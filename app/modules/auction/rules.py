from decimal import Decimal, ROUND_HALF_UP
from app.coerce import money
from app.config import RULE_VERSION, BILLABLE_QUANT

def settle(pair, rule_version=RULE_VERSION):
    quant=BILLABLE_QUANT.get(rule_version, BILLABLE_QUANT[RULE_VERSION])
    billable=(Decimal(pair['net_kg'])*(1-Decimal(pair['rate']))).quantize(Decimal(quant),rounding=ROUND_HALF_UP)
    return {**pair,'billable_kg':str(billable),'amount':money(billable*Decimal(pair['price']))}

def apply(state):
    rule_version=state.get('rule_version',RULE_VERSION)
    state['settlements']=[settle(p,rule_version) for p in state['pairs']]
    total=sum((Decimal(p['amount']) for p in state['settlements']),Decimal(0))
    state['views']['auction']={'title':'扣杂结算','rows':state['settlements'],'metrics':{'版本票':len(state['settlements']),'金额_CNY':money(total)}}
