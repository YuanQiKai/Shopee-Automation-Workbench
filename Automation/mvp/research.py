"""Evidence-first market research. Raw snapshots are immutable and fail closed."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal as D, ROUND_FLOOR
import hashlib
import json
import re
import unicodedata
import uuid

from engine import COST_FIELDS, evaluate, solve_price, num, money, stamp
from sorftime import unpack_response, validate_query
import selection

VERSION = '0.4.0'
CONTRACT = 'sorftime-observed-2026-09-09-v2'
DEFAULT_POLICY = {'id': 'main', 'revision': 1, 'maxSellingPricePHP': '1000',
                  'category': '家居用品', 'excluded': ['强资质认证', '带电', '化学相关', '危险品', '平台违规', '侵权', '书籍', '虚拟商品', '收藏品'],
                  'source': '店主于 2026-09-09 明确确认；成交价上限可修改'}


def get_policy(db):
    try:
        return read(db, 'research_policy', 'main')
    except ValueError:
        return deepcopy(DEFAULT_POLICY)


def update_policy(db, body):
    policy = get_policy(db)
    if body.get('revision') != policy['revision']:
        raise ValueError('筛选设置已变更，请刷新后重试')
    policy['maxSellingPricePHP'] = str(num(body.get('maxSellingPricePHP'), '成交价上限', D('.01'), D('100000')))
    policy.update(revision=policy['revision'] + 1, updatedAt=stamp(), source='店主在本机手动修改')
    save(db, 'research_policy', policy)
    log(db, '更新选品范围', '成交价上限', policy['maxSellingPricePHP'] + ' PHP；已有候选重新判断')
    return policy


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def read(db, kind, id):
    row = db.execute('SELECT payload FROM records WHERE kind=? AND id=?', (kind, id)).fetchone()
    if not row:
        raise ValueError('研究记录不存在')
    return json.loads(row[0])


def records(db, kind):
    return [json.loads(r[0]) for r in db.execute('SELECT payload FROM records WHERE kind=? ORDER BY rowid DESC', (kind,))]


def save(db, kind, value, immutable=False):
    raw = json.dumps(value, ensure_ascii=False, default=str)
    if immutable:
        db.execute('INSERT OR IGNORE INTO records(kind,id,payload) VALUES(?,?,?)', (kind, value['id'], raw))
    else:
        db.execute('INSERT INTO records(kind,id,payload) VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload', (kind, value['id'], raw))


def log(db, action, subject, detail):
    db.execute('INSERT INTO audit(time,action,subject,detail) VALUES(?,?,?,?)', (stamp(), action, subject, detail))


def decimal_value(value, positive=False):
    try:
        return num(value, minimum=D('0.000000001') if positive else D('0'), maximum=D('1000000000000'))
    except ValueError:
        return None


def scalar(value, positive=False):
    n = decimal_value(value, positive)
    return str(n) if n is not None else None


def count(value):
    n = decimal_value(value)
    return int(n) if n is not None and n == n.to_integral() else None


def valid_time(value, future=False):
    if not isinstance(value, str) or not value or value.startswith(('1970-', '0001-')):
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            # Provider dates have no timezone; retain the literal date but do
            # not fabricate a UTC timestamp or precise observation instant.
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) and not future:
                return value if dt.date() <= datetime.now(timezone.utc).date() else None
            return None
        if not future and dt > datetime.now(timezone.utc):
            return None
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def current_evidence(proof):
    if not isinstance(proof, dict) or not isinstance(proof.get('source'), str) or not proof['source'].strip():
        return False
    until = valid_time(proof.get('validUntil'), future=True)
    return bool(until and datetime.fromisoformat(until) > datetime.now(timezone.utc))


def issue(code, text, fields=(), severity='high'):
    return {'code': code, 'message': text, 'fields': list(fields), 'severity': severity}


def norm_title(text):
    return re.sub(r'[^\w\u4e00-\u9fff]+', '', unicodedata.normalize('NFKC', text).lower())


def normalize_row(raw, doc, tool, args, fetched_at, snapshot_id, index):
    platform = 'shopee' if tool.startswith('shopee_') else '1688'
    is_sku = tool == 'ali1688_product_variations'
    source_id = str(raw.get('sku_id') if is_sku else raw.get('product_id') or '')
    q = []
    row = {'id': digest([snapshot_id, index]), 'snapshotId': snapshot_id, 'rowIndex': index,
           'platform': platform, 'site': args.get('site', 'CN'), 'tool': tool, 'sourceId': source_id,
           'kind': 'sku' if is_sku else 'product', 'parentId': args.get('product_id') if is_sku else None,
           'title': str(raw.get('sku_name') if is_sku else raw.get('title') or ''),
           'fetchedAt': fetched_at, 'providerUpdatedAt': None, 'quality': q,
           'price': None, 'rawPrice': raw.get('offer_price') if is_sku else raw.get('price'),
           'currency': None, 'monthlySales': None, 'cumulativeSales': None, 'group': 'unknown',
           'evidenceStatus': 'provider_reported', 'verifiedPurchaseCost': None,
           'fieldProvenance': {'price': '/data/' + str(index) + ('/offer_price' if is_sku else '/price')}}
    if not re.fullmatch(r'\d{1,30}', source_id):
        q.append(issue('MISSING_ID', '来源商品或 SKU 标识缺失，不能关联', ['sourceId'], 'critical'))
    if platform == 'shopee':
        price_description = str(doc.get('price', ''))
        declared = re.findall(r'\b(PHP|THB|CNY|USD|VND|IDR|SGD|MYR|TWD|BRL)\b', price_description.upper())
        explicit_currency = str(raw.get('currency', '')).upper()
        currencies = set(declared + ([explicit_currency] if explicit_currency else []))
        if args.get('site') != 'PH' or currencies != {'PHP'}:
            q.append(issue('CURRENCY_CONFLICT' if currencies else 'CURRENCY_UNKNOWN', 'PH 请求与价格币种说明不一致或币种缺失；未自动改成 PHP', ['price', 'currency'], 'critical'))
        else:
            row['currency'], row['price'] = 'PHP', scalar(raw.get('price'), True)
        row['declaredCurrency'] = sorted(currencies)
        row['monthlySales'] = count(raw.get('sales_count'))
        row['cumulativeSales'] = count(raw.get('his_sales_count'))
        row['monthlyMetricDefinition'] = str(doc.get('sales_count', '未知'))
        row['providerUpdatedAt'] = valid_time(raw.get('sales_calc_time'))
        row['correctionDate'] = valid_time(raw.get('sale_is_correction'))
        row['priceUpdatedAt'] = None  # sales calculation date is NOT price time.
        row['salesRaw'] = raw.get('sales_count')
        if row['monthlySales'] is None:
            q.append(issue('MONTHLY_SALES_UNKNOWN', '月销量不可计算或缺失；不是 0', ['sales_count']))
        if row['providerUpdatedAt'] is None:
            q.append(issue('SALES_DATE_UNKNOWN', '销量计算时间缺失、占位或未来日期；抓取时间不能替代', ['sales_calc_time']))
        row['shopId'] = str(raw.get('shop_id') or '')
        row['shopName'] = raw.get('shop_name')
        row['group'] = {'本土店': 'local', '跨境店': 'cross_border', 'local store': 'local', 'cross-border store': 'cross_border'}.get(raw.get('shop_loc_type'), 'unknown')
        row['shopLocation'] = raw.get('shop_location')
        row['shopType'] = raw.get('shop_type')
        row['rating'] = scalar(raw.get('ratings'))
        row['ratingCount'] = count(raw.get('ratings_count'))
        row['listingDate'] = valid_time(raw.get('sale_time'))
        row['category'] = raw.get('bsr_category', [])
        row['brand'] = raw.get('brand')
        row['couponText'] = raw.get('coupon_str')
        row['arrivalPrice'], row['deliveryDays'], row['reviewThemes'], row['adStatus'] = None, None, None, None
        row['photos'] = raw.get('photo') if isinstance(raw.get('photo'), list) else [raw['photo']] if isinstance(raw.get('photo'), str) else []
        row['url'] = f"https://shopee.ph/product/{row['shopId']}/{source_id}" if row['shopId'].isdigit() and source_id.isdigit() else None
        q.append(issue('VARIANT_UNCONFIRMED', '搜索或详情标价未绑定同规格变体；到手价、运费和券条件待核实', ['price', 'variant'], 'medium'))
    else:
        row['currency'] = 'CNY' if 'CNY' in str(doc.get('offer_price' if is_sku else 'price', '')).upper() else None
        row['price'] = scalar(row['rawPrice'], True) if row['currency'] else None
        if row['price'] is None:
            q.append(issue('PRICE_UNKNOWN', '报价为零、缺失、非法或币种未知；不能当作免费采购', ['price'], 'critical'))
        row['stock'] = count(raw.get('stock' if is_sku else 'stock_count'))
        row['stockMeaning'] = '接口/商家报送数量，未证实可履约，不是自有库存'
        row['priceUpdatedAt'], row['stockUpdatedAt'] = None, None
        if is_sku:
            row['displayPrice'] = scalar(raw.get('price'), True)
            row['package'] = {k: scalar(raw.get(k), True) if re.search(r'\bcm\b|厘米', str(doc.get(k, '')), re.I) else None for k in ('width', 'height', 'length')}
            weight = decimal_value(raw.get('weight'), True)
            unit_kg = bool(re.search(r'\bkg\b|千克|公斤', str(doc.get('weight', '')), re.I))
            row['package']['weightG'] = str(weight * 1000) if weight is not None and unit_kg else None
            if not unit_kg:
                q.append(issue('PACKAGE_UNIT_UNKNOWN', '重量单位未明确为 kg，不自动换算为 g', ['weight']))
            row['packageSource'] = raw.get('pkg_size_source')
            if any(v is None for v in row['package'].values()):
                q.append(issue('PACKAGE_UNKNOWN', '包装尺寸/重量不完整；0 尺寸按未填写处理', ['width', 'height', 'length', 'weight']))
            q.append(issue('QUOTE_NOT_CONFIRMED', 'SKU offer_price 是接口报价，税票、运费、数量与可下单价格待确认', ['offer_price']))
            row['url'] = f"https://detail.1688.com/offer/{args['product_id']}.html"
        else:
            row['supplierName'] = raw.get('store_name')
            row['moq'] = count(raw.get('min_order_quantity'))
            if row['moq'] == 0:
                row['moq'] = None
            row['dropship'] = raw.get('is_drop_shipping') if type(raw.get('is_drop_shipping')) is bool else None
            row['tiers'] = raw.get('wholesale_price_range') if isinstance(raw.get('wholesale_price_range'), list) else []
            row['serviceScore'] = scalar(raw.get('service_score'))
            row['repurchaseRate'] = scalar(raw.get('repurchase_rate'))
            row['monthlySales'] = count(raw.get('sales_of_30d'))
            row['shippingOrigin'] = raw.get('shipping_origin')
            row['shippingTimeRaw'] = raw.get('shipping_time')
            duration = re.search(r'(\d+(?:\.\d+)?)\s*(小时|天|hours?|days?)', str(raw.get('shipping_time') or ''), re.I)
            row['dispatchHoursReported'] = str(D(duration[1]) * (24 if duration[2].lower() in ('天', 'day', 'days') else 1)) if duration else None
            if row['dispatchHoursReported'] is None:
                q.append(issue('DISPATCH_TIME_UNKNOWN', '发货时间不能解析为时长；不能把城市名转成天数', ['shipping_time']))
            if row['dropship'] and row['moq'] and row['moq'] > 1:
                q.append(issue('MOQ_DROPSHIP_CONFLICT', '一件代发标签与批发起订量大于 1 并存，必须核实单件下单条件', ['min_order_quantity', 'is_drop_shipping']))
            if not row['supplierName']:
                q.append(issue('SUPPLIER_UNKNOWN', '供应商名称缺失，需核实主体', ['store_name']))
            url = raw.get('url')
            row['url'] = url if isinstance(url, str) and re.fullmatch(r'https://detail\.1688\.com/offer/\d+\.html', url) else None
            row['photos'] = raw.get('photo') if isinstance(raw.get('photo'), list) else [raw['photo']] if isinstance(raw.get('photo'), str) else []
        if is_sku:
            row['photos'] = raw.get('photo') if isinstance(raw.get('photo'), list) else [raw['photo']] if isinstance(raw.get('photo'), str) else []
        q.append(issue('SUPPLY_TIME_UNKNOWN', '报价与库存的上游更新时间/有效期缺失；本次查询时间不等于报价生效时间', ['priceUpdatedAt', 'stockUpdatedAt']))
    row['titleFingerprint'] = norm_title(row['title'])
    row['identity'] = f"{platform}:{row['site']}:{row['kind']}:{row.get('parentId') or ''}:{source_id}"
    return row


def ingest(db, event, batch_id, transport):
    if not isinstance(event, dict):
        raise ValueError('采集记录格式错误')
    tool, args = event.get('tool'), event.get('args')
    validate_query(tool, args)
    fetched_at = valid_time(event.get('fetchedAt'))
    if not fetched_at or 'T' not in fetched_at:
        raise ValueError('采集时间必须明确、含时区且不能在未来')
    snapshot = {'tool': tool, 'args': args, 'fetchedAt': fetched_at, 'response': event.get('response'),
                'transport': transport, 'contractVersion': CONTRACT}
    snapshot['id'] = digest(snapshot)
    save(db, 'research_snapshot', snapshot, immutable=True)
    batch = read(db, 'research_batch', batch_id)
    if snapshot['id'] not in batch['snapshotIds']:
        batch['snapshotIds'].append(snapshot['id'])
    try:
        payload = unpack_response(event['response'])
        raw_data, doc = payload['data'], payload.get('doc', {})
        if not isinstance(doc, dict):
            raise ValueError('字段说明不是已知对象结构')
        is_products = tool in ('shopee_product_search_from_name', 'shopee_product_search', 'shopee_keyword_relation_results', 'shopee_product_request', 'ali1688_similar_product', 'ali1688_product_search', 'ali1688_product_search_from_image', 'ali1688_product_request', 'ali1688_product_variations')
        if is_products:
            nested = isinstance(raw_data, dict) and isinstance(raw_data.get('products'), list)
            rows = raw_data['products'] if nested else raw_data if isinstance(raw_data, list) else [raw_data] if isinstance(raw_data, dict) and ('product_id' in raw_data or 'sku_id' in raw_data) else None
            row_doc = {k.removeprefix('products.'): v for k, v in doc.items() if k.startswith('products.')} if nested else doc
            if rows is None or len(rows) > 2000 or any(not isinstance(row, dict) for row in rows):
                raise ValueError('商品响应结构或行数超出契约')
            normalized = []
            for i, raw in enumerate(rows):
                observation = normalize_row(raw, row_doc, tool, args, fetched_at, snapshot['id'], i)
                observation['rowPath'] = '/data/products/' + str(i) if nested else '/data/' + str(i) if isinstance(raw_data, list) else '/data'
                observation['fieldProvenance']['price'] = observation['rowPath'] + ('/offer_price' if observation['kind'] == 'sku' else '/price')
                normalized.append(observation)
            for observation in normalized:
                save(db, 'research_observation', observation, immutable=True)
                if observation['id'] not in batch['observationIds']:
                    batch['observationIds'].append(observation['id'])
        else:
            batch['notes'].append('类目/趋势数据已保存原始快照；不同趋势结构不强行并入商品表')
    except (ValueError, TypeError, KeyError) as exc:
        if tool in ('shopee_favorite_keyword', 'shopee_change_favorite_keyword', 'shopee_del_favorite_keyword') and isinstance(event.get('response'), dict) and not event['response'].get('isError'):
            batch['notes'].append('账号变更接口响应已原样保存；请查看原始回执，不将非商品回执解析成商品或自动重试')
        else:
            batch['notes'].append('快照隔离：' + str(exc)[:300])
    save(db, 'research_batch', batch)
    return snapshot['id']


def observation_details(db, observation_id):
    observation = read(db, 'research_observation', observation_id)
    snapshot = read(db, 'research_snapshot', observation['snapshotId'])
    payload = unpack_response(snapshot['response'])
    data = payload['data']
    nested = isinstance(data, dict) and isinstance(data.get('products'), list)
    raw = data['products'][observation['rowIndex']] if nested else data[observation['rowIndex']] if isinstance(data, list) else data
    doc = payload.get('doc', {})
    row_doc = {k.removeprefix('products.'): v for k, v in doc.items() if k.startswith('products.')} if nested else doc
    return {'observation': observation, 'raw': raw, 'doc': row_doc, 'originalDoc': doc,
            'snapshot': {k: snapshot[k] for k in ('id', 'tool', 'args', 'fetchedAt', 'transport')},
            'envelopeFields': {**{k: v for k, v in payload.items() if k not in ('doc', 'data')}, **({'data': {k: v for k, v in data.items() if k != 'products'}} if nested else {})}}


def snapshot_summary(snapshot):
    summary = {k: snapshot[k] for k in ('id', 'tool', 'args', 'fetchedAt', 'transport', 'contractVersion')}
    try:
        payload = unpack_response(snapshot['response'])
        data = payload['data']
        if isinstance(data, dict) and isinstance(data.get('products'), list):
            summary['resultInfo'] = {'page': data.get('page'), 'pageCount': data.get('page_count'), 'returnedRows': len(data['products'])}
        elif isinstance(data, list):
            summary['resultInfo'] = {'returnedRows': len(data)}
    except (ValueError, KeyError, TypeError):
        pass
    return summary


def new_batch(db, label, transport):
    batch = {'id': str(uuid.uuid4()), 'label': label[:200], 'createdAt': stamp(),
             'transport': transport, 'snapshotIds': [], 'observationIds': [], 'notes': []}
    save(db, 'research_batch', batch)
    return batch


def import_bundle(db, bundle, transport='manual_import'):
    if not isinstance(bundle, dict) or not isinstance(bundle.get('events'), list) or len(bundle['events']) > 50:
        raise ValueError('导入应为含 events 数组的采集快照，最多 50 个调用')
    key = digest([bundle, transport])
    previous = next((b for b in records(db, 'research_batch') if b.get('importHash') == key), None)
    if previous:
        return previous
    batch = new_batch(db, str(bundle.get('label', '导入快照')), transport)
    batch['importHash'] = key
    save(db, 'research_batch', batch)
    for event in bundle['events']:
        ingest(db, event, batch['id'], transport)
    log(db, '导入调研快照', batch['label'], '保留原始响应；导入记录不是后端实时连接')
    return read(db, 'research_batch', batch['id'])


def observations_with_conflicts(db):
    observations = records(db, 'research_observation')
    groups = {}
    for row in observations:
        groups.setdefault(row['identity'], []).append(row)
    for siblings in groups.values():
        if len(siblings) < 2:
            continue
        prices = {str(r.get('rawPrice')) for r in siblings}
        sales = {str(r.get('monthlySales')) for r in siblings}
        for row in siblings:
            # Different observation dates may legitimately differ. Preserve
            # each record and require the operator to select the right time.
            if len(prices) > 1:
                row['quality'].append(issue('PRICE_OBSERVATIONS_DIFFER', '同一来源商品的价格观测不同，需按时间和规格核对；未覆盖旧值', ['price']))
            if len(sales) > 1 and row['platform'] == 'shopee':
                row['quality'].append(issue('SALES_OBSERVATIONS_DIFFER', '搜索/详情或不同观测的月销量不一致，需核对计算窗口；未自动择优取值', ['sales_count']))
    return observations


def latest_unique(observations):
    result = {}
    for row in sorted(observations, key=lambda r: r['fetchedAt']):
        result[row['identity']] = row
    return list(result.values())


def source_profile(observations):
    unique = latest_unique(observations)
    issues = {}
    for row in unique:
        for q in row['quality']:
            issues[q['code']] = issues.get(q['code'], 0) + 1
    return {'observations': len(observations), 'uniqueRecords': len(unique),
            'duplicateObservations': len(observations) - len(unique),
            'shopeeProducts': sum(r['platform'] == 'shopee' for r in unique),
            'supplierOffers': sum(r['platform'] == '1688' and r['kind'] == 'product' for r in unique),
            'supplierSkus': sum(r['kind'] == 'sku' for r in unique), 'issues': issues,
            'scope': '关键词/选定商品样本，不代表全市场；跨链接相似标题仅作提示，不自动合并 SPU'}


def new_case(db, observation_id):
    row = read(db, 'research_observation', observation_id)
    if row['platform'] != 'shopee' or not row['sourceId'].isdigit():
        raise ValueError('请从 Shopee 商品结果创建候选研究')
    for previous in records(db, 'research_case'):
        if previous['marketIdentity'] == row['identity']:
            return previous
    case = {'id': str(uuid.uuid4()), 'revision': 1, 'title': row['title'], 'createdAt': stamp(),
            'marketIdentity': row['identity'], 'marketObservationId': observation_id,
            'selectionEvidence': selection.empty_evidence(),
            'offerObservationId': '', 'skuObservationId': '', 'specification': '', 'mappingEvidence': '',
            'mappingConfirmed': False, 'comparisons': [], 'pricePHP': '', 'marketMaxPHP': '',
            'marketEvidence': {'source': '', 'validUntil': ''},
            'demandEvidence': {'source': '', 'validUntil': '', 'value': '', 'windowStart': '', 'windowEnd': ''},
            'quote': {'unitPrice': '', 'unitsPerSale': '', 'purchaseQuantity': '', 'moq': '', 'stock': '', 'leadDays': '',
                      'dropship': 'unknown', 'source': '', 'validUntil': '', 'confirmed': False},
            'package': {'weightG': '', 'length': '', 'width': '', 'height': '', 'source': '', 'validUntil': ''},
            'costs': {k: {'amount': '', 'source': '', 'validUntil': ''} for k in COST_FIELDS if k != 'purchase'},
            'rulesEvidence': {'source': '', 'validUntil': '', 'version': ''},
            'cashEvidence': {'source': '', 'validUntil': '', 'requestedUnits': ''},
            'checks': {k: 'unknown' for k in ('rights', 'compliance', 'carrier', 'sensitiveGoods', 'facts', 'homeCategory', 'simpleCertification')},
            'checksEvidence': {'source': '', 'validUntil': ''}, 'payment': 'normal', 'buyerShippingPHP': '',
            'orderFeeExempt': False, 'disposition': 'open', 'dispositionReason': '', 'notes': ''}
    save(db, 'research_case', case)
    log(db, '新建候选研究', case['title'], '未自动复制竞品素材或默认成本；未知值保留')
    return case


def update_case(db, body):
    old = read(db, 'research_case', body.get('id'))
    if body.get('revision') != old['revision']:
        raise ValueError('研究已在其他操作中修改，请刷新后重试')
    allowed = {'title', 'offerObservationId', 'skuObservationId', 'specification', 'mappingEvidence', 'mappingConfirmed',
               'comparisons', 'pricePHP', 'marketMaxPHP', 'marketEvidence', 'demandEvidence', 'quote', 'package', 'costs',
               'rulesEvidence', 'cashEvidence', 'checks', 'checksEvidence', 'payment', 'buyerShippingPHP',
               'orderFeeExempt', 'disposition', 'dispositionReason', 'notes', 'selectionEvidence'}
    case = deepcopy(old)
    case.setdefault('selectionEvidence', selection.empty_evidence())
    for key in allowed:
        if key in body:
            case[key] = body[key]
    selection.validate_evidence(case['selectionEvidence'])
    if not isinstance(case['title'], str) or not case['title'].strip() or len(case['title']) > 1000:
        raise ValueError('研究名称不能为空')
    for key in ('marketEvidence', 'demandEvidence', 'quote', 'package', 'costs', 'rulesEvidence', 'cashEvidence', 'checks', 'checksEvidence'):
        if not isinstance(case[key], dict):
            raise ValueError('证据与成本格式错误')
    for key in ('specification', 'mappingEvidence', 'notes', 'dispositionReason', 'offerObservationId', 'skuObservationId'):
        if not isinstance(case[key], str) or len(case[key]) > 10000:
            raise ValueError('文本格式不正确或过长')
    if type(case['mappingConfirmed']) is not bool or type(case['quote'].get('confirmed')) is not bool or type(case['orderFeeExempt']) is not bool:
        raise ValueError('确认标记必须是布尔值')
    if case['payment'] not in ('normal', 'installment') or case['disposition'] not in ('open', 'deferred', 'rejected'):
        raise ValueError('状态不正确')
    if case['disposition'] != 'open' and not case['dispositionReason'].strip():
        raise ValueError('暂缓/淘汰必须记录原因')
    if case['quote'].get('dropship') not in ('unknown', 'yes', 'no'):
        raise ValueError('代发状态不正确')
    if any(v not in ('unknown', 'yes', 'no') for v in case['checks'].values()):
        raise ValueError('核实状态必须是未知、通过或不通过')
    numeric = [case.get('pricePHP'), case.get('marketMaxPHP'), case.get('buyerShippingPHP'), case['cashEvidence'].get('requestedUnits'), case['demandEvidence'].get('value')]
    numeric += [case['quote'].get(k) for k in ('unitPrice', 'unitsPerSale', 'purchaseQuantity', 'moq', 'stock', 'leadDays')]
    numeric += [case['package'].get(k) for k in ('weightG', 'length', 'width', 'height')]
    for key, cost in case['costs'].items():
        if key not in COST_FIELDS or key == 'purchase' or not isinstance(cost, dict):
            raise ValueError('成本字段不正确')
        numeric.append(cost.get('amount'))
    for value in numeric:
        if value not in (None, ''):
            num(value)
    proofs = [case[k] for k in ('marketEvidence', 'demandEvidence', 'quote', 'package', 'rulesEvidence', 'cashEvidence', 'checksEvidence')]
    proofs += list(case['costs'].values())
    for proof in proofs:
        for key in ('source', 'validUntil'):
            if not isinstance(proof.get(key, ''), str) or len(proof.get(key, '')) > 10000:
                raise ValueError('证据说明和有效期必须为文本')
    for oid, kind in [(case['offerObservationId'], 'product'), (case['skuObservationId'], 'sku')]:
        if oid:
            obs = read(db, 'research_observation', oid)
            if obs['platform'] != '1688' or obs['kind'] != kind or not obs['sourceId'].isdigit():
                raise ValueError('货源或 SKU 引用类型不正确')
    if not isinstance(case['comparisons'], list) or len(case['comparisons']) > 100:
        raise ValueError('竞品对比最多 100 条')
    seen = set()
    for comparison in case['comparisons']:
        if not isinstance(comparison, dict):
            raise ValueError('竞品格式不正确')
        obs = read(db, 'research_observation', comparison.get('observationId'))
        if obs['platform'] != 'shopee' or obs['identity'] in seen:
            raise ValueError('竞品必须来自 Shopee 且同一商品不得重复计数')
        seen.add(obs['identity'])
        if comparison.get('sameSpec') not in ('yes', 'no', 'unknown'):
            raise ValueError('同规格状态不正确')
        for key in ('source', 'validUntil', 'specEvidence'):
            if not isinstance(comparison.get(key, ''), str) or len(comparison.get(key, '')) > 10000:
                raise ValueError('竞品核实依据必须为文本')
        if comparison.get('arrivalPricePHP') not in ('', None):
            num(comparison['arrivalPricePHP'], minimum=D('0.01'))
        if comparison.get('sales30d') not in ('', None):
            value = num(comparison['sales30d'])
            if value != value.to_integral():
                raise ValueError('同规格30天销量必须是非负整数')
        if comparison.get('salesScope', 'unknown') not in ('unknown', 'same_spec_30d', 'cumulative', 'mixed_variants'):
            raise ValueError('销量口径无效')
        for field in ('observedAt', 'salesWindowStart', 'salesWindowEnd'):
            if not isinstance(comparison.get(field, ''), str) or len(comparison.get(field, '')) > 100:
                raise ValueError('竞品观察日期必须是文本')
    for field in ('observedAt',):
        if not isinstance(case['quote'].get(field, ''), str) or len(case['quote'].get(field, '')) > 100:
            raise ValueError('报价复核时间格式错误')
    case['revision'] += 1
    case['updatedAt'] = stamp()
    save(db, 'research_case', case)
    log(db, '更新候选研究', case['title'], '保留原始快照；所有判断重新计算')
    return case


def autosave_case(db, body):
    """Persist partial edits separately; invalid drafts never certify a case."""
    old = read(db, 'research_case', body.get('id'))
    try:
        prior = read(db, 'research_draft', old['id'])
    except ValueError:
        prior = {'revision': 0}
    request_id = body.get('requestId')
    if not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9-]{8,100}', request_id):
        raise ValueError('自动保存请求标识无效')
    if prior.get('requestId') == request_id:
        return {'case': old, 'draft': prior, 'conflict': False}
    # Preserve the competing draft for recovery, never silently last-write-win.
    if body.get('draftRevision', 0) != prior['revision'] or body.get('revision') != old['revision']:
        conflict = {'id': str(uuid.uuid4()), 'caseId': old['id'], 'createdAt': stamp(),
                    'payload': body, 'reason': '另一个页面已保存新版本；没有覆盖新版本'}
        save(db, 'research_conflict_draft', conflict)
        return {'conflict': True, 'recoveryId': conflict['id'], 'case': old, 'draft': prior,
                'error': '检测到并发修改；你的草稿已另存，可在自动保存恢复记录中查看'}
    excluded = {'createdAt', 'updatedAt', 'marketIdentity', 'marketObservationId', 'assessment'}
    payload = {k: body[k] for k in set(old) | {'selectionEvidence'} if k not in excluded and k in body}
    payload.update(id=old['id'], revision=old['revision'])
    if len(json.dumps(payload, ensure_ascii=False)) > 300000:
        raise ValueError('候选草稿超过 300KB')
    validation_error = None
    try:
        current = update_case(db, payload)
        status = 'committed'
    except (ValueError, TypeError, AttributeError) as exc:
        current, status = old, 'draft'
        validation_error = str(exc) if isinstance(exc, ValueError) else '资料结构尚不完整，已自动保存草稿'
    payload['revision'] = current['revision']
    draft = {'id': old['id'], 'revision': prior['revision'] + 1, 'caseRevision': current['revision'],
             'requestId': request_id, 'savedAt': stamp(), 'status': status,
             'validationError': validation_error, 'payload': payload}
    save(db, 'research_draft', draft)
    return {'case': current, 'draft': draft, 'conflict': False}


def compare_market(case, observations):
    by_id = {r['id']: r for r in observations}
    groups = {'local': [], 'cross_border': [], 'unknown': []}
    excluded, valid_ids = [], []
    for item in case.get('comparisons', []):
        obs = by_id.get(item.get('observationId'))
        if not obs:
            continue
        arrival = decimal_value(item.get('arrivalPricePHP'), True)
        if item.get('sameSpec') != 'yes' or not str(item.get('specEvidence', '')).strip() or arrival is None or not current_evidence(item):
            excluded.append(obs['id'])
            continue
        groups[obs['group']].append(arrival)
        valid_ids.append(obs['id'])
    results = {}
    for group, prices in groups.items():
        ordered = sorted(prices)
        n = len(ordered)
        median = ((ordered[(n-1)//2] + ordered[n//2]) / 2) if n else None
        results[group] = {'count': n, 'min': money(min(prices)) if n else None,
                          'median': money(median) if n else None, 'max': money(max(prices)) if n else None}
    return {'groups': results, 'validCount': len(valid_ids), 'excludedCount': len(excluded),
            'scope': '仅人工核实同规格、PHP 到手价与有效证据的样本；本地/跨境不混算', 'validIds': valid_ids}


def assess(case, settings, observations, policy=None):
    policy = policy or DEFAULT_POLICY
    by_id = {r['id']: r for r in observations}
    needs, failures, warnings = [], [], []
    def need(code, label, where):
        needs.append({'code': code, 'message': label, 'section': where, 'owner': '店主/资料提供方'})
    quote, package = case['quote'], case['package']
    offer, sku = by_id.get(case['offerObservationId']), by_id.get(case['skuObservationId'])
    if not offer or not sku or sku.get('parentId') != offer.get('sourceId'):
        need('SKU_MAPPING', '选择同一 1688 商品下的真实 SKU，不按搜索最低价代替', '货源与规格')
    if not case['mappingConfirmed'] or not case['specification'].strip() or not case['mappingEvidence'].strip():
        need('SPECIFICATION', '确认两平台数量、尺寸、材质、功能、颜色/型号相符，并填写证据', '货源与规格')
    if not quote.get('confirmed') or not current_evidence(quote):
        need('PURCHASE_QUOTE', '补充可下单 SKU 报价、数量、税票条件及有效期；接口报价不是最终采购成本', '货源与规格')
    unit, per_sale = decimal_value(quote.get('unitPrice'), True), count(quote.get('unitsPerSale'))
    quantity, moq, stock = count(quote.get('purchaseQuantity')), count(quote.get('moq')), count(quote.get('stock'))
    if unit is None or not per_sale or not quantity or not moq or stock is None:
        need('PURCHASE_QUANTITY', '单价、每销售单元采购数量、实际下单量、MOQ、可供库存必须完整', '货源与规格')
    if quantity and moq and quantity < moq:
        failures.append('实际采购量小于已确认 MOQ')
    if quantity and per_sale and quantity < per_sale:
        failures.append('实际采购量不足一个完整销售单元')
    if stock is not None and quantity and stock < quantity:
        failures.append('已确认可供库存不足')
    if quote.get('dropship') == 'no':
        failures.append('不支持当前要求的出单后单件代发')
    elif quote.get('dropship') != 'yes':
        need('DROPSHIP', '确认适用于选定 SKU/数量的一件代发能力', '货源与规格')
    if sku and unit is not None and sku.get('price') and unit != D(sku['price']):
        warnings.append('人工确认单价与接口 SKU 报价不同；必须在报价依据中解释，不自动覆盖任一值')
    if offer and sku and offer.get('price') and sku.get('price') and D(offer['price']) != D(sku['price']):
        warnings.append('1688 商品展示价与所选 SKU 报价不同，严禁使用较低展示价冒充该 SKU 采购价')
    if not current_evidence(package) or any(decimal_value(package.get(k), True) is None for k in ('weightG', 'length', 'width', 'height')):
        need('PACKAGE', '补全包装后长宽高/cm、重量/g、证据及有效期；商家自填不是实测', '物流与合规')
    lead = count(quote.get('leadDays'))
    if lead is None:
        need('DISPATCH', '提供供应商承诺备货天数；不可从城市名推断', '货源与规格')
    elif lead + int(settings['domesticDays']) + int(settings['warehouseDays']) + 1 > int(settings['shipDeadlineDays']):
        failures.append('当前备货、国内运输、云仓与缓冲天数超过交运期限')
    for key, label in {'rights': '素材权利', 'compliance': '禁限售/资质', 'carrier': 'SLS/云仓承运', 'sensitiveGoods': '不含化学/带电/易燃易爆', 'facts': '商品事实', 'homeCategory': '属于家居用品', 'simpleCertification': '无需复杂认证额外成本'}.items():
        value = case['checks'].get(key, 'unknown')
        if value == 'no':
            failures.append(label + '核实不通过')
        elif value != 'yes':
            need('CHECK_' + key.upper(), label + '待核实', '物流与合规')
    if not current_evidence(case['checksEvidence']):
        need('CHECKS_EVIDENCE', '补充物流/合规/素材核实依据及有效期', '物流与合规')
    costs = {}
    if unit is not None and per_sale:
        costs['purchase'] = money(unit * per_sale)
    for key, label in COST_FIELDS.items():
        if key == 'purchase':
            continue
        item = case['costs'].get(key, {})
        amount = decimal_value(item.get('amount'))
        if amount is None or not current_evidence(item):
            need('COST_' + key.upper(), label + '金额、分摊依据或有效期缺失；不适用也需证据明确填 0', '成本与利润')
        if amount is not None:
            costs[key] = money(amount)
    rules_ok = settings['rules'].get('verified') is True and current_evidence(case['rulesEvidence']) and case['rulesEvidence'].get('version') == settings['rules'].get('version')
    if not rules_ok:
        need('FEE_RULES', '核实本店费用/汇率/时限配置，并绑定当前规则版本和有效期', '成本与利润')
    price, ceiling = decimal_value(case.get('pricePHP'), True), decimal_value(case.get('marketMaxPHP'), True)
    buyer_shipping = decimal_value(case.get('buyerShippingPHP'))
    policy_ceiling = D(policy['maxSellingPricePHP'])
    if price is not None and price > policy_ceiling:
        failures.append('计划商品成交价超过店主设置的 ' + str(policy_ceiling) + ' PHP 上限')
    if price is None or buyer_shipping is None:
        need('REVENUE', '确认计划成交价 PHP 与买家运费；未知不得自动填 0', '成本与利润')
    if ceiling is None or not current_evidence(case['marketEvidence']):
        need('MARKET_CEILING', '给出同规格市场可接受成交价上限及证据；不能用最高搜索标价替代', '竞品与需求')
    comparison = compare_market(case, observations)
    if comparison['validCount'] < 10:
        need('SAMPLE_SIZE', f"已核实同规格竞品 {comparison['validCount']}/10，样本不足；不虚构补齐", '竞品与需求')
    # v0.4 derives demand from individually reviewed, same-spec 30-day rows.
    # Retain legacy demandEvidence only as historical data, never as a gate.
    calc, recommendation, max_purchase, scenarios = None, None, None, []
    finance_ready = (not any(n['section'] == '成本与利润' or n['code'] in ('SKU_MAPPING', 'SPECIFICATION', 'PURCHASE_QUANTITY') for n in needs)
                     and quote.get('confirmed') and current_evidence(quote) and len(costs) == len(COST_FIELDS)
                     and quantity >= moq and quantity >= per_sale and stock >= quantity)
    if finance_ready:
        product = {'price': str(price), 'costs': costs, 'buyerShipping': str(buyer_shipping), 'payment': case['payment'], 'orderFeeExempt': case['orderFeeExempt']}
        try:
            calc = evaluate(product, settings['rules'])
            recommendation = solve_price(product, settings['rules'])
        except ValueError as exc:
            finance_ready, calc, recommendation = False, None, None
            need('CALCULATION_RANGE', '核算参数超出引擎范围：' + str(exc), '成本与利润')
    if finance_ready:
        if not calc['meetsTarget']:
            failures.append('计划成交价未同时达到净利率和单件利润目标')
        if not recommendation:
            failures.append('当前费用结构在 1–100000 PHP 内无可行目标价')
        elif ceiling is not None and D(recommendation['price']) > ceiling:
            failures.append('双目标最低成交价高于已确认市场上限')
        if recommendation and D(recommendation['price']) > policy_ceiling:
            failures.append('双目标最低成交价超过店主成交价上限')
        if price is not None and ceiling is not None and price > ceiling:
            failures.append('计划成交价高于已确认市场上限')
        # Max purchase budget at the entered selling price, excluding the
        # currently entered purchase cost; both profit constraints apply.
        revenue, profit = D(calc['revenue']), D(calc['profit'])
        margin_cost_ceiling = revenue * (1 - D(settings['rules']['targetMargin']) / 100)
        profit_cost_ceiling = revenue - D(settings['rules']['targetProfit'])
        other_cost = D(calc['totalCost']) - D(costs['purchase'])
        max_purchase = str((min(margin_cost_ceiling, profit_cost_ceiling) - other_cost).quantize(D('.01'), rounding=ROUND_FLOOR))
        for label, changes in [('基准', {}), ('采购 +10%', {'purchase': D('1.10')}), ('SLS +15%', {'sls': D('1.15')}), ('PHP 贬值 5%', {'fx': D('.95')}), ('高档分期', {'installment': True}), ('组合压力', {'purchase': D('1.10'), 'sls': D('1.15'), 'fx': D('.95'), 'installment': True})]:
            pp, rr = deepcopy(product), deepcopy(settings['rules'])
            for key, value in changes.items():
                if key in ('purchase', 'sls'):
                    pp['costs'][key] = money(D(pp['costs'][key]) * value)
                elif key == 'fx':
                    rr['fx'] = str(D(rr['fx']) * value)
                else:
                    pp['payment'] = 'installment'
            try:
                scenarios.append({'label': label, **evaluate(pp, rr)})
            except ValueError as exc:
                scenarios.append({'label': label, 'error': str(exc), 'profit': None, 'margin': None, 'meetsTarget': False})
    cash, saleable = None, None
    requested = count(case['cashEvidence'].get('requestedUnits'))
    if not current_evidence(case['cashEvidence']) or not requested:
        need('CASH_CONFIRMATION', '核实银行余额/承诺/保护资金，填写拟承诺销售数量及证据有效期', '资金与处置')
    elif finance_ready and quantity and unit is not None:
        if requested * per_sale > stock:
            failures.append('拟承诺销售数量超过已确认供应商库存可支持数量')
        available = D(settings['bankBalance']) - D(settings['committed']) - D(settings['reserve'])
        # Conservatively reserve all per-unit costs plus the confirmed MOQ
        # purchase lot; this is an upper-bound scenario, not real cash flow.
        non_purchase = D(calc['totalCost']) - D(costs['purchase'])
        purchase_lot = unit * max(quantity, requested * per_sale)
        required = purchase_lot + non_purchase * requested
        cash = {'available': money(available), 'requiredConservative': money(required), 'requestedUnits': requested,
                'basis': '采购按实际批量/MOQ垫付，其余所有成本保守预留；不是回款预测或真实预留'}
        if required > available:
            failures.append('拟承诺数量的保守资金需求超过已核实可用资金')
        saleable = min(stock // per_sale, int(max(D('0'), available) / D(calc['totalCost']))) if stock is not None and D(calc['totalCost']) > 0 else None
        warnings.append('资金可售上限仅为库存/资金参考，未接入当日履约能力及平台库存限制，不能自动发布库存')
    seven = selection.assess_selection(case, settings, observations, {'calculation': calc})
    needs.extend(seven['needs'])
    failures.extend(seven['failures'])
    if case['disposition'] == 'rejected':
        failures.append('人工淘汰：' + case['dispositionReason'])
    state = 'rejected' if failures else 'needs_evidence' if needs else 'deferred' if case['disposition'] == 'deferred' else 'eligible_for_review'
    return {'state': state, 'label': {'rejected': '当前方案不通过', 'needs_evidence': '资料不足，不能判定', 'deferred': '人工暂缓', 'eligible_for_review': '可进入人工试验审核'}[state],
            'needs': needs, 'failures': failures, 'warnings': warnings, 'calculation': calc, 'recommended': recommendation,
            'maxPurchasePerSaleCNY': max_purchase, 'scenarios': scenarios, 'comparison': comparison,
            'cash': cash, 'stockCashUpperBound': saleable, 'canPublish': False, 'canPurchase': False,
            'selection': seven, 'canReviewListing': state == 'eligible_for_review',
            'assessmentFingerprint': digest([case, settings, policy, selection.POLICY, observations]),
            'meaning': '七维及资金硬门槛通过后可进入人工上架测试审核；不保证销量或最终利润；每个变体分别核实'}


def assessment_with_draft(case, settings, observations, policy, draft=None):
    result = assess(case, settings, observations, policy)
    if draft and draft['status'] == 'draft':
        result.update(state='needs_evidence', label='草稿已保存，资料待校验', calculation=None,
                      recommended=None, maxPurchasePerSaleCNY=None, scenarios=[], cash=None,
                      stockCashUpperBound=None, canPublish=False, canPurchase=False, canReviewListing=False,
                      selection={**result['selection'], 'score': None, 'observedScore': 0, 'eligible': False,
                                 'dimensions': [], 'metrics': {}, 'stress': None})
        result['needs'].insert(0, {'code': 'DRAFT_PENDING', 'message': draft['validationError'],
                                  'section': '自动保存草稿', 'owner': '店主'})
    return result


def research_state(db, connector_status):
    obs = observations_with_conflicts(db)
    settings = read(db, 'settings', 'main')
    policy = get_policy(db)
    cases = records(db, 'research_case')
    drafts = records(db, 'research_draft')
    draft_by_id = {d['id']: d for d in drafts}
    for case in cases:
        case.setdefault('selectionEvidence', selection.empty_evidence())
        draft = draft_by_id.get(case['id'])
        case['assessment'] = assessment_with_draft(case, settings, obs, policy, draft)
    snapshots = records(db, 'research_snapshot')
    return {'version': VERSION, 'connector': connector_status, 'policy': policy, 'batches': records(db, 'research_batch'),
            'observations': obs, 'cases': cases, 'drafts': drafts, 'conflictDrafts': records(db, 'research_conflict_draft')[:30], 'jobs': records(db, 'research_job')[:50],
            'snapshots': [snapshot_summary(s) for s in snapshots],
            'profile': source_profile(obs), 'rulesVersion': settings['rules']['version'],
            'selectionPolicy': selection.POLICY, 'selectionFields': selection.FIELDS,
            'scorePolicy': '七维100分；总分至少75且所有硬门槛通过才进入人工上架测试审核；未知不补分'}
