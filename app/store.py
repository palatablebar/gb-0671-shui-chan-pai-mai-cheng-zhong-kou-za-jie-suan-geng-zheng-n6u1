import sqlite3, json, hashlib
from datetime import datetime, timezone
from pathlib import Path
from app.errors import BusinessError

def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con=sqlite3.connect(path,timeout=15)
    con.row_factory=sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, result TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT '待复核')")
    con.execute("CREATE TABLE IF NOT EXISTS migrations (id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL)")
    return con

def save(path, result):
    run_id=result['manifest']['run_id']
    with connect(path) as con:
        con.execute('INSERT OR IGNORE INTO runs(id,digest,result) VALUES(?,?,?)', (run_id,result['manifest']['sha256'],json.dumps(result,ensure_ascii=False)))
    return get(path,run_id)

def save_sealed(path, result, status='已封存'):
    """写入历史封存批；显式状态写入，不覆盖已存在批次。"""
    run_id=result['manifest']['run_id']
    with connect(path) as con:
        con.execute('INSERT OR IGNORE INTO runs(id,digest,result,status,revision) VALUES(?,?,?,?,?)',
                    (run_id,result['manifest']['sha256'],json.dumps(result,ensure_ascii=False),status,result.get('revision',1)))
    return get(path,run_id)

def get(path, run_id):
    with connect(path) as con: row=con.execute('SELECT * FROM runs WHERE id=?',(run_id,)).fetchone()
    if not row: raise BusinessError('NOT_FOUND','批次不存在',404)
    result=json.loads(row['result']);result.update(revision=row['revision'],status=row['status'])
    return result

def list_runs(path):
    with connect(path) as con: return [dict(r) for r in con.execute('SELECT id,digest,result,status,revision FROM runs ORDER BY rowid')]

def history(path):
    with connect(path) as con:
        return [dict(r) for r in con.execute('SELECT id,revision,status FROM runs ORDER BY rowid DESC LIMIT 100')]

def review(path,run_id,revision):
    with connect(path) as con:
        cur=con.execute('UPDATE runs SET revision=revision+1,status=? WHERE id=? AND revision=?',('已复核',run_id,revision))
        if cur.rowcount!=1:
            if not con.execute('SELECT 1 FROM runs WHERE id=?',(run_id,)).fetchone():
                raise BusinessError('NOT_FOUND','批次不存在',404)
            raise BusinessError('STALE_VERSION','复核版本已更新，请刷新',409)
    return get(path,run_id)

def migration_digest(plan):
    """同一候选集合（旧批 id 有序列表）+新规则版本 → 同一迁移指纹。"""
    payload={'candidates':[b['run_id'] for b in plan['batches']],
             'new_rule_version':plan['new_rule_version'],
             'window_days':plan['window_days']}
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def commit_migration(path, plan, new_runs):
    """单事务：迁移批与新封存批同时落库；任何异常整体回滚，旧批与快照不动。"""
    digest_value=migration_digest(plan)
    migration_id=digest_value[:16]
    created=datetime.now(timezone.utc).isoformat()
    con=connect(path)
    try:
        with con:
            for result in new_runs:
                con.execute('INSERT OR IGNORE INTO runs(id,digest,result,status,revision) VALUES(?,?,?,?,?)',
                            (result['manifest']['run_id'],result['manifest']['sha256'],
                             json.dumps(result,ensure_ascii=False),'已封存',result.get('revision',1)))
            con.execute('INSERT OR IGNORE INTO migrations(id,digest,result,created_at) VALUES(?,?,?,?)',
                        (migration_id,digest_value,json.dumps(plan,ensure_ascii=False),created))
    finally:
        con.close()
    return migration_id

def get_migration(path, migration_id):
    with connect(path) as con:
        row=con.execute('SELECT * FROM migrations WHERE id=?',(migration_id,)).fetchone()
    if not row: raise BusinessError('NOT_FOUND','迁移结果不存在',404)
    result=json.loads(row['result'])
    result.update(migration_id=row['id'],digest=row['digest'],created_at=row['created_at'])
    return result

def list_migrations(path):
    with connect(path) as con:
        rows=con.execute('SELECT id,digest,created_at FROM migrations ORDER BY rowid DESC LIMIT 100').fetchall()
    return [dict(r) for r in rows]
