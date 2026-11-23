"""扣杂口径迁移裁决测试：可迁移/留旧待核分支、证据不丢失、重跑批次一致、失败回滚。"""
import sqlite3
from decimal import Decimal

import pytest

from app import store
from app.config import RULE_VERSION, RULE_VERSION_V2
from app.engine import evaluate
from app.migration import service
from app.migration.rules import plan_migration
from app.migration.seed import seed_historical


@pytest.fixture
def seeded(tmp_path):
    path=str(tmp_path/'migration.sqlite')
    seed_historical(path)
    return path


def test_seed_is_idempotent(seeded):
    before={r['id']:r['digest'] for r in store.list_runs(seeded)}
    again=seed_historical(seeded)
    assert again['count']==0
    after={r['id']:r['digest'] for r in store.list_runs(seeded)}
    assert before==after


def test_migration_summary_branches(seeded):
    plan=service.run_migration(seeded)
    assert plan['summary']=={'candidates':9,'migrated':4,'blocked':5,'excluded':2}
    statuses={b['run_id']:b for b in plan['batches']}
    assert statuses['MIG-H1-000000001']['status']=='可迁移'
    assert statuses['MIG-H1-000000001']['amount_delta']=='0.05'
    assert statuses['MIG-H2-000000002']['amount_delta']=='0.00'


def test_block_reason_codes(seeded):
    plan=service.run_migration(seeded)
    reasons={b['run_id']:b['block_reasons'] for b in plan['batches'] if b['block_reasons']}
    assert reasons['MIG-H5-000000005']==['MIG_SNAPSHOT_MISSING']
    assert 'MIG_INPUT_MISMATCH' in reasons['MIG-H6-000000006']
    assert reasons['MIG-H7-000000007']==['MIG_QUARANTINE_MISMATCH']
    assert 'MIG_AMOUNT_MISMATCH' in reasons['MIG-H8-000000008']
    assert reasons['MIG-H9-000000009']==['MIG_SEAL_MISMATCH']
    for b in plan['batches']:
        if b['status']=='留旧待核':
            assert b['migrated_run_id']=='' and b['new_amount']==''


def test_excluded_not_counted(seeded):
    plan=service.run_migration(seeded)
    ids={e['run_id']:e['reason'] for e in plan['excluded']}
    assert ids=={'MIG-H10-000000010':'OUT_OF_WINDOW','MIG-H11-000000011':'NOT_SEALED'}
    candidate_ids={b['run_id'] for b in plan['batches']}
    assert set(ids).isdisjoint(candidate_ids)


def test_rerun_same_id_and_batch_count(seeded):
    first=service.run_migration(seeded)
    second=service.run_migration(seeded)
    assert first['migration_id']==second['migration_id']
    assert first['digest']==second['digest']
    assert len(first['batches'])==len(second['batches'])==9
    assert [(b['run_id'],b['status']) for b in first['batches']]==[(b['run_id'],b['status']) for b in second['batches']]
    assert len(store.list_migrations(seeded))==1
    # 新封存批重跑不重复写入：11 原始 + 4 迁移新批
    assert len(store.list_runs(seeded))==15


def test_old_batches_and_snapshots_untouched(seeded):
    before={r['id']:r['digest'] for r in store.list_runs(seeded)}
    service.run_migration(seeded)
    after={r['id']:r['digest'] for r in store.list_runs(seeded)}
    for run_id, digest_value in before.items():
        assert after[run_id]==digest_value
    h1=store.get(seeded,'MIG-H1-000000001')
    assert h1['manifest']['rule_version']==RULE_VERSION
    assert 'input_snapshot' in h1 and h1['archive']['seal']


def test_new_run_carries_new_rule_and_basis(seeded):
    plan=service.run_migration(seeded)
    for b in plan['batches']:
        if b['status']!='可迁移':
            continue
        new=store.get(seeded,b['migrated_run_id'])
        assert new['manifest']['rule_version']==RULE_VERSION_V2
        assert new['manifest']['migrated_from']==b['run_id']
        assert new['status']=='已封存'
        assert new['input_snapshot']['bytes_b64']==store.get(seeded,b['run_id'])['input_snapshot']['bytes_b64']
        assert new['balance']['row_balanced'] and new['balance']['money_balanced']
        assert new['balance']['amount']==b['new_amount']


def test_snapshot_missing_never_replaces_current(seeded):
    h5=store.get(seeded,'MIG-H5-000000005')
    assert 'input_snapshot' not in h5
    service.run_migration(seeded)
    again=store.get(seeded,'MIG-H5-000000005')
    assert again['balance']['amount']==h5['balance']['amount']
    assert again['archive']['seal']==h5['archive']['seal']


def test_commit_rollback_keeps_everything(tmp_path, monkeypatch):
    path=str(tmp_path/'rollback.sqlite')
    seed_historical(path)
    original=store.commit_migration
    def failing_commit(db, plan, new_runs):
        con=store.connect(db)
        try:
            with con:
                for result in new_runs:
                    con.execute('INSERT OR IGNORE INTO runs(id,digest,result,status,revision) VALUES(?,?,?,?,?)',
                                (result['manifest']['run_id'],result['manifest']['sha256'],'{}','已封存',1))
                raise RuntimeError('模拟切换失败')
        finally:
            con.close()
    monkeypatch.setattr(store,'commit_migration',failing_commit)
    with pytest.raises(RuntimeError):
        service.run_migration(path)
    monkeypatch.undo()
    # 失败后无迁移记录、无新批，原始 11 批与快照完好
    assert store.list_migrations(path)==[]
    runs=store.list_runs(path)
    assert len(runs)==11
    for r in runs:
        full=store.get(path,r['id'])
        if r['id']!='MIG-H5-000000005':
            assert 'input_snapshot' in full
        assert full['archive']['seal']


def test_rollback_on_broken_db(tmp_path, monkeypatch):
    path=str(tmp_path/'broken.sqlite')
    seed_historical(path)
    def broken_commit(db, plan, new_runs):
        con=store.connect(db)
        try:
            with con:
                con.execute('INSERT INTO migrations(id,digest,result,created_at) VALUES(?,?,?,?)',
                            ('X','Y','{}','Z'))
                con.execute('INSERT INTO no_such_table VALUES(1)')
        finally:
            con.close()
    monkeypatch.setattr(store,'commit_migration',broken_commit)
    with pytest.raises(sqlite3.OperationalError):
        service.run_migration(path)
    assert store.list_migrations(path)==[]
    assert len(store.list_runs(path))==11


def test_balance_invariant_for_migrated(seeded):
    plan=service.run_migration(seeded)
    for b in plan['batches']:
        if b['status']=='可迁移':
            new=store.get(seeded,b['migrated_run_id'])
            total=Decimal(new['balance']['amount'])
            assert total==Decimal(new['balance']['paid'])+Decimal(new['balance']['due'])


def test_migration_digest_stable_across_plans(seeded):
    sealed=[store.get(seeded,r['id']) for r in store.list_runs(seeded)]
    p1,_=plan_migration(sealed)
    p2,_=plan_migration(list(reversed(sealed)))
    assert store.migration_digest(p1)==store.migration_digest(p2)
    assert [b['run_id'] for b in p1['batches']]==[b['run_id'] for b in p2['batches']]


def test_seed_rule_versions_are_legacy(seeded):
    for r in store.list_runs(seeded):
        full=store.get(seeded,r['id'])
        if full['manifest'].get('sealed_at'):
            assert full['manifest']['rule_version']==RULE_VERSION
