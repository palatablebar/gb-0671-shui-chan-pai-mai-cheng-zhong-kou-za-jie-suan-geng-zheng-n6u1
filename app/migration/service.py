"""迁移服务：收集封存批 → 内存裁决 → 单事务提交，失败整体回滚。"""
from app import store
from app.migration.rules import plan_migration
from app.migration.seed import seed_historical


def run_migration(path):
    sealed=[store.get(path, r['id']) for r in store.list_runs(path)]
    plan, new_runs=plan_migration(sealed)
    migration_id=store.commit_migration(path, plan, new_runs)
    return store.get_migration(path, migration_id)


def seed(path):
    return seed_historical(path)
