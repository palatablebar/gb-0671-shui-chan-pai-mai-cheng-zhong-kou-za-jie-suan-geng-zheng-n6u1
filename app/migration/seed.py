"""近三个月已封存历史批次的确定性播种器。

覆盖裁决所需的全部分支：可迁移（金额有变化/无变化/更正链/含隔离行）、
快照缺失、输入行对不平、隔离数对不平、金额对不平、封存指纹被改写、窗口外、未封存。
数据为虚构票据，不接入真实秤台与支付渠道。重跑播种幂等，不覆盖已存在批次。
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from app import store
from app.config import RULE_VERSION, RULE_VERSION_V2
from app.engine import evaluate

HEADER='id,ticket,kind,weight,unit,fish,price,rate,version,replaces,paid'


def row(id_, ticket, kind, weight, fish='黄鱼', price='12.30', rate='0.05',
        version='1', replaces='', paid='0', unit='kg'):
    return ','.join([id_, ticket, kind, weight, unit, fish, price, rate, version, replaces, paid])


def gross(id_, ticket, weight, **kw):
    return row(id_+'-G', ticket, 'gross', weight, **kw)


def tare(id_, ticket, weight, **kw):
    return row(id_+'-T', ticket, 'tare', weight, **kw)


def make_run(csv_text, run_id, sealed_at, source='migration-seed'):
    state=evaluate({'dataset':'dirty', 'csv_text':csv_text}, rule_version=RULE_VERSION)
    state['source']=source
    state['manifest']['run_id']=run_id
    state['manifest']['sealed_at']=sealed_at
    state['manifest']['sealed_rule_version']=RULE_VERSION
    return state


def at(days_ago, hour=2):
    dt=datetime.now(timezone.utc)-timedelta(days=days_ago)
    return dt.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()


def seed_historical(path, now=None):
    now=now or datetime.now(timezone.utc)
    existing={r['id'] for r in store.list_runs(path)}
    inserted=[]

    def put(state, run_id, status='已封存'):
        if run_id in existing:
            return
        store.save_sealed(path, state, status=status)
        existing.add(run_id)
        inserted.append(run_id)

    # H1 健康批：净重88kg、扣杂率0.123。
    # 旧口径计价重 88×(1-0.123)=77.176kg（量化0.001）→ 77.176×12.30=949.2648→949.26；
    # 新口径先量化到0.01kg=77.18kg → 77.18×12.30=949.314→949.31，金额差 +0.05，可直观对比。
    h1=make_run('\n'.join([HEADER,
        gross('H1','01001','100', rate='0.123'), tare('H1','01001','12', rate='0.123')]),
        'MIG-H1-000000001', at(10))
    put(h1, 'MIG-H1-000000001')

    # H2 健康批：计价重恰好到 0.01，新旧金额一致（delta=0.00）。
    h2=make_run('\n'.join([HEADER, gross('H2','01002','100'), tare('H2','01002','10')]),
                'MIG-H2-000000002', at(20))
    put(h2, 'MIG-H2-000000002')

    # H3 更正链：v1 被 v2 替代，已付取最大累计值。
    h3_lines=[HEADER,
        gross('H3A','01003','100', version='1'), tare('H3A','01003','10', version='1'),
        gross('H3B','01003','102', version='2', replaces='1', paid='900'),
        tare('H3B','01003','10', version='2', replaces='1', paid='900')]
    h3=make_run('\n'.join(h3_lines), 'MIG-H3-000000003', at(35))
    put(h3, 'MIG-H3-000000003')

    # H4 脏批：含空行、重复表头、同编号冲突隔离，结构守恒，仍可迁移。
    h4_lines=[HEADER,
        gross('H4A','01004','100'), tare('H4A','01004','10'),
        '', HEADER,
        'H4B-G,01005,gross,100,kg,黄鱼,12.30,0.05,1,,0',
        'H4B-G,01005,gross,101,kg,黄鱼,12.30,0.05,1,,0',
        'H4B-T,01005,tare,10,kg,黄鱼,12.30,0.05,1,,0']
    h4=make_run('\n'.join(h4_lines), 'MIG-H4-000000004', at(55))
    put(h4, 'MIG-H4-000000004')

    # H5 源快照缺失：不得替换现行版本，直接阻断。
    h5=make_run('\n'.join([HEADER, gross('H5','01006','100'), tare('H5','01006','10')]),
                'MIG-H5-000000005', at(15))
    h5.pop('input_snapshot', None)
    put(h5, 'MIG-H5-000000005')

    # H6 封存输入被改写：源快照重算输入行对不平，封存指纹同时失配。
    h6=make_run('\n'.join([HEADER, gross('H6','01007','100'), tare('H6','01007','10')]),
                'MIG-H6-000000006', at(25))
    h6['records'][0]['weight_kg']='999'
    h6['counts']['input']=h6['counts']['input']+1
    put(h6, 'MIG-H6-000000006')

    # H7 隔离清单被追加：隔离数无法与重算对平。
    h7=make_run('\n'.join([HEADER, gross('H7','01008','100'), tare('H7','01008','10')]),
                'MIG-H7-000000007', at(40))
    h7['quarantine'].append({'line':999, 'id':'H7-FAKE', 'code':'MISSING_VALUE',
                             'detail':'播种：事后追加的隔离行', 'raw':{}})
    put(h7, 'MIG-H7-000000007')

    # H8 封存金额被改写：金额对不平（封存指纹随之失配）。
    h8=make_run('\n'.join([HEADER, gross('H8','01009','100'), tare('H8','01009','10')]),
                'MIG-H8-000000008', at(45))
    h8['balance']['amount']='0.01'
    put(h8, 'MIG-H8-000000008')

    # H9 仅封存指纹被改写：金额等仍可对平，只剩指纹失配。
    h9=make_run('\n'.join([HEADER, gross('H9','01010','100'), tare('H9','01010','10')]),
                'MIG-H9-000000009', at(60))
    h9['archive']['seal']='0'*64
    put(h9, 'MIG-H9-000000009')

    # H10 窗口外（91天前封存）：健康但排除，不进入迁移批次数。
    h10=make_run('\n'.join([HEADER, gross('H10','01011','100'), tare('H10','01011','10')]),
                 'MIG-H10-000000010', at(91))
    put(h10, 'MIG-H10-000000010')

    # H11 未封存（无 sealed_at，状态待复核）：排除项。
    h11=make_run('\n'.join([HEADER, gross('H11','01012','100'), tare('H11','01012','10')]),
                 'MIG-H11-000000011', now.isoformat())
    h11['manifest'].pop('sealed_at', None)
    put(h11, 'MIG-H11-000000011', status='待复核')

    return {'inserted':inserted, 'count':len(inserted),
            'skipped':sorted(set([f'MIG-H{i}-0000000{i:02d}' for i in range(1,12)])-set(inserted))}
