"""Isolated synthetic tests. These are not candidates, prices or market evidence."""
import copy,random
from selection_math import *

NOW='2026-09-15T16:00:00+08:00'
def fixture():
    lines=[]
    amounts={'commission':(100,'PHP'),'transaction':(50,'PHP'),'domestic':(10,'CNY'),
             'warehouse_pack':(5,'CNY'),'sls':(20,'CNY'),'ads':(7,'CNY')}
    for k in REQUIRED_COSTS:
        a,c=amounts.get(k,(0,'CNY'))
        line=dict(key=k,amount=a,currency=c,status='已核实',evidence='隔离合成测试',
                  calculation='仅为算法测试，不是事实费率',valid_until='2026-09-16T16:00:00+08:00')
        if k=='transaction': line['stress_amount']=100
        lines.append(line)
    return dict(net_sale_php=1000,extra_subsidy_php=0,fx='.12',quote_cny=10,purchase_units=1,
      purchase_surcharge_rate=0,setup_cny=50,test_orders=5,fee_lines=lines,costs_reviewed=True,
      quote_evidence='隔离测试SKU',quote_observed_at=NOW,quote_valid_until='2026-09-16T16:00:00+08:00')

def run():
    m=fixture(); r=calculate(m,NOW)
    assert r['revenue_cny']==120 and r['other_cny']==60 and r['profit_cny']==50
    assert r['quote_ceiling_cny']==36 and r['stress_profit_cny']==D('32.95')
    assert r['test_total_cny']==400 and r['max_test_orders']==6
    m['test_orders']=7; assert calculate(m,NOW)['status']=='成本条件不通过'
    for key in ['fx','quote_cny','setup_cny']:
        m=fixture();m[key]=None;assert calculate(m,NOW)['status']=='待补证'
    m=fixture();m['fee_lines'].pop();assert calculate(m,NOW)['status']=='待补证'
    m=fixture();m['quote_observed_at']='2026-09-13T16:00:00+08:00';assert calculate(m,NOW)['status']=='待补证'
    m=fixture();m['fee_lines'][0]['currency']='THB';assert calculate(m,NOW)['status']=='待补证'
    m=fixture();m['fee_lines'][0]['status']='预算';assert calculate(m,NOW)['status']=='待补证'
    m=fixture();m['fee_lines'][0]['amount']=-1;assert calculate(m,NOW)['status']=='待补证'
    m=fixture();m['fee_lines'][1].pop('stress_amount');assert calculate(m,NOW)['status']=='待补证'
    m=fixture();m['net_sale_php']=50;assert calculate(m,NOW)['quote_ceiling_cny'] is None
    c={'model':fixture(),'gates':{k:'通过' for k in GATES}}
    assert evaluate(c,NOW)['decision']=='可进入人工测品审核'
    c['gates']['rights']='待补证';assert evaluate(c,NOW)['decision']=='待补证'
    c['gates']['rights']='不通过';assert evaluate(c,NOW)['decision']=='当前方案不通过'
    # Independent brute-force cent grid verifies the exact affordable quote boundary.
    rng=random.Random(1509)
    for _ in range(100):
        m=fixture();m['purchase_units']=rng.randint(1,6);m['purchase_surcharge_rate']=str(rng.choice([0,.01,.03,.13]))
        m['net_sale_php']=rng.randint(400,1500);r=calculate(m,NOW)
        revenue=(D(m['net_sale_php'])*D('.12')).quantize(CENT,rounding=ROUND_HALF_UP)
        target=max(D(15),revenue/D(5)).quantize(CENT,rounding=ROUND_CEILING)
        f=D(m['purchase_units'])*(1+D(m['purchase_surcharge_rate']))
        feasible=[D(i)/100 for i in range(12001) if revenue-D(60)-(D(i)/100*f).quantize(CENT,rounding=ROUND_HALF_UP)>=target]
        expected=max(feasible) if feasible else None
        assert expected==r['quote_ceiling_cny'],(expected,r)
    return '通过：基础/压力/500元边界、缺值/过期/币种/费用/权限门槛，以及100组采购上限独立穷举'

if __name__=='__main__': print(run())
