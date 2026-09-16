"""Auditable one-sales-unit forecast. Decimal amounts; no network or mutations."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING
from datetime import datetime, timezone

D = lambda v: Decimal(str(v))
CENT = Decimal('0.01')
REQUIRED_COSTS = {
 'commission':'适用跨境佣金', 'transaction':'交易费（含实际支付方式）',
 'installment_extra':'额外分期项目费', 'growth':'卖家增长费',
 'platform_shipping':'平台运费计划费', 'order_processing':'订单处理费',
 'preorder':'预售及其他平台服务费', 'activities':'MDV/返币/直播等活动费',
 'domestic':'中国境内运费', 'warehouse_pack':'云仓/验货/贴标/仓储/包材',
 'sls':'SLS卖家净国际物流', 'ads':'广告预算分摊', 'affiliate':'联盟/达人分摊',
 'returns':'售后退款/拒收/破损净损失准备', 'collection':'收款/换汇/提现',
 'tax':'其他不可抵扣税费', 'overhead':'固定运营成本分摊', 'other':'其他有说明费用'
}
LOGISTICS = {'domestic','warehouse_pack','sls'}
BUDGETABLE = {'ads','affiliate','returns','overhead','other'}
GATES = ['data','demand','competition','supply','logistics','compliance','cash','rights']

def money(v): return D(v).quantize(CENT, rounding=ROUND_HALF_UP)

def stamp(v):
    dt=datetime.fromisoformat(str(v).replace('Z','+00:00'))
    if dt.tzinfo is None: raise ValueError('日期必须含时区')
    return dt

def nonnegative(v):
    try: return not isinstance(v,bool) and D(v).is_finite() and D(v)>=0
    except Exception: return False

def calculate(model, as_of):
    """Return forecast only after cost completeness; no commercial success claim."""
    gaps=[]
    if not model: return {'status':'待补证','gaps':['无逐SKU完整成本输入']}
    try: now=stamp(as_of)
    except Exception: return {'status':'待补证','gaps':['运行时间无效']}
    required=['net_sale_php','extra_subsidy_php','fx','quote_cny','purchase_units',
              'purchase_surcharge_rate','setup_cny','test_orders']
    for k in required:
        if not nonnegative(model.get(k)): gaps.append(k+'缺失或无效')
    for k in ['fx','net_sale_php','purchase_units','test_orders']:
        if nonnegative(model.get(k)) and D(model[k])<=0: gaps.append(k+'须大于0')
    for k in ['purchase_units','test_orders']:
        if nonnegative(model.get(k)) and D(model[k])!=D(model[k]).to_integral_value(): gaps.append(k+'须整数')
    if model.get('costs_reviewed') is not True: gaps.append('费用适用/税项/分摊未核实')
    if not model.get('quote_evidence'): gaps.append('缺逐SKU报价来源')
    try:
        if stamp(model['quote_valid_until'])<now: gaps.append('报价已过期')
        seen=stamp(model['quote_observed_at'])
        if seen>now or (now-seen).total_seconds()>86400: gaps.append('报价非24小时内有效观测')
    except Exception: gaps.append('报价观测或有效期无效')
    lines=model.get('fee_lines',[])
    keys=[x.get('key') for x in lines]
    if len(keys)!=len(set(keys)): gaps.append('费用键重复，先明确分项再汇总')
    for k in REQUIRED_COSTS:
        if k not in keys: gaps.append('缺费项:'+k)
    for x in lines:
        key=x.get('key','?')
        if key not in REQUIRED_COSTS: gaps.append('未映射费项:'+key)
        if not nonnegative(x.get('amount')): gaps.append(key+'金额未知或异常')
        if x.get('currency') not in ['CNY','PHP']: gaps.append(key+'币种未确认')
        if not x.get('evidence') or not x.get('calculation'): gaps.append(key+'缺依据或计算口径')
        status=x.get('status')
        if status not in ['已核实','预算','不适用']: gaps.append(key+'待核实')
        if status=='预算' and key not in BUDGETABLE: gaps.append(key+'不能用预算代替费用核实')
        if status=='不适用' and nonnegative(x.get('amount')) and D(x['amount'])!=0: gaps.append(key+'不适用必须为0且有依据')
        try:
            if stamp(x['valid_until'])<now: gaps.append(key+'已过期')
        except Exception: gaps.append(key+'有效期无效')
        if key=='transaction' and not nonnegative(x.get('stress_amount')): gaps.append('缺高档交易费压力金额')
        if x.get('stress_amount') is not None and not nonnegative(x['stress_amount']): gaps.append(key+'压力金额异常')
    if gaps: return {'status':'待补证','gaps':gaps}
    fx=D(model['fx']); units=D(model['purchase_units']); surcharge=D(model['purchase_surcharge_rate'])
    quote=D(model['quote_cny']); sale=D(model['net_sale_php'])+D(model['extra_subsidy_php'])
    revenue=money(sale*fx)
    if revenue<=0: return {'status':'待补证','gaps':['换汇后收入须大于0']}
    other=Decimal(0); stress_other=Decimal(0); fee_results=[]
    for x in lines:
        a=D(x['amount']); stress=D(x['stress_amount']) if x.get('stress_amount') is not None else a
        if x['key'] in LOGISTICS: stress*=D('1.15')
        base_cny=money(a*(fx if x['currency']=='PHP' else 1))
        stress_cny=money(stress*(fx*D('.95') if x['currency']=='PHP' else 1))
        other+=base_cny; stress_other+=stress_cny
        fee_results.append({'key':x['key'],'base_cny':base_cny,'stress_cny':stress_cny})
    procurement=money(quote*units*(1+surcharge))
    total=procurement+other; profit=revenue-total
    target=max(D(15),revenue*D('.2')).quantize(CENT,rounding=ROUND_CEILING)
    factor=units*(1+surcharge); budget=revenue-other-target
    ceiling=None
    if budget>=0:
        trial=(budget/factor).quantize(CENT,rounding=ROUND_FLOOR)
        # Maximal cent quote under rounded procurement, without iterative unbounded search.
        trial2=((budget+D('.005')-D('.000000000001'))/factor).quantize(CENT,rounding=ROUND_FLOOR)
        ceiling=max(trial,trial2)
        if revenue-other-money(ceiling*factor)<target: ceiling-=CENT
    stress_revenue=money(sale*fx*D('.95'))
    stress_profit=stress_revenue-money(quote*D('1.1')*factor)-stress_other
    test_total=money(D(model['setup_cny'])+D(model['test_orders'])*total)
    max_orders=max(0,int(((D(500)-D(model['setup_cny']))/total).to_integral_value(rounding=ROUND_FLOOR))) if total>0 else None
    ok=profit>=target and stress_profit>=0 and test_total<=500
    return {'status':'成本条件通过' if ok else '成本条件不通过','gaps':[],
      'revenue_cny':revenue,'other_cny':other,'procurement_cny':procurement,'total_cost_cny':total,
      'profit_cny':profit,'margin':profit/revenue,'target_profit_cny':target,
      'quote_ceiling_cny':ceiling,'ceiling_note':'' if ceiling is not None else '即使采购0元也不满足利润目标',
      'stress_other_cny':stress_other,'stress_profit_cny':stress_profit,
      'test_total_cny':test_total,'max_test_orders':max_orders,'fee_results':fee_results}

def evaluate(candidate, as_of):
    r=calculate(candidate.get('model'),as_of)
    states=candidate.get('gates',{})
    if '不通过' in states.values(): decision='当前方案不通过'
    elif r['status']=='成本条件不通过': decision='当前方案不通过'
    elif all(states.get(k)=='通过' for k in GATES) and r['status']=='成本条件通过': decision='可进入人工测品审核'
    else: decision='待补证'
    r['decision']=decision
    return r
