"""Deterministic single-unit pricing. No external platform calls."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
from datetime import datetime, timezone

D = Decimal
ZERO = D('0')
CENT = D('0.01')


def num(value, name='金额', minimum=ZERO, maximum=D('10000000')):
    if value is None or value == '' or isinstance(value, bool):
        raise ValueError(f'{name}不能为空')
    try:
        result = D(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f'{name}必须是数字')
    if not result.is_finite() or result < minimum or result > maximum:
        raise ValueError(f'{name}超出允许范围')
    return result


def money(value):
    return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


def stamp():
    return datetime.now(timezone.utc).isoformat()


def fingerprint(product, settings, supplier):
    p = {k: v for k, v in product.items() if k not in ('approval', 'analysis')}
    return hashlib.sha256(json.dumps([p, settings, supplier], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


COST_FIELDS = {
    'purchase': '采购成本', 'domestic': '国内运费', 'warehouse': '云仓操作',
    'packaging': '包材', 'sls': 'SLS 卖家净物流', 'risk': '售后损失准备',
    'overhead': '固定费用分摊', 'tax': '税费暂估', 'withdrawal': '提现批次分摊',
}


def evaluate(product, rules, price=None):
    fx = num(rules.get('fx'), 'PHP → CNY 汇率', D('0.000001'), D('100'))
    p = num(product.get('price') if price is None else price, '成交价', D('0.01')).quantize(CENT, rounding=ROUND_HALF_UP)
    costs = product.get('costs', {})
    lines, total = [], ZERO
    for key, label in COST_FIELDS.items():
        amount = num(costs.get(key), label).quantize(CENT, rounding=ROUND_HALF_UP)
        total += amount
        lines.append({'key': key, 'name': label, 'currency': 'CNY', 'original': money(amount), 'cny': money(amount), 'basis': '单件分摊 / 手动录入'})
    payment = product.get('payment', 'normal')
    rate_key = 'installment' if payment == 'installment' else 'transaction'
    buyer_shipping = num(product.get('buyerShipping', '0'), '买家运费')
    fee_specs = [
        ('commission', '佣金', p, '商品成交价'),
        ('platformShipping', '平台运费（独立试算项）', p, '商品成交价 · 单件封顶'),
        (rate_key, '分期交易费' if payment == 'installment' else '普通交易费', p + buyer_shipping, '成交价 + 买家运费'),
        ('growth', '卖家增长费', p, '商品成交价'),
        ('marketing', '活动 / 推广比例准备', p, '商品成交价'),
        ('receiving', '收款费用', p, '原型简化为商品成交价'),
    ]
    for key, label, basis, explanation in fee_specs:
        rate = num(rules.get(key), label, ZERO, D('100'))
        fee = (basis * rate / D('100')).quantize(CENT, rounding=ROUND_HALF_UP)
        if key == 'platformShipping':
            fee = min(fee, num(rules.get('shippingCap'), '单件平台运费封顶'))
        converted = (fee * fx).quantize(CENT, rounding=ROUND_HALF_UP)
        total += converted
        lines.append({'key': key, 'name': label, 'currency': 'PHP', 'original': money(fee), 'cny': money(converted), 'basis': f'{explanation} × {rate}%'})
    fixed = ZERO if product.get('orderFeeExempt', False) else num(rules.get('orderFee'), '订单固定费')
    fixed_cny = (fixed * fx).quantize(CENT, rounding=ROUND_HALF_UP)
    total += fixed_cny
    lines.append({'key': 'orderFee', 'name': '订单固定费', 'currency': 'PHP', 'original': money(fixed), 'cny': money(fixed_cny), 'basis': '单件单订单 · 不重复按 SKU 收取'})
    revenue = (p * fx).quantize(CENT, rounding=ROUND_HALF_UP)
    profit = revenue - total
    margin = profit / revenue * D('100') if revenue else ZERO
    target_margin = num(rules.get('targetMargin'), '净利率目标', ZERO, D('95'))
    target_profit = num(rules.get('targetProfit'), '单件利润目标')
    meets = margin >= target_margin and profit >= target_profit and profit > 0
    return {'price': money(p), 'revenue': money(revenue), 'totalCost': money(total), 'profit': money(profit), 'margin': money(margin), 'meetsTarget': meets, 'lines': lines}


def solve_price(product, rules):
    """Find the first feasible integer PHP price, including rounding boundaries.

    The capped shipping fee defines two affine regions. Conservative rounding
    bounds eliminate impossible prices; exact enumeration verifies the rest.
    No assumption of monotonic rounded margin is made.
    """
    base = sum(num(product['costs'].get(k), label).quantize(CENT, rounding=ROUND_HALF_UP) for k, label in COST_FIELDS.items())
    fx = num(rules.get('fx'), '汇率', D('0.000001'), D('100'))
    margin = num(rules.get('targetMargin'), '目标净利率', ZERO, D('95')) / D('100')
    target = num(rules.get('targetProfit'), '目标利润')
    keys = ['commission', 'growth', 'marketing', 'receiving', 'installment' if product.get('payment') == 'installment' else 'transaction']
    rates = {k: num(rules.get(k), k, ZERO, D('100')) / D('100') for k in keys + ['platformShipping']}
    variable = sum(rates[k] for k in keys)
    shipping = rates['platformShipping']
    cap = num(rules.get('shippingCap'), '平台运费封顶')
    fixed = ZERO if product.get('orderFeeExempt') else num(rules.get('orderFee'), '固定费')
    base += (fixed * fx).quantize(CENT, rounding=ROUND_HALF_UP)
    base += num(product.get('buyerShipping', '0')) * rates[keys[-1]] * fx
    # Each of six fees is rounded in PHP and then CNY; revenue also rounds.
    epsilon = D('0.005') + D('6') * (D('0.005') * fx + D('0.005'))
    boundary = cap / shipping if shipping else D('100000')
    regions = [(D('1'), min(boundary, D('100000')), variable + shipping, base)]
    if shipping:
        regions.append((max(D('1'), boundary), D('100000'), variable, base + cap * fx))
    last = 0
    for low, high, rate, constant in regions:
        for coefficient, rhs in [(fx * (1 - rate), constant + target - epsilon), (fx * (1 - margin - rate), constant - epsilon)]:
            if coefficient > 0:
                low = max(low, rhs / coefficient)
            elif coefficient < 0:
                high = min(high, rhs / coefficient)
            elif rhs > 0:
                high = ZERO
        start = max(1, last + 1, int(low.to_integral_value(rounding=ROUND_CEILING)))
        stop = min(100000, int(high.to_integral_value(rounding=ROUND_FLOOR)))
        for candidate in range(start, stop + 1):
            last = candidate
            result = evaluate(product, rules, str(candidate))
            if result['meetsTarget']:
                return result
    return None


def analyze(product, settings, supplier):
    rules = settings['rules']
    missing = [label for key, label in COST_FIELDS.items() if product.get('costs', {}).get(key) in (None, '')]
    reasons = list(missing)
    result = None
    recommended = None
    if not missing:
        try:
            result = evaluate(product, rules)
            recommended = solve_price(product, rules)
        except ValueError as exc:
            reasons.append(str(exc))
    if result and not result['meetsTarget']:
        reasons.append('成交价未同时达到净利率和单件利润目标')
    if not supplier:
        reasons.append('未关联供应商')
    else:
        if not product.get('demo') and supplier.get('demo'):
            reasons.append('真实商品不能关联示例供应商')
        if not supplier.get('verified'):
            reasons.append('供应商待复核')
        if int(supplier.get('stock', 0)) <= 0:
            reasons.append('供应商无可供库存')
        if not supplier.get('dropship'):
            reasons.append('单件代发能力未确认')
        if int(supplier.get('leadDays', 0)) + int(settings.get('domesticDays', 2)) + int(settings.get('warehouseDays', 1)) + 1 > int(settings.get('shipDeadlineDays', 7)):
            reasons.append('采购到交运时限不足')
    if not product.get('supplierSku', '').strip():
        reasons.append('供应商 SKU 待录入')
    if not product.get('weight'):
        reasons.append('包装重量待核实')
    checks = product.get('checks', {})
    for key, label in {'supply': '货源与报价', 'logistics': '物流与尺寸', 'rights': '素材使用权', 'compliance': '禁限售与资质', 'facts': '商品事实'}.items():
        if not checks.get(key):
            reasons.append(label + '待核实')
    try:
        expiry = datetime.fromisoformat(product.get('quoteValidUntil', '').replace('Z', '+00:00'))
        if expiry.tzinfo is None or expiry < datetime.now(timezone.utc):
            reasons.append('报价已过期')
    except (ValueError, TypeError):
        reasons.append('报价有效期待录入')
    if not product.get('source', '').strip():
        reasons.append('缺少证据来源')
    if not product.get('demo') and not rules.get('verified'):
        reasons.append('店铺费率尚未核实')
    if recommended and product.get('marketMax') and num(recommended['price']) > num(product['marketMax']):
        reasons.append('目标售价超过录入的市场价格上限')
    score_values = product.get('scores', [0, 0, 0, 0, 0, 0])
    score = sum(int(v) for v in score_values)
    approval = product.get('approval')
    valid_approval = bool(approval and approval.get('fingerprint') == fingerprint(product, settings, supplier) and not reasons)
    content = product.get('content') or {}
    content_ready = bool(content.get('title', '').strip() and content.get('description', '').strip())
    state = 'approved' if valid_approval else 'stale' if approval else 'blocked' if reasons else 'review' if content_ready else 'ready'
    return {'calculation': result, 'recommended': recommended, 'blockers': list(dict.fromkeys(reasons)), 'score': score, 'state': state, 'contentReady': content_ready, 'approvalValid': valid_approval, 'canApprove': not reasons and content_ready, 'canPublish': False}


def generate_content(product):
    facts = product.get('facts', {})
    title = product.get('englishName', '').strip()
    if not title:
        raise ValueError('请先填写英文品名，再整理英文文案')
    details = []
    for field, label in [('material', 'Material'), ('size', 'Size'), ('pack', 'Package includes'), ('use', 'Suggested use')]:
        if facts.get(field):
            details.append(f'{label}: {facts[field]}')
    if not details:
        raise ValueError('请先填写至少一条已核实的英文商品事实')
    return {'title': title, 'bullets': details, 'description': title + '\n\n' + '\n'.join(details), 'imagePrompt': f'Create a clean product listing layout for {title}. Use the seller-authorized real product photograph without changing shape, color, count or details. White background, clear spacing. Only include verified text: ' + '; '.join(details), 'method': '事实模板整理（未调用 AI）', 'createdAt': stamp()}
