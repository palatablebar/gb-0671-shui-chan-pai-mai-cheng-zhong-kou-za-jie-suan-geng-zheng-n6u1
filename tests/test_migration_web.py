"""迁移模块的 HTTP 与页面集成测试。"""
from fastapi.testclient import TestClient
from app import main


def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main,'DB_PATH',str(tmp_path/'web.sqlite'))
    return TestClient(main.app)


def test_migration_page_empty(tmp_path, monkeypatch):
    c=client(tmp_path,monkeypatch)
    r=c.get('/migration')
    assert r.status_code==200
    assert '口径迁移' in r.text and '尚无迁移结果' in r.text


def test_seed_and_migrate_api(tmp_path, monkeypatch):
    c=client(tmp_path,monkeypatch)
    seed=c.post('/api/migration/seed').json()
    assert seed['count']==11
    plan=c.post('/api/migration/runs').json()
    assert plan['summary']['candidates']==9
    assert plan['summary']['migrated']==4
    assert plan['summary']['blocked']==5
    mid=plan['migration_id']
    listed=c.get('/api/migration/runs').json()
    assert [m['id'] for m in listed]==[mid]
    assert c.get(f'/api/migration/runs/{mid}').json()['migration_id']==mid
    assert c.get('/api/migration/runs/unknown').status_code==404


def test_migration_page_shows_every_batch(tmp_path, monkeypatch):
    c=client(tmp_path,monkeypatch)
    c.post('/api/migration/seed')
    plan=c.post('/api/migration/runs').json()
    html=c.get('/migration').text
    for b in plan['batches']:
        assert b['run_id'] in html
        assert b['old_rule_version'] in html and b['new_rule_version'] in html
        assert b['old_amount'] in html
    assert 'MIG_SNAPSHOT_MISSING' not in html or '源快照缺失' in html
    assert '源快照缺失，不得替换现行版本' in html
    assert '留旧待核' in html and '可迁移' in html


def test_migration_idempotent_over_http(tmp_path, monkeypatch):
    c=client(tmp_path,monkeypatch)
    c.post('/api/migration/seed')
    a=c.post('/api/migration/runs').json()
    b=c.post('/api/migration/runs').json()
    assert a['migration_id']==b['migration_id']
    assert len(c.get('/api/migration/runs').json())==1
    runs=c.get('/api/runs').json()
    assert len(runs)==15


def test_new_migrated_run_navigable_and_exportable(tmp_path, monkeypatch):
    c=client(tmp_path,monkeypatch)
    c.post('/api/migration/seed')
    plan=c.post('/api/migration/runs').json()
    target=next(b for b in plan['batches'] if b['status']=='可迁移')
    page=c.get(f"/archive?run_id={target['migrated_run_id']}")
    assert page.status_code==200
    export=c.get(f"/api/export/{target['migrated_run_id']}")
    assert export.status_code==200
    assert target['migrated_run_id'] in c.get('/migration').text


def test_existing_pipeline_still_works_alongside(tmp_path, monkeypatch):
    c=client(tmp_path,monkeypatch)
    run=c.post('/api/runs',json={}).json()
    assert run['manifest']['rule_version']=='2026.11.17-r2'
    c.post('/api/migration/seed')
    plan=c.post('/api/migration/runs').json()
    assert plan['old_rule_version']=='2026.11.17-r2'
    assert plan['new_rule_version']=='2026.11.20-r3'
    # 常规重跑路径不受规则版本参数影响
    again=c.post(f"/api/runs/{run['manifest']['run_id']}/rerun").json()
    assert again['manifest']['run_id']==run['manifest']['run_id']
