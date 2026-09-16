"""CNY/PHP decimal calculations. A preview is never an eligibility certificate."""
from decimal import Decimal,ROUND_HALF_UP,ROUND_CEILING,InvalidOperation
from pathlib import Path
import json
D=Decimal
CENT=D('.01')
ROOT=Path(__file__).resolve().parents[1]
RATES=json.loads((ROOT/'assets/philippines-rules.json').read_text(encoding='utf-8')) if (ROOT/'assets/philippines-rules.json').exists() else {}
EXTRAS={'domestic_cny':'国内运费','packaging_cny':'额外包装','purchase_tax_cny':'采购税票差额','customs_cny':'关税及清关附加','ads_cny':'广告预算分摊','affiliate_cny':'联盟营销','returns_cny':'退款/COD拒收损失准备','overhead_cny':'固定费分摊','tax_cny':'经营税费分摊','other_cny':'其他费用','seller_topup_php':'卖家额外运费补贴','platform_other_php':'其他平台扣款'}
def dec(x):
    if x is None or x=='':return None
    if isinstance(x,bool):raise ValueError('金额不能为布尔值')
    try:v=D(str(x))
    except InvalidOperation:raise ValueError('数值格式无效')
    if not v.is_finite() or v<0 or v>D('100000000'):raise ValueError('数值必须为有限非负值')
    return v
def money(x):return x.quantize(CENT,rounding=ROUND_HALF_UP)
def text(x):return str(money(x)) if x is not None else None
def platform_shipping(sale_php,mall=False,items=1):
    return min(D(100), (sale_php*D('.0448' if mall else '.056')).quantize(D(1),rounding=ROUND_HALF_UP))*items
def logistics(weight_kg,length_cm,width_cm,height_cm,channel,category_ids=None):
    problems=[]
    weight=dec(weight_kg); dims=[dec(x) for x in [length_cm,width_cm,height_cm]]
    if weight is None or weight==0:problems.append('缺包装实重')
    if any(x is None or x==0 for x in dims):problems.append('缺完整包装尺寸；0不是实际尺寸')
    sea=channel=='sea'
    if channel not in ('sea','standard'):raise ValueError('只支持已开通的标准/海运渠道')
    if weight and weight>D(50 if sea else 20):problems.append('超渠道限重')
    if all(dims):
        if (sea and (max(dims)>=150 or sum(dims)>=300)) or (not sea and max(dims)>150):problems.append('超渠道尺寸限制')
    matches=[x for x in RATES.get('sea_ban',[]) if x['category_id'] in [str(v) for v in (category_ids or [])]] if sea else []
    if matches:problems.append('命中海运禁运清单/祖先类目，须核实层级；不批准海运')
    if sea and not category_ids:problems.append('缺类目ID及祖先路径，海运禁运未核查')
    value=None;row=None
    if weight and weight<=D(50 if sea else 20):
        grams=int((weight*1000/D(10)).to_integral_value(rounding=ROUND_CEILING))*10
        row=next((r for r in RATES.get('sls_rates',[]) if r['grams']==grams),None)
        if row:value=dec(row.get(channel))
        if value is None:problems.append('运费表缺少有效重量档')
    return {'channel':channel,'seller_sls_php':text(value),'chargeable_g':int((weight*100).to_integral_value(rounding=ROUND_CEILING))*10 if weight else None,'source_cell':('菲律宾!'+('E' if sea else 'C')+str(row['row'])) if row else None,'problems':problems,'sea_matches':matches,'reference_days':[28,35] if sea else [5,15],'buyer_tail_php':{'A':20,'B':20,'C':45,'D':45} if sea else {'A':40,'B':60,'C':60,'D':60}}
def warehouse(distinct_skus,weight,dims,plan='A'):
    n=dec(distinct_skus)
    if n is None or n<1 or n!=int(n):return None,['缺仓库不同SKU数量']
    base=D('2.5')+max(0,n-1)*D('.5') if plan=='A' else D(3)+max(0,n-3)*D('.5')
    problems=[]
    if any(x is None or x==0 for x in dims) or not weight:problems.append('包装数据未齐，仓库附加费未核实')
    elif sum(dims)>=110 or weight>D(3):problems.append('仓库大包/超重计费存在文档歧义，需逐单报价')
    return base,problems
def compute(c,settings,stress=False):
    f=c.get('financial',{}); missing=[];lines=[]
    def val(key,container=f):
        v=dec(container.get(key))
        if v is None:missing.append(key)
        return v
    price=val('list_price_php'); factor=dec(settings.get('activity_factor'));fx=val('fx_cny_per_php',settings)
    if factor is None: missing.append('activity_factor'); factor=D('.4')
    if not settings.get('activity_confirmed'):missing.append('4折口径待确认')
    if factor<=0 or factor>1:raise ValueError('成交比例应大于0且不超过1')
    if fx is not None and fx<=0:raise ValueError('汇率必须大于0')
    sale=money(price*factor) if price is not None else None
    if fx is not None and stress:fx*=D('.95')
    qty=val('purchase_units');quote=val('purchase_price_cny');subsidy=val('cash_subsidy_php')
    if qty is not None and (qty<1 or qty!=int(qty)):raise ValueError('采购件数必须为正整数')
    if quote is not None and quote<=0:missing.append('采购报价必须大于0')
    procurement=money(qty*quote*(D('1.10') if stress else 1)) if qty is not None and quote is not None else None
    log=logistics(f.get('weight_kg'),f.get('length_cm'),f.get('width_cm'),f.get('height_cm'),f.get('channel','standard'),c.get('category_ids'))
    missing+=log['problems']
    wh,wh_problems=warehouse(f.get('warehouse_skus'),dec(f.get('weight_kg')),[dec(f.get(k)) for k in ('length_cm','width_cm','height_cm')],settings.get('warehouse_plan','A'))
    missing+=wh_problems
    for k in ['commission_pct','transaction_pct','program_pct']:
        value=val(k,settings)
        if value is not None and value>100:raise ValueError('费率不能超过100%')
    commission=money(sale*dec(settings['commission_pct'])/100) if sale is not None and dec(settings.get('commission_pct')) is not None else None
    transaction_base=sale
    if settings.get('transaction_base')=='sale_plus_buyer_shipping':
        buyer=val('buyer_shipping_php');transaction_base=(sale+buyer) if sale is not None and buyer is not None else None
    elif settings.get('transaction_base')!='sale':missing.append('transaction_base');transaction_base=None
    tx_rate=val('transaction_stress_pct',settings) if stress else dec(settings.get('transaction_pct'))
    if tx_rate is not None and tx_rate>100:raise ValueError('压力交易费率不能超过100%')
    if stress and tx_rate is not None and dec(settings.get('transaction_pct')) is not None and tx_rate<dec(settings['transaction_pct']):raise ValueError('压力交易费率不得低于基准费率')
    tx=money(transaction_base*tx_rate/100) if transaction_base is not None and tx_rate is not None else None
    program=money(sale*dec(settings['program_pct'])/100) if sale is not None and dec(settings.get('program_pct')) is not None else None
    ship=platform_shipping(sale,settings.get('mall',False)) if sale is not None else None
    infra=D(0) if settings.get('infra_exempt') is True and settings.get('infra_evidence') else D(5)
    sls=dec(log['seller_sls_php'])
    if sls is not None and stress:sls=money(sls*D('1.15'))
    php_costs={'平台佣金':commission,'交易/支付费':tx,'活动项目费':program,'平台运费':ship,'平台基础设施费':infra,'SLS卖家藏价运费':sls}
    extras={k:val(k) for k in EXTRAS}
    if stress:
        for k in ['domestic_cny','packaging_cny']:
            if extras[k] is not None:extras[k]=money(extras[k]*D('1.15'))
        if wh is not None:wh=money(wh*D('1.15'))
    php_costs['卖家额外运费补贴']=extras.pop('seller_topup_php')
    php_costs['其他平台扣款']=extras.pop('platform_other_php')
    revenue=money((sale+subsidy)*fx) if sale is not None and fx is not None and subsidy is not None else None
    settlement=(sale+subsidy-sum(php_costs.values())) if sale is not None and subsidy is not None and all(v is not None for v in php_costs.values()) else None
    withdrawal=money(max(D(0),settlement)*fx*D('.002')) if settlement is not None and fx is not None else None
    if settlement is not None and settlement<0:missing.append('预计平台结算为负')
    costs={'采购成本':procurement,'云仓基础服务':wh,'提现费(预计结算额×0.2%)':withdrawal,**{EXTRAS[k]:v for k,v in extras.items()}}
    costs.update({k:money(v*fx) if v is not None and fx is not None else None for k,v in php_costs.items()})
    for k,v in costs.items():lines.append({'name':k,'cny':text(v),'php':text(php_costs.get(k))})
    total=money(sum(costs.values())) if all(v is not None for v in costs.values()) else None
    logistic_names=['国内运费','额外包装','云仓基础服务','SLS卖家藏价运费','卖家额外运费补贴']
    logistics_total=sum(costs[k] for k in logistic_names) if all(costs.get(k) is not None for k in logistic_names) else None
    logistics_ratio=logistics_total/revenue*100 if revenue and logistics_total is not None else None
    if logistics_ratio is not None and logistics_ratio>D(25):missing.append('履约物流成本超过收入25%经营门槛')
    profit=money(revenue-total) if revenue is not None and total is not None else None
    margin=money(profit/revenue*100) if profit is not None and revenue else None
    ceiling=money(max(D(0),(revenue-max(D(15),revenue*D('.20'))-(total-procurement))/qty)) if profit is not None and procurement is not None and qty else None
    # Downward cent rounding for a maximum payable quote.
    if ceiling is not None:
        while ceiling>0 and revenue-money(total-procurement+money(ceiling*qty))<max(D(15),revenue*D('.20')):ceiling-=CENT
    orders=val('test_orders');setup=val('test_setup_cny');already=val('test_spent_cny')
    if orders is not None and (orders<1 or orders!=int(orders)):raise ValueError('测试订单数必须为正整数')
    test=money(already+setup+total*orders) if all(v is not None for v in [already,setup,total,orders]) else None
    return {'revenue_cny':text(revenue),'sale_php':text(sale),'full_cost_cny':text(total),'profit_cny':text(profit),'margin_pct':text(margin),'purchase_ceiling_cny':text(ceiling),'test_total_cny':text(test),'cash_needed_cny':text(test-already) if test is not None else None,'lines':lines,'missing':sorted(set(missing)),'logistics':log,'complete':not missing and total is not None,'scenario':'组合压力' if stress else '活动成交','threshold_pass':profit is not None and profit>=15 and margin>=20 and test is not None and test<=500}
