import copy,json,sys
from pathlib import Path
from decimal import Decimal as D
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.costs import compute,platform_shipping,logistics,warehouse,EXTRAS
from backend.domain import evaluate,current_hash,supplier_view
def scenario():
    settings={'activity_factor':'.4','activity_confirmed':True,'fx_cny_per_php':'.12','commission_pct':'10','transaction_pct':'2','transaction_stress_pct':'2','program_pct':'0','transaction_base':'sale','warehouse_plan':'A'}
    f={k:'0' for k in EXTRAS}
    f.update(list_price_php='1000',purchase_price_cny='5',purchase_units='1',cash_subsidy_php='0',weight_kg='.1',length_cm='12',width_cm='8',height_cm='1',warehouse_skus='1',test_orders='3',test_setup_cny='10',test_spent_cny='0',channel='standard')
    return {'financial':f,'spec':'隔离测试','checks':{},'category_ids':[]},settings
def test_official_round_and_cap():
    assert platform_shipping(D(300))==D(17)
    assert platform_shipping(D(2250))==D(100)
    assert platform_shipping(D(300),items=2)==D(34)
def test_actual_workbook_boundaries():
    assert logistics('.05',12,8,1,'standard')['seller_sls_php']=='23.00'
    assert logistics('.0501',12,8,1,'standard')['seller_sls_php']=='27.50'
    assert logistics('.15',12,8,1,'sea',['999999'])['seller_sls_php']=='65.00'
    assert logistics('.5',12,8,1,'sea',['999999'])['seller_sls_php']=='131.50'
    assert logistics('.5',150,10,10,'sea',['999999'])['problems']
    assert not logistics('.5',150,10,10,'standard')['problems']
    assert logistics('.5',100,100,100,'sea',['999999'])['problems']
def test_zero_dimensions_and_ban_fail_closed():
    x=logistics('.1',0,0,0,'sea',['100072']);assert x['problems'] and x['sea_matches']
def test_baseline_hand_math_and_discount():
    c,s=scenario();x=compute(c,s)
    # 400 PHP sales; commission40, transaction8, platform22, infra5, SLS45.5 => net279.5 PHP.
    # Withdrawal279.5*.12*.002=.07; purchase5+warehouse2.5+platform120.5*.12+.07=22.03.
    assert x['sale_php']=='400.00' and x['full_cost_cny']=='22.03'
    assert x['profit_cny']=='25.97' and x['test_total_cny']=='76.09'
    assert x['complete'] and x['threshold_pass']
    assert next(y for y in x['lines'] if y['name'].startswith('提现'))['cny']=='0.07'
def test_missing_never_zero_and_no_premature_approval():
    c,s=scenario();c['financial']['tax_cny']=None;x=compute(c,s)
    assert x['full_cost_cny'] is None and not x['complete']
    c,s=scenario();s['activity_confirmed']=False;assert not compute(c,s)['complete']
    ev=evaluate(c,s,[]);assert not ev['eligible']
def test_negative_profit_does_not_crash():
    c,s=scenario();c['financial']['purchase_price_cny']='60';x=evaluate(c,s,[])
    assert D(x['base']['profit_cny'])<0 and not x['eligible']
def test_test_total_includes_past_and_setup():
    c,s=scenario();c['financial']['test_spent_cny']='450';x=compute(c,s)
    assert x['test_total_cny']=='526.09' and not x['threshold_pass']
def test_ceiling_cent_boundary():
    c,s=scenario();x=compute(c,s);cap=D(x['purchase_ceiling_cny'])
    c['financial']['purchase_price_cny']=str(cap);a=compute(c,s);assert a['threshold_pass']
    c['financial']['purchase_price_cny']=str(cap+D('.01'));b=compute(c,s);assert not b['threshold_pass']
def test_warehouse_counts_distinct_sku():
    assert warehouse(1,D('.1'),[D(12),D(8),D(1)])[0]==D('2.5')
    assert warehouse(3,D('.1'),[D(12),D(8),D(1)])[0]==D('3.5')
    assert warehouse(3,D('.1'),[D(12),D(8),D(1)],'B')[0]==D('3')
def test_infra_waiver_needs_evidence():
    c,s=scenario();s['infra_exempt']=True
    assert next(x for x in compute(c,s)['lines'] if x['name']=='平台基础设施费')['php']=='5.00'
    s['infra_evidence']='隔离测试凭证';assert next(x for x in compute(c,s)['lines'] if x['name']=='平台基础设施费')['php']=='0.00'
@pytest.mark.parametrize('value',['NaN','Infinity','-1',True])
def test_invalid_money_rejected(value):
    c,s=scenario();c['financial']['purchase_price_cny']=value
    with pytest.raises(ValueError):compute(c,s)
