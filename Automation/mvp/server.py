"""Local-only, zero-dependency MVP. Run: python server.py"""
import argparse
import base64
import csv
import io
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import threading
import uuid
import zipfile
from copy import deepcopy
from contextlib import contextmanager
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from decimal import Decimal as D

from engine import analyze, evaluate, solve_price, fingerprint, generate_content, stamp, num, money, COST_FIELDS
from seed import default_settings, seed_products, seed_suppliers
import research
from sorftime import SorftimeClient, ConnectorError, validate_query, MUTATING

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get('MEEYA_DB', str(ROOT / 'data' / 'meeya.sqlite3')))
LOCK = threading.RLock()
TOKEN = secrets.token_urlsafe(32)
SORFTIME = SorftimeClient()
RESEARCH_TASK_LOCK = threading.Lock()


def research_worker(job_id, connector):
    # One network task at a time; do not hold the database lock over I/O.
    if not RESEARCH_TASK_LOCK.acquire(blocking=False):
        with LOCK, connect() as db:
            job = research.read(db, 'research_job', job_id)
            job.update(status='failed', error='已有采集在执行，请完成后再发起；本次没有调用外部服务')
            research.save(db, 'research_job', job)
        return
    try:
        with LOCK, connect() as db:
            job = research.read(db, 'research_job', job_id)
            job.update(status='running', startedAt=stamp())
            research.save(db, 'research_job', job)
        response = connector.call(job['tool'], job['args'], confirmed=True) if job.get('confirmedExternalChange') else connector.call(job['tool'], job['args'])
        with LOCK, connect() as db:
            prior_notes = len(research.read(db, 'research_batch', job['batchId'])['notes'])
            snapshot_id = research.ingest(db, {'tool': job['tool'], 'args': job['args'], 'fetchedAt': stamp(), 'response': response}, job['batchId'], 'backend_mcp')
            new_notes = research.read(db, 'research_batch', job['batchId'])['notes'][prior_notes:]
            quarantine = next((n for n in new_notes if n.startswith('快照隔离')), None)
            job.update(status='quarantined' if quarantine else 'completed', error=quarantine, finishedAt=stamp(), snapshotId=snapshot_id)
            research.save(db, 'research_job', job)
            research.log(db, 'MCP 调研采集', job['tool'], '原始快照已保存；不等于数据已经核实')
    except Exception as exc:
        with LOCK, connect() as db:
            job = research.read(db, 'research_job', job_id)
            message = str(exc) if isinstance(exc, (ConnectorError, ValueError)) else '采集失败；未生成数据，未自动重试'
            job.update(status='failed', finishedAt=stamp(), error=message[:500], errorCode=getattr(exc, 'code', 'FAILED'))
            research.save(db, 'research_job', job)
    finally:
        RESEARCH_TASK_LOCK.release()


@contextmanager
def connect():
    db = sqlite3.connect(DB_PATH, timeout=20)
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:
            yield db
    finally:
        db.close()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE IF NOT EXISTS records (kind TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(kind,id))')
        db.execute('CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, time TEXT NOT NULL, action TEXT NOT NULL, subject TEXT NOT NULL, detail TEXT NOT NULL)')
        if not db.execute("SELECT 1 FROM records WHERE kind='settings'").fetchone():
            put(db, 'settings', 'main', default_settings())
            for p in seed_products():
                put(db, 'product', p['id'], p)
            for s in seed_suppliers():
                put(db, 'supplier', s['id'], s)
            audit(db, '初始化', '演示工作区', '8 个虚构商品、3 个虚构供应商；未连接外部平台')


def recover_research_jobs():
    with LOCK, connect() as db:
        for job in research.records(db, 'research_job'):
            if job['status'] in ('queued', 'running'):
                job.update(status='interrupted', error='服务已重启；结果可能未落库，不自动重复计费调用，请人工确认后重试')
                research.save(db, 'research_job', job)


def put(db, kind, id, value):
    db.execute('INSERT INTO records(kind,id,payload) VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload', (kind, id, json.dumps(value, ensure_ascii=False)))


def get(db, kind, id):
    row = db.execute('SELECT payload FROM records WHERE kind=? AND id=?', (kind, id)).fetchone()
    if not row:
        raise ValueError('记录不存在')
    return json.loads(row[0])


def all_records(db, kind):
    return [json.loads(row[0]) for row in db.execute('SELECT payload FROM records WHERE kind=? ORDER BY rowid DESC', (kind,))]


def audit(db, action, subject, detail=''):
    db.execute('INSERT INTO audit(time,action,subject,detail) VALUES(?,?,?,?)', (stamp(), action, subject, detail))


def supplier_for(db, p):
    try:
        return get(db, 'supplier', p.get('supplierId', ''))
    except ValueError:
        return None


def check_revision(old, body):
    if body.get('revision') != old.get('revision'):
        raise ValueError('数据已在另一个操作中修改，请刷新后重试')


def clean_product(p):
    if not isinstance(p, dict) or not isinstance(p.get('costs'), dict) or not isinstance(p.get('checks'), dict):
        raise ValueError('商品、成本和核实字段必须是对象')
    if type(p.get('orderFeeExempt', False)) is not bool:
        raise ValueError('固定费豁免必须是布尔值')
    for key in ['name', 'englishName', 'category', 'source', 'supplierId', 'supplierSku', 'quoteValidUntil', 'researchCaseId']:
        if not isinstance(p.get(key, ''), str) or len(p.get(key, '')) > 1500:
            raise ValueError(f'{key}格式不正确或过长')
    if not p.get('name', '').strip():
        raise ValueError('请填写商品名称')
    num(p.get('price'), '成交价', D('0.01'), D('100000'))
    if p.get('marketMax') not in (None, ''):
        num(p['marketMax'], '市场上限', D('0.01'), D('100000'))
    num(p.get('buyerShipping', '0'), '买家运费')
    for key, value in p.get('costs', {}).items():
        if key not in COST_FIELDS:
            raise ValueError('未知成本字段')
        if value not in (None, ''):
            num(value, COST_FIELDS[key], D('0'), D('100000'))
    if p.get('weight') not in (None, ''):
        num(p['weight'], '重量', D('0.01'), D('100000'))
    if p.get('payment') not in ('normal', 'installment'):
        raise ValueError('支付方式不正确')
    for k, v in p.get('checks', {}).items():
        if type(v) is not bool:
            raise ValueError('核实字段必须是布尔值')
    limits = [20, 15, 25, 20, 10, 10]
    if not isinstance(p.get('scores'), list) or len(p['scores']) != 6 or any(type(v) is not int or v < 0 or v > limits[i] for i, v in enumerate(p['scores'])):
        raise ValueError('六项评分超出各自上限')
    if not isinstance(p.get('facts'), dict) or any(not isinstance(v, str) or len(v) > 1000 for v in p['facts'].values()):
        raise ValueError('商品事实格式不正确')
    content = p.get('content')
    if content and (not isinstance(content, dict) or any(not isinstance(content.get(k, ''), str) or len(content.get(k, '')) > 15000 for k in ['title', 'description', 'imagePrompt'])):
        raise ValueError('文案格式不正确')
    if p.get('imageUrl') and not re.fullmatch(r'/assets/[a-f0-9-]+', p['imageUrl']):
        raise ValueError('仅支持本机上传图片')
    return p


def validate_settings(s):
    if not isinstance(s, dict) or not isinstance(s.get('rules'), dict):
        raise ValueError('配置格式不正确')
    rules = s['rules']
    if not isinstance(rules.get('source'), str) or len(rules['source']) > 5000:
        raise ValueError('规则依据格式不正确')
    for key in ['commission', 'platformShipping', 'transaction', 'installment', 'growth', 'marketing', 'receiving']:
        num(rules.get(key), key, D('0'), D('100'))
    num(rules.get('fx'), '汇率', D('0.000001'), D('100'))
    num(rules.get('targetMargin'), '净利率目标', D('0'), D('95'))
    for key in ['shippingCap', 'orderFee', 'targetProfit']:
        num(rules.get(key), key)
    for key in ['bankBalance', 'committed', 'reserve', 'advancePerOrder', 'monthlyTarget']:
        num(s.get(key), key)
    for key in ['dailyTarget', 'dailyOrders', 'cashCycle', 'domesticDays', 'warehouseDays', 'shipDeadlineDays']:
        value = num(s.get(key), key, D('0'), D('1000'))
        if value != value.to_integral():
            raise ValueError(f'{key}必须是整数')
    if type(rules.get('verified')) is not bool:
        raise ValueError('规则核实状态不正确')
    if rules['verified'] and not rules.get('source', '').strip():
        raise ValueError('核实规则时必须提供证据来源')


def analyze_product(db, product, settings, supplier):
    result = analyze(product, settings, supplier)
    if product.get('demo'):
        return result
    reasons = []
    try:
        case = research.read(db, 'research_case', product.get('researchCaseId', ''))
        draft = next((d for d in research.records(db, 'research_draft') if d['id'] == case['id']), None)
        decision = research.assessment_with_draft(case, settings, research.observations_with_conflicts(db), research.get_policy(db), draft)
        result['selectionFingerprint'] = decision['assessmentFingerprint']
        result['score'] = decision['selection']['score']
        if not decision['canReviewListing']:
            reasons.append('关联候选未通过七维与资金门槛，请到调研与选品补证')
        sku = research.read(db, 'research_observation', case['skuObservationId']) if case['skuObservationId'] else {}
        matches = (str(product.get('supplierSku', '')) == sku.get('sourceId')
                   and product.get('name') == case['title']
                   and product.get('payment') == case['payment']
                   and product.get('orderFeeExempt', False) == case['orderFeeExempt'])
        for a, b in [(product.get('price'),case['pricePHP']), (product.get('buyerShipping'),case['buyerShippingPHP']), (product.get('weight'),case['package'].get('weightG'))]:
            matches = matches and research.decimal_value(a) is not None and research.decimal_value(a) == research.decimal_value(b)
        if decision['calculation']:
            for key in COST_FIELDS:
                expected = D(case['quote']['unitPrice'])*D(case['quote']['unitsPerSale']) if key == 'purchase' else research.decimal_value(case['costs'].get(key, {}).get('amount'))
                matches = matches and expected is not None and research.decimal_value(product.get('costs', {}).get(key)) == expected
        if not matches:
            reasons.append('内容商品与关联研究的名称、SKU、价格、支付、重量或成本不一致，不能沿用选品结论')
        if (product.get('approval') or {}).get('selectionFingerprint') != result['selectionFingerprint']:
            result['approvalValid'] = False
    except (ValueError, TypeError, KeyError):
        reasons.append('真实商品需关联已通过七维核验的候选研究，旧六项手动分不能替代')
    result['blockers'] = list(dict.fromkeys(result['blockers'] + reasons))
    if result['blockers']:
        result.update(canApprove=False, approvalValid=False, state='blocked')
    elif not result['approvalValid']:
        result['state'] = 'review' if result['contentReady'] else 'ready'
    return result


def state(db):
    settings = get(db, 'settings', 'main')
    suppliers = all_records(db, 'supplier')
    smap = {s['id']: s for s in suppliers}
    products = all_records(db, 'product')
    for p in products:
        p['analysis'] = analyze_product(db, p, settings, smap.get(p.get('supplierId')))
    logs = [dict(zip(['time', 'action', 'subject', 'detail'], row)) for row in db.execute('SELECT time,action,subject,detail FROM audit ORDER BY id DESC LIMIT 30')]
    exports = all_records(db, 'export')
    return {'products': products, 'suppliers': suppliers, 'settings': settings, 'audit': logs,
            'exports': exports, 'mode': 'local-prototype', 'productionConnected': False,
            'csrfToken': TOKEN, 'version': research.VERSION, 'savedAt': stamp(), 'researchConnector': SORFTIME.status()}


def csv_cell(value):
    text = str(value)
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else text


def export_package(db, ids):
    if not isinstance(ids, list) or not ids or len(ids) > 100:
        raise ValueError('请选择 1–100 个已审核商品')
    if any(not isinstance(id, str) for id in ids):
        raise ValueError('商品标识格式不正确')
    ids = sorted(set(ids))
    settings = get(db, 'settings', 'main')
    products = [get(db, 'product', id) for id in ids]
    for p in products:
        a = analyze_product(db, p, settings, supplier_for(db, p))
        if not a['approvalValid']:
            raise ValueError(p['name'] + '：审核不存在、已失效或有阻断项')
    key = fingerprint({'ids': ids, 'products': products}, settings, None)
    exports = all_records(db, 'export')
    previous = next((x for x in exports if x['fingerprint'] == key), None)
    record = previous or {'id': str(uuid.uuid4()), 'time': stamp(), 'productIds': ids, 'count': len(ids), 'fingerprint': key, 'status': '内容包已导出 · 未上架'}
    if not previous:
        put(db, 'export', record['id'], record)
        audit(db, '导出内容包', str(len(ids)) + ' 个商品', '通用 CSV/JSON + 英文文案 + 生图提示词；不等于 Shopee 官方模板或真实发布')
    buff = io.BytesIO()
    with zipfile.ZipFile(buff, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('README.txt', 'Meeya MVP 内容工作包\n这不是 Shopee 官方批量模板。未连接 Shopee，未真实上架。\n示例数据不得用于真实刊登。正式上架须核实费用、素材、属性、类目、货源及官方模板。\n文案由事实模板生成，图片提示词未调用 AI。\n')
        out = io.StringIO(newline='')
        writer = csv.writer(out)
        writer.writerow(['id', 'name', 'english_title', 'price_php', 'supplier_sku', 'weight_g', 'is_demo', 'description'])
        for p in products:
            writer.writerow([csv_cell(x) for x in [p['id'], p['name'], p['content']['title'], p['price'], p.get('supplierSku', ''), p['weight'], p['demo'], p['content']['description']]])
            folder = re.sub(r'[^a-zA-Z0-9_-]', '_', p['id'])
            z.writestr(folder + '/listing.txt', p['content']['title'] + '\n\n' + p['content']['description'])
            z.writestr(folder + '/image-prompt.txt', p['content'].get('imagePrompt', ''))
        z.writestr('products.csv', '\ufeff' + out.getvalue())
        z.writestr('products.json', json.dumps(products, ensure_ascii=False, indent=2))
        z.writestr('fee-rules.json', json.dumps(settings['rules'], ensure_ascii=False, indent=2))
    return buff.getvalue(), record


class Handler(BaseHTTPRequestHandler):
    server_version = 'MeeyaMVP/0.2'

    def log_message(self, fmt, *args):
        # Avoid recording user-entered query strings or payloads.
        pass

    def send_bytes(self, body, content_type, status=200, extra=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data: blob: https://*.susercontent.com https://*.alicdn.com https://*.shopee.ph; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def json_response(self, value, status=200):
        self.send_bytes(json.dumps(value, ensure_ascii=False).encode(), 'application/json; charset=utf-8', status)

    def allowed_host(self):
        return self.headers.get('Host', '') in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}

    def reject_post(self, message):
        # Drain a bounded small body before closing, so Windows does not
        # discard the 403 response by resetting a socket with unread bytes.
        # Invalid sessions still execute no application action.
        try:
            length = int(self.headers.get('Content-Length', 0))
            if 0 < length <= 8192:
                self.connection.settimeout(2)
                self.rfile.read(length)
        except (ValueError, OSError):
            pass
        self.close_connection = True
        return self.json_response({'error': message}, 403)

    def do_GET(self):
        if not self.allowed_host():
            return self.json_response({'error': '仅支持本机访问'}, 403)
        path = urlparse(self.path).path
        try:
            if path == '/api/state':
                with LOCK, connect() as db:
                    return self.json_response(state(db))
            if path == '/api/health':
                return self.json_response({'ok': True, 'version': research.VERSION, 'storage': 'sqlite', 'productionConnected': False})
            if path == '/api/research/state':
                with LOCK, connect() as db:
                    return self.json_response(research.research_state(db, SORFTIME.status()))
            if path.startswith('/api/research/observation/'):
                with LOCK, connect() as db:
                    return self.json_response(research.observation_details(db, path.rsplit('/', 1)[-1]))
            if path.startswith('/api/research/snapshot/'):
                with LOCK, connect() as db:
                    snapshot = research.read(db, 'research_snapshot', path.rsplit('/', 1)[-1])
                return self.send_bytes(json.dumps(snapshot, ensure_ascii=False, indent=2).encode(), 'application/json; charset=utf-8', extra={'Content-Disposition': 'attachment; filename="research-evidence.json"'})
            if path.startswith('/api/research/export/'):
                with LOCK, connect() as db:
                    case = research.read(db, 'research_case', path.rsplit('/', 1)[-1])
                    observations = research.observations_with_conflicts(db)
                    draft = next((d for d in research.records(db, 'research_draft') if d['id'] == case['id']), None)
                    assessment = research.assessment_with_draft(case, research.read(db, 'settings', 'main'), observations, research.get_policy(db), draft)
                    result = {'case': case, 'draft': draft, 'assessment': assessment, 'exportedAt': stamp(), 'meaning': '候选研究记录；未通过校验的最新输入单独保留在 draft，不是上架包或采购指令'}
                return self.send_bytes(json.dumps(result, ensure_ascii=False, indent=2).encode(), 'application/json; charset=utf-8', extra={'Content-Disposition': 'attachment; filename="research-case.json"'})
            if path == '/api/backup':
                with LOCK, connect() as db:
                    values = [{'kind': k, 'id': id, 'payload': json.loads(p)} for k, id, p in db.execute('SELECT kind,id,payload FROM records')]
                    audit_rows = [dict(zip(['time', 'action', 'subject', 'detail'], r)) for r in db.execute('SELECT time,action,subject,detail FROM audit')]
                    raw = json.dumps({'schemaVersion': 1, 'exportedAt': stamp(), 'records': values, 'audit': audit_rows}, ensure_ascii=False, indent=2).encode()
                return self.send_bytes(raw, 'application/json; charset=utf-8', extra={'Content-Disposition': 'attachment; filename="meeya-backup.json"'})
            files = {'/selection-ui.js': ('selection-ui.js', 'text/javascript; charset=utf-8'), '/research-autosave.js': ('research-autosave.js', 'text/javascript; charset=utf-8'), '/research-browser.js': ('research-browser.js', 'text/javascript; charset=utf-8'), '/research-interactions.js': ('research-interactions.js', 'text/javascript; charset=utf-8'), '/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8'), '/research.js': ('research.js', 'text/javascript; charset=utf-8'), '/research.css': ('research.css', 'text/css; charset=utf-8'), '/favicon.svg': ('favicon.svg', 'image/svg+xml')}
            if path in files:
                file, ct = files[path]
                return self.send_bytes((ROOT / 'static' / file).read_bytes(), ct)
            if path.startswith('/assets/'):
                id = path.removeprefix('/assets/')
                if not re.fullmatch(r'[a-f0-9-]+', id):
                    raise ValueError('图片标识不正确')
                with connect() as db:
                    asset = get(db, 'asset', id)
                return self.send_bytes(base64.b64decode(asset['data']), asset['mime'])
            return self.json_response({'error': '页面不存在'}, 404)
        except ValueError as exc:
            self.json_response({'error': str(exc)}, 400)

    def do_POST(self):
        global SORFTIME
        if not self.allowed_host() or self.headers.get('X-MVP-Token') != TOKEN:
            return self.reject_post('会话已失效，请刷新页面')
        origin = self.headers.get('Origin')
        if origin and origin not in {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}:
            return self.reject_post('来源不允许')
        try:
            size = int(self.headers.get('Content-Length', 0))
            if size <= 0 or size > 8_000_000:
                raise ValueError('请求为空或超过 8MB')
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError('请求必须为 JSON 对象')
            path = urlparse(self.path).path
            if path == '/api/research/connect':
                key = body.get('key')
                if key is not None and (not isinstance(key, str) or not 1 <= len(key.strip()) <= 4096):
                    raise ValueError('密钥不能为空或过长')
                connector = SorftimeClient(key.strip()) if key else SORFTIME
                result = connector.connect()
                SORFTIME = connector
                return self.json_response(result)
            with LOCK, connect() as db:
                if path == '/api/research/policy':
                    policy = research.update_policy(db, body)
                    db.commit()
                    return self.json_response({'policy': policy})
                if path == '/api/research/query':
                    tool, args = body.get('tool'), body.get('args')
                    validate_query(tool, args)
                    if tool in MUTATING:
                        if body.get('confirmedExternalChange') is not True:
                            raise ValueError('关键词收藏变更需逐次明确确认，不会随普通调研自动执行')
                        request_id = body.get('requestId')
                        if not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9-]{8,100}', request_id):
                            raise ValueError('变更操作缺少唯一请求标识')
                        existing = next((j for j in research.records(db, 'research_job') if j.get('requestId') == request_id), None)
                        if existing:
                            if existing['tool'] != tool or existing['args'] != args:
                                raise ValueError('请求标识不能用于不同操作')
                            return self.json_response({'job': existing}, 202)
                    if not SORFTIME.status()['configured']:
                        raise ValueError('本机后端未连接 Sorftime，请先在调研工作台输入密钥并测试连接')
                    if RESEARCH_TASK_LOCK.locked():
                        raise ValueError('已有采集在执行，请稍后再发起，避免重复调用')
                    batch_id = body.get('batchId')
                    if batch_id:
                        research.read(db, 'research_batch', batch_id)
                    else:
                        batch_id = research.new_batch(db, str(body.get('label') or args.get('name') or args.get('search_name') or tool), 'backend_mcp')['id']
                    job = {'id': str(uuid.uuid4()), 'batchId': batch_id, 'tool': tool, 'args': args,
                           'createdAt': stamp(), 'status': 'queued', 'error': None}
                    if tool in MUTATING:
                        job.update(confirmedExternalChange=True, requestId=body['requestId'])
                    research.save(db, 'research_job', job)
                    db.commit()
                    threading.Thread(target=research_worker, args=(job['id'], SORFTIME), daemon=True).start()
                    return self.json_response({'job': job}, 202)
                if path == '/api/research/import':
                    batch = research.import_bundle(db, body, 'manual_import')
                    db.commit()
                    return self.json_response({'batch': batch})
                if path == '/api/research/cases':
                    case = research.new_case(db, body.get('observationId'))
                    db.commit()
                    return self.json_response({'case': case})
                if path == '/api/research/cases/save':
                    case = research.update_case(db, body)
                    db.commit()
                    return self.json_response({'case': case})
                if path == '/api/research/cases/autosave':
                    result = research.autosave_case(db, body)
                    db.commit()
                    return self.json_response(result, 409 if result['conflict'] else 200)
                if path == '/api/pricing':
                    p = body['product']
                    settings = get(db, 'settings', 'main')
                    clean_product(p)
                    a = analyze_product(db, p, settings, supplier_for(db, p))
                    scenarios = []
                    if a['calculation']:
                        for label, changes in [('采购 +10%', 'purchase'), ('SLS +15%', 'sls'), ('PHP 贬值 5%', 'fx'), ('高档分期', 'payment')]:
                            pp, rules = deepcopy(p), deepcopy(settings['rules'])
                            if changes in ('purchase', 'sls'):
                                pp['costs'][changes] = money(num(pp['costs'][changes]) * (D('1.10') if changes == 'purchase' else D('1.15')))
                            elif changes == 'fx':
                                rules['fx'] = str(num(rules['fx']) * D('0.95'))
                            else:
                                pp['payment'] = 'installment'
                            scenarios.append({'label': label, **evaluate(pp, rules)})
                    return self.json_response({'analysis': a, 'scenarios': scenarios})
                if path == '/api/products':
                    p = clean_product(body)
                    p.update({'id': str(uuid.uuid4()), 'revision': 1, 'demo': False, 'approval': None, 'createdAt': stamp()})
                    p.pop('analysis', None)
                    put(db, 'product', p['id'], p)
                    audit(db, '新增候选', p['name'], '手动录入')
                    db.commit()
                    return self.json_response({'product': p})
                if path.startswith('/api/products/'):
                    parts = path.split('/')
                    id, action = parts[3], parts[4] if len(parts) > 4 else 'save'
                    old = get(db, 'product', id)
                    check_revision(old, body)
                    settings = get(db, 'settings', 'main')
                    if action == 'save':
                        p = clean_product(body)
                        # Client cannot manufacture approvals, demo flags or IDs.
                        p.update({'id': id, 'demo': old['demo'], 'approval': old.get('approval'), 'createdAt': old['createdAt'], 'revision': old['revision'] + 1})
                        if p.get('facts') != old.get('facts') or p.get('englishName') != old.get('englishName'):
                            p['content'] = None
                        p.pop('analysis', None)
                        put(db, 'product', id, p)
                        audit(db, '更新商品', p['name'], '已保存新版本；旧审核自动失效')
                    elif action == 'content':
                        old['content'] = generate_content(old)
                        old['revision'] += 1
                        put(db, 'product', id, old)
                        audit(db, '整理英文文案', old['name'], '事实模板 · 未调用 AI')
                    elif action == 'approve':
                        supplier = supplier_for(db, old)
                        analysis = analyze_product(db, old, settings, supplier)
                        if not analysis['canApprove']:
                            raise ValueError('不能审核：' + '；'.join(analysis['blockers'] or ['请先生成文案']))
                        old['approval'] = {'fingerprint': fingerprint(old, settings, supplier), 'time': stamp(), 'mode': '示例审核' if old['demo'] else '本地内容审核'}
                        if analysis.get('selectionFingerprint'):
                            old['approval']['selectionFingerprint'] = analysis['selectionFingerprint']
                        put(db, 'product', id, old)
                        audit(db, '内容审核', old['name'], '仅批准当前版本内容包；未发布店铺')
                    else:
                        raise ValueError('不支持此操作')
                    db.commit()
                    return self.json_response({'ok': True})
                if path == '/api/settings':
                    old = get(db, 'settings', 'main')
                    check_revision(old, body)
                    validate_settings(body)
                    body['revision'] = old['revision'] + 1
                    body['pools'] = old['pools']
                    body['rules']['version'] = f"LOCAL-{body['revision']}"
                    put(db, 'settings', 'main', body)
                    audit(db, '更新规则/资金参数', body['rules']['version'], '相关商品旧审核自动失效')
                    db.commit()
                    return self.json_response({'ok': True})
                if path == '/api/suppliers':
                    s = body
                    if not isinstance(s.get('name'), str) or not s['name'].strip():
                        raise ValueError('供应商名称不能为空')
                    for k in ['name', 'category', 'note']:
                        if not isinstance(s.get(k, ''), str) or len(s.get(k, '')) > 5000:
                            raise ValueError('供应商资料格式不正确或过长')
                    for k in ['stock', 'leadDays']:
                        v = num(s.get(k), k, D('0'), D('100000'))
                        if v != v.to_integral():
                            raise ValueError('库存和备货天数必须为整数')
                    for k in ['verified', 'dropship']:
                        if type(s.get(k)) is not bool:
                            raise ValueError('供应商核实状态格式不正确')
                    if s.get('id'):
                        old = get(db, 'supplier', s['id'])
                        check_revision(old, s)
                        s['revision'] += 1
                        s['demo'] = old.get('demo', False)
                    else:
                        s.update({'id': str(uuid.uuid4()), 'revision': 1, 'demo': False})
                    put(db, 'supplier', s['id'], s)
                    audit(db, '更新供应商', s['name'], '关联商品审核重新检查')
                    db.commit()
                    return self.json_response({'ok': True})
                if path == '/api/assets':
                    match = re.fullmatch(r'data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)', body.get('dataUrl', ''))
                    if not match or body.get('rights') is not True:
                        raise ValueError('请选择 PNG/JPEG/WebP 并确认图片使用权')
                    raw = base64.b64decode(match[2], validate=True)
                    if len(raw) > 4_000_000:
                        raise ValueError('图片不得超过 4MB')
                    valid_header = {
                        'image/png': raw.startswith(b'\x89PNG\r\n\x1a\n'),
                        'image/jpeg': raw.startswith(b'\xff\xd8\xff'),
                        'image/webp': raw.startswith(b'RIFF') and raw[8:12] == b'WEBP',
                    }
                    if not valid_header[match[1]]:
                        raise ValueError('图片文件头不正确')
                    p = get(db, 'product', body['productId'])
                    check_revision(p, body)
                    id = str(uuid.uuid4())
                    put(db, 'asset', id, {'mime': match[1], 'data': match[2], 'productId': p['id'], 'rights': True, 'time': stamp()})
                    p['imageUrl'] = '/assets/' + id
                    p['revision'] += 1
                    put(db, 'product', p['id'], p)
                    audit(db, '上传商品原图', p['name'], '仅本机保存')
                    db.commit()
                    return self.json_response({'ok': True})
                if path == '/api/export':
                    raw, record = export_package(db, body.get('ids'))
                    db.commit()
                    return self.send_bytes(raw, 'application/zip', extra={'Content-Disposition': 'attachment; filename="meeya-listing-package.zip"', 'X-Export-Id': record['id']})
                return self.json_response({'error': '接口不存在'}, 404)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            self.json_response({'error': str(exc)}, 400)
        except Exception:
            self.json_response({'error': '保存失败，请稍后重试；原数据仍保留'}, 500)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    init_db()
    recover_research_jobs()
    httpd = ThreadingHTTPServer(('127.0.0.1', args.port), Handler, bind_and_activate=False)
    httpd.allow_reuse_address = False
    if os.name == 'nt':
        httpd.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    httpd.server_bind()
    httpd.server_activate()
    print(f'Meeya MVP ready at http://127.0.0.1:{args.port}', flush=True)
    print('Local SQLite storage. Research connector available; configure in the local page. Store publishing / AI generation remain disconnected.', flush=True)
    httpd.serve_forever()


if __name__ == '__main__':
    main()
