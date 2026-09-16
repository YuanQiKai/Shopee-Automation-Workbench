"""Versioned, conservative admission rules. Provisional thresholds, not a forecast."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal as D
import json
from pathlib import Path
from engine import num, money, evaluate

POLICY = json.loads(Path(__file__).with_name('selection_policy.json').read_text(encoding='utf-8'))
EXCLUSIONS = {
    'noPowered': '不带电', 'noChemicals': '非化学相关品', 'noDangerous': '非危险品',
    'noRestricted': '非平台违规或禁限售', 'noComplexCertification': '非强资质认证品',
    'noInfringement': '无侵权风险并有素材权利', 'noBooks': '非书籍',
    'noVirtual': '非虚拟商品', 'noCollectibles': '非收藏品',
}
FIELDS = {
    'competition': [('difference','已核实的差异点（具体规格/场景/组合）','text'), ('differenceVerified','差异点有证据','tri')],
    'profit': [('advertisingCovered','推广支出已包含在现有费用中（注明具体费项，禁止漏算/重复）','tri')],
    'logistics': [('billableWeightG','承运方核实计费重量 g（含体积重）','number'), ('leadHours','供应商备货上限 小时','number'), ('domesticHours','国内运输上限 小时','number'), ('warehouseHours','云仓及交接上限 小时','number'), ('deadlineHours','平台允许交运时间 小时（统一起算点）','number')],
    'supply': [('samplePassed','已完成样品或有记录实物验货','tri'), ('noSubstitution','确认不会擅自换规格','tri'), ('afterSales','退换责任及采购凭证条件已确认','tri'), ('backupVerified','有已核实同规格备用货源（加分）','tri')],
    'compliance': [(k,v,'tri') for k,v in EXCLUSIONS.items()],
    'expansion': [('repeatOpportunity','有依据的耗材/配件复购机会','tri'), ('relatedCount','同客群可扩展不同SPU数（不含颜色尺码）','integer'), ('bundleVerified','已核实有利润的套装机会','tri')],
    'cash': [('dailyUnits','本产品计划新增日订单量（按全店剩余资金）','integer'), ('monthlyLossCNY','当月经营亏损 CNY（无亏损填0并留证）','number')],
}


def empty_evidence():
    return {key: {**{f: 'unknown' if typ == 'tri' else '' for f, _, typ in fields},
                  'source': '', 'observedAt': '', 'validUntil': ''} for key, fields in FIELDS.items()}


def n(value):
    try:
        return num(value, maximum=D('1000000000000'))
    except ValueError:
        return None


def dt(value):
    try:
        x = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return x.astimezone(timezone.utc) if x.tzinfo else None
    except (ValueError, AttributeError, TypeError):
        return None


def recent(proof, now, hours):
    if not isinstance(proof, dict):
        return False
    observed, until = dt(proof.get('observedAt')), dt(proof.get('validUntil'))
    return (isinstance(proof.get('source'), str) and bool(proof['source'].strip())
            and observed is not None and until is not None
            and now - timedelta(hours=hours) <= observed <= now < until)


def validate_evidence(value):
    if not isinstance(value, dict) or set(value) - set(FIELDS):
        raise ValueError('七维证据格式或维度错误')
    for group, data in value.items():
        if not isinstance(data, dict):
            raise ValueError('维度证据必须是对象')
        allowed = {f for f, _, _ in FIELDS[group]} | {'source', 'observedAt', 'validUntil'}
        if set(data) - allowed:
            raise ValueError('维度包含未知字段')
        for f in ('source', 'observedAt', 'validUntil'):
            if not isinstance(data.get(f, ''), str) or len(data.get(f, '')) > 10000:
                raise ValueError('证据来源/时间格式错误')
        for f, label, typ in FIELDS[group]:
            v = data.get(f, '')
            if v in ('', None):
                continue
            if typ == 'tri' and v not in ('yes', 'no', 'unknown'):
                raise ValueError(label + '只能选通过、不通过或未知')
            if typ in ('number', 'integer'):
                z = num(v)
                if typ == 'integer' and z != z.to_integral():
                    raise ValueError(label + '必须为整数')
            if typ == 'text' and (not isinstance(v, str) or len(v) > 10000):
                raise ValueError(label + '文本格式错误')


def assess_selection(case, settings, observations, base, now=None):
    now = now or datetime.now(timezone.utc)
    t, evidence = POLICY['thresholds'], case.get('selectionEvidence') or {}
    needs, failures, dimensions, metrics = [], [], [], {}
    def need(group, code, message):
        needs.append({'code': 'SELECT_' + code, 'message': message, 'section': group, 'owner': '店主/资料提供方'})
    def fail(group, message):
        failures.append(group + '：' + message)
    def proof(group, hours=168, required=True):
        p = evidence.get(group, {})
        good = recent(p, now, hours)
        if required and not good:
            need(group, group.upper() + '_PROOF', '补充有效来源、实际复核时间和有效期，不能用过期证据延长有效期')
        return p, good
    def dimension(key, points, start):
        nn, ff = start
        status = 'fail' if len(failures) > ff else 'unknown' if len(needs) > nn else 'pass'
        spec = next(x for x in POLICY['dimensions'] if x['id'] == key)
        dimensions.append({**spec, 'status': status, 'score': points if status == 'pass' else None,
                           'reasons': failures[ff:] + [x['message'] for x in needs[nn:]]})
    def mark(): return len(needs), len(failures)
    # All evidence is operator-reviewed; raw provider monthly totals never auto-fill it.
    begin = mark()
    by_id = {r['id']: r for r in observations}
    rows, seen, windows = [], set(), set()
    for item in case.get('comparisons', []):
        obs = by_id.get(item.get('observationId'), {})
        identity = obs.get('identity')
        if (not identity or identity in seen or obs.get('platform') != 'shopee'
                or obs.get('site') != 'PH'):
            continue
        seen.add(identity)
        sales, price = n(item.get('sales30d')), n(item.get('arrivalPricePHP'))
        try:
            end = date.fromisoformat(item.get('salesWindowEnd', ''))
            start = date.fromisoformat(item.get('salesWindowStart', ''))
            window_ok = (end-start).days == 29 and 0 <= (now.date()-end).days <= t['salesAgeDaysMax']
        except (ValueError, TypeError):
            window_ok = False
        if (item.get('sameSpec') != 'yes' or not item.get('specEvidence', '').strip()
                or not recent(item, now, t['marketProofAgeDaysMax']*24)
                or sales is None or sales != sales.to_integral() or price is None or price <= 0
                or not window_ok or item.get('salesScope') != 'same_spec_30d'
                or not str(obs.get('shopId', '')).isdigit()):
            continue
        windows.add((start, end))
        rows.append({'shop': obs['shopId'], 'sales': sales, 'price': price, 'group': obs.get('group')})
    shops = {}
    for row in rows:
        shops[row['shop']] = shops.get(row['shop'], D(0)) + row['sales']
    total = sum(shops.values(), D(0))
    metrics.update(validMarketSamples=len(rows), distinctShops=len(shops), sampleSales30d=str(total))
    if len(rows) < t['sampleMin'] or len(shops) < t['shopsMin'] or len(windows) != 1:
        need('市场需求', 'SAMPLES', '需要同一明确30天窗口、近14天内结束的10个同规格商品和5家店；逐条复核销量口径、币种、来源与近7天复核日期')
    else:
        if total < t['sampleSalesMin']: fail('市场需求', '样本30天销量合计不足300件')
        if sum(v >= t['salesPerShopMin'] for v in shops.values()) < t['sellingShopsMin']:
            fail('市场需求', '少于3家独立店铺各达到30件/30天')
    dimension('demand', 20 if total >= 1000 else 16, begin)

    begin = mark()
    p, ok = proof('competition')
    cbshops = {}
    for r in rows:
        if r['group'] == 'cross_border': cbshops[r['shop']] = cbshops.get(r['shop'], D(0)) + r['sales']
    if len(rows) < t['sampleMin'] or len(windows) != 1 or len(shops) < t['shopsMin']:
        need('竞争空间','COMPETITION_SAMPLE','需求样本不完整，集中度与跨境价格优势暂不可判定')
    else:
        share = sum(sorted(shops.values(), reverse=True)[:3], D(0))*100/total if total else D(100)
        metrics['sampleTop3ShopSharePct'] = money(share)
        if share > t['top3ShareMaxPct']: fail('竞争空间', '样本前三店销量占比超过70%，暂缓同款竞争')
        if sum(v >= t['salesPerShopMin'] for v in cbshops.values()) < t['crossBorderShopsMin']:
            fail('竞争空间', '少于2家跨境店各达到30件/30天，缺少同履约模式验证')
        prices = sorted(r['price'] for r in rows if r['group'] == 'cross_border')
        ours, shipping = n(case.get('pricePHP')), n(case.get('buyerShippingPHP'))
        if prices and ours is not None and shipping is not None:
            median = (prices[(len(prices)-1)//2]+prices[len(prices)//2])/2
            metrics['crossBorderMedianPHP'] = money(median)
            if ours+shipping > median*(1+D(t['pricePremiumMaxPct'])/100):
                fail('竞争空间', '计划买家到手价超过跨境同规格中位数110%')
        else: need('竞争空间','ARRIVAL_PRICE','核实跨境同规格到手价与本品买家运费')
    if ok:
        if p.get('differenceVerified') == 'no': fail('竞争空间','没有可验证差异点')
        elif p.get('differenceVerified') != 'yes' or not str(p.get('difference','')).strip():
            need('竞争空间','DIFFERENCE','提供至少1个真实差异点及证据，不能只写高质量')
    dimension('competition',15 if n(metrics.get('sampleTop3ShopSharePct')) is not None and D(metrics['sampleTop3ShopSharePct']) <= 50 else 12,begin)

    begin = mark()
    p, ok = proof('profit')
    calc = base.get('calculation')
    stress = None
    if not calc: need('利润','COSTS','先补全原有成本、报价和费用证据')
    else:
        net, revenue = D(calc['profit']), D(calc['revenue'])
        margin = net*100/revenue if revenue > 0 else D(-1)
        if net < max(D(t['profitMinCNY']), D(settings['rules']['targetProfit'])) or margin < max(D(t['marginMinPct']),D(settings['rules']['targetMargin'])):
            fail('利润','基准未达到每单15元及20%净利率，或本店更高目标')
        costs = {k:D(v['amount']) for k,v in case['costs'].items()}
        costs['purchase'] = D(case['quote']['unitPrice'])*D(case['quote']['unitsPerSale'])*D('1.10')
        for k in ('domestic','warehouse','packaging','sls'): costs[k] *= D('1.15')
        rules = deepcopy(settings['rules']); rules['fx'] = str(D(rules['fx'])*D('.95'))
        try:
            stress = evaluate({'price':case['pricePHP'],'costs':{k:money(v) for k,v in costs.items()},'buyerShipping':case['buyerShippingPHP'],'payment':'installment','orderFeeExempt':case['orderFeeExempt']},rules)
            if D(stress['profit']) < t['stressProfitMinCNY']: fail('利润','采购/全部物流/汇率/分期组合压力后亏损')
        except ValueError: need('利润','STRESS','组合压力计算范围无效')
    if ok and p.get('advertisingCovered') != 'yes':
        if p.get('advertisingCovered') == 'no': fail('利润','推广支出尚未纳入完全成本')
        else: need('利润','ADS','确认广告/推广支出所归属的具体费项，不得漏计或重复')
    dimension('profit',25 if calc and D(calc['revenue']) > 0 and D(calc['profit']) >= 20 and D(calc['profit'])*100/D(calc['revenue']) >= 25 else 21,begin)

    begin = mark()
    p, ok = proof('logistics')
    nums = {k:n(p.get(k)) for k in ('billableWeightG','leadHours','domesticHours','warehouseHours','deadlineHours')}
    if ok:
        if any(v is None for v in nums.values()) or not nums['billableWeightG'] or not nums['deadlineHours']:
            need('物流','TIMES','补齐承运计费重量、各段时效与同一起算点的交运期限')
        else:
            if nums['billableWeightG'] > t['billableWeightMaxG']: fail('物流','计费重量超过500g初期范围')
            physical = n(case['package'].get('weightG'))
            if physical is None or nums['billableWeightG'] < physical: fail('物流','计费重量不可小于包装实重')
            slack = nums['deadlineHours']-sum(nums[k] for k in ('leadHours','domesticHours','warehouseHours'))
            metrics['dispatchSlackHours'] = str(slack)
            if slack < t['dispatchBufferHours']: fail('物流','交运剩余安全时间不足24小时')
            for key, minimum in [('leadHours', n(case['quote'].get('leadDays'))), ('domesticHours', n(settings.get('domesticDays'))), ('warehouseHours', n(settings.get('warehouseDays')))]:
                if minimum is not None and nums[key] < minimum*24:
                    fail('物流','小时上限与既有备货/国内/云仓天数冲突，请统一依据后更新配置')
            deadline_days = n(settings.get('shipDeadlineDays'))
            if deadline_days is not None and nums['deadlineHours'] > deadline_days*24:
                fail('物流','小时交运期限宽于既有平台天数，请统一依据，不能延长承诺')
    if calc and D(calc['revenue']) > 0:
        logistical = sum(D(case['costs'][k]['amount']) for k in ('domestic','warehouse','packaging','sls'))
        share = logistical*100/D(calc['revenue'])
        metrics['logisticsSharePct'] = money(share)
        if share > t['logisticsShareMaxPct']: fail('物流','全部物流与包材成本超过净收入25%')
    else: need('物流','LOGISTICS_COST','物流成本比例待费用齐全后计算')
    dimension('logistics',10 if nums.get('billableWeightG') is not None and nums['billableWeightG'] <= 300 else 8,begin)

    begin = mark()
    p, ok = proof('supply',t['quoteAgeHoursMax'])
    q = case['quote']; per_sale=n(q.get('unitsPerSale')); moq=n(q.get('moq')); quantity=n(q.get('purchaseQuantity')); stock=n(q.get('stock'))
    if not recent(q,now,t['quoteAgeHoursMax']): need('供应','QUOTE_AGE','报价和库存须24小时内实际复核，并记录复核时间')
    if per_sale is not None and moq is not None and quantity is not None:
        if moq > per_sale or quantity != per_sale: fail('供应','无库存模式要求一次采购恰好满足一个销售单元，MOQ/批量不得迫使囤货')
    if per_sale and stock is not None and stock/per_sale < t['stockSalesMin']: fail('供应','已核实库存不足10个销售单元')
    if nums.get('leadHours') is not None and nums['leadHours'] > t['leadHoursMax']: fail('供应','备货上限超过48小时')
    if ok:
        for key in ('samplePassed','noSubstitution','afterSales'):
            if p.get(key) == 'no': fail('供应',dict((x,y) for x,y,_ in FIELDS['supply'])[key]+'未通过')
            elif p.get(key) != 'yes': need('供应',key.upper(),'样品/验货、不换规格、退换责任与凭证条件须全部确认')
    dimension('supply',15 if ok and p.get('backupVerified')=='yes' else 12,begin)

    begin = mark()
    p, ok = proof('compliance')
    if ok:
        for key,label in EXCLUSIONS.items():
            if p.get(key)=='no': fail('合规',label+'不通过，违反店主禁做清单')
            elif p.get(key)!='yes': need('合规',key.upper(),label+'待确认')
    dimension('compliance',10,begin)
    p, ok = proof('expansion',required=False)
    expansion = (2*int(p.get('repeatOpportunity')=='yes')+2*int((n(p.get('relatedCount')) or 0)>=3)+int(p.get('bundleVerified')=='yes')) if ok else 0
    dimension('expansion',expansion,mark())
    dimensions[-1]['status']='pass' if ok else 'unscored'
    if not ok: dimensions[-1]['reasons']=['可选加分项：无有效证据记0分，不阻断耐用品上架测试']

    p, ok = proof('cash',24)
    projected = None
    if ok:
        daily, loss = n(p.get('dailyUnits')), n(p.get('monthlyLossCNY'))
        if daily is None or daily <= 0 or daily != daily.to_integral() or loss is None:
            need('资金','CASH_INPUT','填写计划新增日订单整数及当月亏损，不能以空白当0')
        else:
            if loss >= t['monthlyLossMaxCNY']: fail('资金','已达到当月4000元试错亏损上限')
            available = max(D(0),D(settings['bankBalance'])-D(settings['committed'])-D(settings['reserve']))
            if D(settings['reserve']) < t['reserveMinCNY']: fail('资金','应急保护资金低于5000元')
            if calc:
                projected = daily*D(t['cashCycleDays'])*D(calc['totalCost'])
                metrics['cash28DaysCNY'] = money(projected)
                metrics['cashUsable80PctCNY'] = money(available*D(t['cashUtilizationMaxPct'])/100)
                if projected > available*D(t['cashUtilizationMaxPct'])/100: fail('资金','28天新增订单保守占资超过可用现金80%')
            else: need('资金','CASH_COST','成本齐全后计算28天占资')
    total_score = sum(d['score'] or 0 for d in dimensions)
    mandatory_known = all(d['status'] not in ('unknown','fail') for d in dimensions if d['id']!='expansion')
    if not needs and not failures and total_score < t['scoreMin']: fail('排序','总分不足75分，暂不进入上架测试审核')
    return {'version':POLICY['version'],'dimensions':dimensions,'metrics':metrics,'needs':needs,'failures':failures,
            'score':total_score if mandatory_known else None,'observedScore':total_score,
            'eligible':not needs and not failures and total_score>=t['scoreMin'],
            'stress':stress,'meaning':'七维全部必选门槛、资金门槛及原有核验同时通过才可人工审核上架测试；不代表已验证盈利。'}
