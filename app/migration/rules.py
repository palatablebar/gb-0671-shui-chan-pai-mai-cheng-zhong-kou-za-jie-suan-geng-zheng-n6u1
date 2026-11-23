"""扣杂口径升级迁移裁决。

裁决原则：
1. 仅近三个月窗口内、已封存、旧规则版本的批次进入候选；窗口外/未封存为排除项，不计批次数量。
2. 每个候选先做源快照核验，再以旧规则重算并与封存证据对平（输入行、隔离数、金额、封存指纹）。
3. 旧口径对平后才允许新口径重算；新口径必须守恒（行守恒、金额守恒、无新增阻断）且输入行/隔离数不变。
4. 任一核验失败即阻断，保留现行（旧）版本，记录原因码；全部通过才生成新封存批，旧批原样保留。
5. 所有重算在内存完成，由存储层单事务提交；同一候选集合重跑得到同一迁移批号与相同批次数。
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.config import RULE_VERSION, RULE_VERSION_V2, MIGRATION_WINDOW_DAYS
from app.engine import evaluate
from app.reasons import REASONS
from app.modules.archive.rules import archive_decision


def parse_instant(value):
    try:
        dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if dt.tzinfo is None:
            return None
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def money_delta(new_value, old_value):
    return format((Decimal(new_value)-Decimal(old_value)).quantize(Decimal('.01')), 'f')


def recompute(snapshot, rule_version):
    """基于不可变源快照按指定规则版本重算，不读取也不改动任何已封存记录。"""
    return evaluate({'dataset':'snapshot'}, snapshot=snapshot, rule_version=rule_version)


def verify_legacy(stored, replica):
    """旧规则重算结果须与封存证据逐项对平。"""
    failures=[]
    if stored['counts'].get('input') != replica['counts'].get('input'):
        failures.append('MIG_INPUT_MISMATCH')
    if len(stored.get('quarantine', [])) != len(replica.get('quarantine', [])):
        failures.append('MIG_QUARANTINE_MISMATCH')
    if stored['balance'].get('amount') != replica['balance'].get('amount'):
        failures.append('MIG_AMOUNT_MISMATCH')
    seal=archive_decision(replica)['seal']
    if stored.get('archive', {}).get('seal') != seal:
        failures.append('MIG_SEAL_MISMATCH')
    return failures, seal


def verify_new(replica_old, replica_new):
    """新口径重算不得改变输入结构，且必须通过守恒校验。"""
    failures=[]
    if replica_old['counts'].get('input') != replica_new['counts'].get('input'):
        failures.append('MIG_INPUT_MISMATCH')
    if len(replica_old.get('quarantine', [])) != len(replica_new.get('quarantine', [])):
        failures.append('MIG_QUARANTINE_MISMATCH')
    balance=replica_new['balance']
    if not (balance['row_balanced'] and balance['money_balanced'] and not balance['blocked']):
        failures.append('MIG_NEW_UNBALANCED')
    return failures


def build_batch(stored, now, window_days):
    """对单个已封存批次形成裁决行；不通过时只返回原因，不产生新版本。"""
    run_id=stored['manifest']['run_id']
    sealed_at=stored['manifest'].get('sealed_at')
    sealed_dt=parse_instant(sealed_at)
    base={
        'run_id':run_id,
        'source':stored.get('source'),
        'sealed_at':sealed_at,
        'old_rule_version':stored['manifest'].get('rule_version'),
        'new_rule_version':RULE_VERSION_V2,
        'status':'留旧待核',
        'block_reasons':[],
        'migrated_run_id':'',
        'snapshot_digest':'',
        'input_rows':stored['counts'].get('input'),
        'quarantine_rows':len(stored.get('quarantine', [])),
        'tickets':len(stored.get('final', [])),
        'old_amount':stored['balance'].get('amount'),
        'new_amount':'',
        'amount_delta':'',
        'old_seal':stored.get('archive', {}).get('seal'),
        'new_seal':'',
    }

    snapshot=stored.get('input_snapshot')
    if not snapshot or 'bytes_b64' not in snapshot or 'context' not in snapshot:
        base['block_reasons']=['MIG_SNAPSHOT_MISSING']
        return base, None
    base['snapshot_digest']=stored['manifest'].get('sha256','')

    # 旧规则重算：先证明封存证据可复现，才允许进入新口径。
    replica_old=recompute(snapshot, RULE_VERSION)
    failures, old_seal=verify_legacy(stored, replica_old)
    if failures:
        base['block_reasons']=failures
        return base, None

    # 新规则重算与守恒核验。
    replica_new=recompute(snapshot, RULE_VERSION_V2)
    failures=verify_new(replica_old, replica_new)
    if failures:
        base['block_reasons']=failures
        return base, None

    new_amount=replica_new['balance']['amount']
    replica_new['manifest'].update({
        'migrated_from':run_id,
        'sealed_at':now.isoformat(),
        'migration_basis':'源快照重算；旧批封存证据原样保留',
    })
    base.update({
        'status':'可迁移',
        'migrated_run_id':replica_new['manifest']['run_id'],
        'new_amount':new_amount,
        'amount_delta':money_delta(new_amount, base['old_amount']),
        'new_seal':archive_decision(replica_new)['seal'],
    })
    return base, replica_new


def plan_migration(runs, now=None, window_days=MIGRATION_WINDOW_DAYS):
    """汇总候选裁决，返回迁移计划与待写入的新封存批（均为内存对象）。"""
    now=now or datetime.now(timezone.utc)
    cutoff=now-timedelta(days=window_days)
    batches=[]
    excluded=[]
    new_runs=[]
    for stored in sorted(runs, key=lambda r: r['manifest']['run_id']):
        run_id=stored['manifest']['run_id']
        sealed_dt=parse_instant(stored['manifest'].get('sealed_at'))
        if stored.get('status') != '已封存' or sealed_dt is None:
            excluded.append({'run_id':run_id, 'reason':'NOT_SEALED', 'detail':'未封存批次不在迁移范围'})
            continue
        if sealed_dt < cutoff:
            excluded.append({'run_id':run_id, 'reason':'OUT_OF_WINDOW',
                             'detail':f'封存于 {sealed_dt.date()}，超出近{window_days}天窗口'})
            continue
        if stored['manifest'].get('rule_version') != RULE_VERSION:
            excluded.append({'run_id':run_id, 'reason':'NOT_LEGACY_RULE',
                             'detail':f"规则版本 {stored['manifest'].get('rule_version')} 非旧口径"})
            continue
        row, new_run=build_batch(stored, now, window_days)
        batches.append(row)
        if new_run is not None:
            new_runs.append(new_run)

    migrated=sum(1 for b in batches if b['status']=='可迁移')
    blocked=len(batches)-migrated
    plan={
        'old_rule_version':RULE_VERSION,
        'new_rule_version':RULE_VERSION_V2,
        'window_days':window_days,
        'generated_at':now.isoformat(),
        'cutoff_at':cutoff.isoformat(),
        'summary':{
            'candidates':len(batches),
            'migrated':migrated,
            'blocked':blocked,
            'excluded':len(excluded),
        },
        'totals':{
            'old_amount':format(sum((Decimal(b['old_amount']) for b in batches), Decimal(0)), '.2f'),
            'new_amount':format(sum((Decimal(b['new_amount']) for b in batches if b['new_amount']), Decimal(0)), '.2f'),
        },
        'batches':batches,
        'excluded':excluded,
        'reason_text':REASONS,
    }
    return plan, new_runs
