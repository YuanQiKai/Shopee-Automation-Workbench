import json,hashlib,re
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from .costs import compute,dec,D
from .db import ROOT,Record,put,read_all,now
from .sorftime import unpack_response
from .market_checks import summarize
GATES={'data':'市场币种与时间窗','demand':'同规格需求','competition':'竞争和价格','compliance':'合规/认证/禁限售','rights':'商标外观图片权利','sample':'样品质量','timing':'全链路交运时效','cost_evidence':'成本与税务凭证'}
def seed(s):
    if s.get(Record,('settings','shop')):return
    settings=json.loads((ROOT/'data/default-settings.json').read_text(encoding='utf-8'));put(s,'settings','shop',settings)
    for c in json.loads((ROOT/'data/seed-candidates.json').read_text(encoding='utf-8')):
        c={**c,'financial':{'channel':'standard'},'checks':{},'category_ids':[],'review':{'state':'pending'},'primary':None,'backup':None}
        put(s,'candidate',c['id'],c)
    snaps=json.loads((ROOT/'data/evidence/sorftime-2026-09-15.json').read_text(encoding='utf-8'))
    snaps.append(json.loads((ROOT/'data/evidence/backup-variants-2026-09-15.json').read_text(encoding='utf-8')))
    for i,snap in enumerate(snaps):
        snap['captured_at']=None;snap['captured_date']='2026-09-15';snap['id']='seed-'+str(i)
        ingest(s,snap)
def ingest(s,snapshot):
    sid=snapshot['id'];put(s,'evidence',sid,snapshot)
    tool=snapshot['tool'];pid=snapshot['arguments'].get('product_id')
    try:data=unpack_response(snapshot['result'])['data']
    except ValueError:return
    if tool not in ('ali1688_product_request','ali1688_product_variations') or not pid:return
    old=s.get(Record,('supplier',pid));sup=dict(old.data) if old else {'offer_id':pid,'detail':{},'skus':[],'evidence_ids':[]}
    if tool=='ali1688_product_request':
        if not isinstance(data,dict) and not (isinstance(data,list) and data and isinstance(data[0],dict)):return
        sup['detail']=data[0] if isinstance(data,list) else data;sup['detail_at']=snapshot.get('captured_at')
    else:
        if not isinstance(data,list):return
        sup['skus']=data;sup['skus_at']=snapshot.get('captured_at')
    sup['evidence_ids']=list(dict.fromkeys(sup.get('evidence_ids',[])+[sid]))
    sup['captured_at']=snapshot.get('captured_at');sup['captured_date']=snapshot.get('captured_date');sup['precision']='second' if sup['captured_at'] else 'date'
    put(s,'supplier',pid,sup)
def supplier_view(sup):
    d=sup.get('detail') or {};warnings=[]
    lead=d.get('shipping_time')
    if not lead or not re.search(r'\d+\s*(小时|天|hours?|days?|h)',str(lead),re.I):warnings.append('发货时效字段不能解析为时间：'+str(lead))
    if not sup.get('captured_at'):warnings.append('历史快照仅有采集日期，24小时新鲜度不可自动通过')
    for sku in sup.get('skus',[]):
        sku['issues']=[]
        if not all(sku.get(k) and dec(sku[k])>0 for k in ('length','width','height','weight')):sku['issues'].append('包装数据缺失/0值')
        if dec(sku.get('price'))!=dec(sku.get('offer_price')):sku['issues'].append('展示价与实际报价字段冲突')
        if sku.get('pkg_size_source')=='商家自填':sku['issues'].append('商家自填，待云仓实测')
    return {**sup,'warnings':warnings}
def current_hash(c,settings,suppliers):
    x={k:v for k,v in c.items() if k not in ('review','ai_summary')}
    ids={c.get(role,{}).get('offer_id') for role in ('primary','backup') if c.get(role)}
    normalized=[]
    for sup in suppliers:
        if sup.get('offer_id') not in ids:continue
        v={k:v for k,v in sup.items() if k!='warnings'}
        v['skus']=[{k:v for k,v in sku.items() if k!='issues'} for sku in sup.get('skus',[])]
        normalized.append(v)
    return hashlib.sha256(json.dumps({'candidate':x,'settings':settings,'suppliers':sorted(normalized,key=lambda s:s['offer_id'])},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def fresh(value,hours=24):
    try:
        t=datetime.fromisoformat(value.replace('Z','+00:00'));delta=(datetime.now(timezone.utc)-t).total_seconds()
        return 0<=delta<=hours*3600
    except (AttributeError,TypeError,ValueError):return False
def future(value):
    try:return datetime.fromisoformat(value.replace('Z','+00:00'))>datetime.now(timezone.utc)
    except (AttributeError,TypeError,ValueError):return False
def evaluate(c,settings,suppliers):
    base=compute(c,settings);stress=compute(c,settings,True);reasons=[]
    market=summarize(c.get('market_observations',[]),now(),c.get('spec'),c.get('planned_landed_php'),c.get('difference_evidence'))
    for key in ('data_gate','demand_gate','competition_gate'):
        if market.get(key)!='通过':reasons.append('市场定量检查：'+key+' '+str(market.get(key)))
    f=c.get('financial',{});buyer=dec(f.get('buyer_shipping_php'))
    if buyer is None or base['sale_php'] is None or dec(c.get('planned_landed_php'))!=D(base['sale_php'])+buyer:reasons.append('计划到手价应与活动售价+买家运费一致')
    weight=dec(f.get('weight_kg'))
    if weight is not None and weight>D('.5'):reasons.append('超出当前轻小件500g经营门槛')
    if not base['complete']:reasons.extend(base['missing'])
    if not base['threshold_pass']:reasons.append('活动成交利润/500元预算未达标或未齐')
    if not stress['complete'] or stress['profit_cny'] is None or D(stress['profit_cny'])<0:reasons.append('组合压力利润未通过')
    for key,label in GATES.items():
        g=c.get('checks',{}).get(key,{})
        if g.get('status')!='pass' or not g.get('evidence') or not future(g.get('valid_until')):reasons.append(label+'待核实或证据过期')
    selected=[]
    for role in ('primary','backup'):
        link=c.get(role)
        if not link:reasons.append(('主' if role=='primary' else '备用')+'货源未绑定具体SKU');continue
        sup=next((x for x in suppliers if x['offer_id']==link.get('offer_id')),None)
        sku=next((x for x in sup.get('skus',[]) if str(x['sku_id'])==link.get('sku_id')),None) if sup else None
        if not sku:reasons.append(role+' SKU不存在');continue
        selected.append(sup)
        if not fresh(sup.get('skus_at')):reasons.append(role+' 报价库存需24小时内重新查询')
        if not fresh(sup.get('detail_at')):reasons.append(role+' 商品级MOQ/代发详情需单独刷新')
        units=dec(c.get('financial',{}).get('purchase_units'))
        if units is None or dec(sku.get('stock')) is None or dec(sku.get('stock'))<10*units:reasons.append(role+' 库存不足10销售单元/未核实')
        conf=link.get('verification',{})
        if not conf.get('same_spec') or not conf.get('quote_evidence') or not conf.get('pack_measured') or not fresh(conf.get('confirmed_at')):reasons.append(role+' 同规格、最终报价、包装实测待确认')
        lead=dec(conf.get('lead_hours'))
        if lead is None or lead>48:reasons.append(role+' 48小时供货条件未通过')
        if dec(conf.get('moq'))!=D(1) or not conf.get('dropship'):reasons.append(role+' 单件代发/MOQ未通过')
        final_price=dec(conf.get('final_price_cny'))
        if final_price is None or final_price<=0:reasons.append(role+' 最终采购单价缺失')
        elif base['purchase_ceiling_cny'] is None or final_price>dec(base['purchase_ceiling_cny']):reasons.append(role+' 最终报价高于采购上限或上限未知')
        if role=='backup' and final_price is not None and final_price>0:
            alt={**c,'financial':{**f,'purchase_price_cny':str(final_price)}}
            a=compute(alt,settings);b=compute(alt,settings,True)
            if not a['threshold_pass'] or b['profit_cny'] is None or D(b['profit_cny'])<0:reasons.append('备用货源切换后利润/压力/500元门槛不通过')
        if role=='primary' and final_price!=dec(c.get('financial',{}).get('purchase_price_cny')):reasons.append('成本采购价与主货源确认价不一致')
    if len(selected)==2 and (selected[0]['offer_id']==selected[1]['offer_id'] or selected[0]['detail'].get('store_name')==selected[1]['detail'].get('store_name')):reasons.append('主备供应商须为不同商家并核验主体')
    if not settings.get('fee_evidence') or not future(settings.get('fee_valid_until')):reasons.append('本店费率凭证缺失/过期')
    if not settings.get('warehouse_evidence'):reasons.append('云仓方案与额外费用凭证缺失')
    today=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    if settings.get('cash_as_of')!=today:reasons.append('今日现金未更新')
    for k in ['available_cash_cny','commitments_cny','realized_loss_cny','unresolved_loss_cny']:
        if dec(settings.get(k)) is None:reasons.append(k)
    digest=current_hash(c,settings,suppliers)
    review=c.get('review',{});state=review.get('state','pending')
    if state=='approved' and (review.get('input_hash')!=digest or reasons):state='stale'
    return {'base':base,'stress':stress,'market':market,'reasons':list(dict.fromkeys(reasons)),'eligible':not reasons,'input_hash':digest,'review_state':state}
