"""Validate explicit PH SKU windows, then summarize this sample only."""
from datetime import date,timedelta
from decimal import Decimal
from collections import defaultdict
from statistics import median
from .selection_math import stamp,nonnegative

def quantile(values,p):
    x=sorted(Decimal(str(v)) for v in values)
    if not x:return None
    i=(len(x)-1)*Decimal(str(p));lo=int(i);hi=min(lo+1,len(x)-1)
    return x[lo]+(x[hi]-x[lo])*(i-lo)

def summarize(rows,as_of,spec,planned_landed_php,difference_evidence=None):
    now=stamp(as_of);seen=set();valid=[];issues=[]
    for i,r in enumerate(rows):
        bad=[]
        for k in ['product_id','shop_id','source']:
            if not r.get(k):bad.append('缺'+k)
        if r.get('site')!='PH' or r.get('currency')!='PHP':bad.append('PH/PHP未确认')
        if r.get('spec')!=spec or r.get('sku_sales_verified') is not True:bad.append('同规格SKU销量未确认')
        for k in ['sales_30d','buyer_landed_php']:
            if not nonnegative(r.get(k)):bad.append(k+'异常')
        if nonnegative(r.get('buyer_landed_php')) and Decimal(str(r['buyer_landed_php']))<=0:bad.append('到手价须正数')
        if r.get('sales_kind') not in ['平台窗口显示','自有订单汇总','服务商估算']:bad.append('销量是实测还是估算未说明')
        if r.get('shop_type') not in ['本土','跨境']:bad.append('店铺地域未知')
        try:
            start=date.fromisoformat(r['window_start']);end=date.fromisoformat(r['window_end'])
            if (end-start).days!=29 or not 0<=(now.date()-end).days<=14:bad.append('30天窗口无效或过期')
            at=stamp(r['observed_at'])
            if not 0<=(now-at).total_seconds()<=7*86400:bad.append('观测过期或在未来')
        except Exception:bad.append('期间/时区字段无效')
        key=(r.get('product_id'),r.get('spec'),r.get('window_start'),r.get('window_end'))
        if key in seen:bad.append('重复商品规格窗口')
        if bad:issues.append({'row':i,'source':r.get('source'),'issues':bad})
        else:seen.add(key);valid.append(r)
    # Only one identical window is admissible for cross-product aggregation.
    windows={(r['window_start'],r['window_end']) for r in valid}
    if len(windows)>1:return {'data_gate':'待补证','demand_gate':'待补证','competition_gate':'待补证','issues':issues+[{'issues':['混合窗口禁止汇总']}],'valid_n':0}
    shops=defaultdict(Decimal);cb=defaultdict(Decimal)
    for r in valid:
        shops[r['shop_id']]+=Decimal(str(r['sales_30d']))
        if r['shop_type']=='跨境':cb[r['shop_id']]+=Decimal(str(r['sales_30d']))
    total=sum(shops.values(),Decimal(0));cr3=sum(sorted(shops.values(),reverse=True)[:3])/total if total>0 else None
    cb_prices=[r['buyer_landed_php'] for r in valid if r['shop_type']=='跨境']
    cb_median=quantile(cb_prices,.5)
    demand=len(valid)>=10 and len(shops)>=5 and total>=300 and sum(v>=30 for v in shops.values())>=3
    competitive=cr3 is not None and cr3<=Decimal('.7') and sum(v>=30 for v in cb.values())>=2
    if not nonnegative(planned_landed_php) or cb_median is None or not difference_evidence:
        comp_state='待补证'
    else:comp_state='通过' if competitive and Decimal(str(planned_landed_php))<=cb_median*Decimal('1.1') else '不通过'
    return {'data_gate':'通过' if len(valid)>=10 else '待补证',
      'demand_gate':('通过' if demand else '不通过') if len(valid)>=10 else '待补证',
      'competition_gate':comp_state if len(valid)>=10 else '待补证',
      'valid_n':len(valid),'excluded_n':len(rows)-len(valid),'shops':len(shops),'sample_sales_30d':total,'estimate_rows':sum(r['sales_kind']=='服务商估算' for r in valid),
      'selling_shops_30':sum(v>=30 for v in shops.values()),'crossborder_shops_30':sum(v>=30 for v in cb.values()),
      'sample_cr3':cr3,'landed_p25':quantile([r['buyer_landed_php'] for r in valid],.25),
      'landed_p50':quantile([r['buyer_landed_php'] for r in valid],.5),
      'landed_p75':quantile([r['buyer_landed_php'] for r in valid],.75),'crossborder_p50':cb_median,
      'issues':issues,'scope':'样本描述；不能外推全站销量或垄断；服务商估算须原样标记'}

if __name__=='__main__':
    now='2026-09-15T12:00:00+08:00'
    rows=[dict(product_id=str(i),shop_id=str(i//2),source='隔离测试',site='PH',currency='PHP',
      spec='test',sku_sales_verified=True,sales_kind='服务商估算',sales_30d=100,buyer_landed_php=200,shop_type='跨境' if i<4 else '本土',
      window_start='2026-08-16',window_end='2026-09-14',observed_at=now) for i in range(10)]
    r=summarize(rows,now,'test',210,'隔离测试')
    assert r['sample_cr3']==Decimal('.6') and r['sample_sales_30d']==1000 and r['demand_gate']=='通过' and r['competition_gate']=='通过'
    rows[0]['currency']='THB';r=summarize(rows,now,'test',210,'隔离测试');assert r['valid_n']==9 and r['data_gate']=='待补证'
    print('通过：10样本5店、CR3、跨境店与到手价、币种错误剔除；仅隔离测试')
