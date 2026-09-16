"""Sorftime MCP adapter; research reads and explicitly confirmed keyword writes."""
import json
import os
import re
import threading
import math
import ipaddress
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

ENDPOINT = 'https://mcp.sorftime.com'
CATALOG = json.loads(Path(__file__).with_name('sorftime_catalog.json').read_text(encoding='utf-8'))['tools']
SPECS = {t['name']: t for t in CATALOG}
ALLOWED = {name: set(t['inputSchema']['properties']) for name, t in SPECS.items()}
MUTATING = {name for name, t in SPECS.items() if t['mutating']}


class ConnectorError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ConnectorError('REDIRECT_BLOCKED', '连接发生重定向，已停止，未转发凭证')


def validate_query(tool, args):
    if tool not in ALLOWED or not isinstance(args, dict) or set(args) - ALLOWED[tool]:
        raise ValueError('不支持的调研工具或参数')
    if tool.startswith('shopee_') and args.get('site') != 'PH':
        raise ValueError('本模块仅查询菲律宾 PH 站；不能混用其他市场')
    spec = SPECS[tool]['inputSchema']
    if set(spec['required']) - set(args):
        raise ValueError('缺少接口必填参数：' + ', '.join(sorted(set(spec['required']) - set(args))))
    for key, value in args.items():
        field = spec['properties'][key]
        if field['type'] == 'string' and (not isinstance(value, str) or not value.strip() or len(value) > 2000):
            raise ValueError(key + ' 必须为非空文本且不超过 2000 字')
        if field['type'] == 'number' and (type(value) not in (float, int) or not math.isfinite(value) or value < 0 or value > 1e12):
            raise ValueError(key + ' 必须为有效非负数值')
        if field.get('enum') and value not in field['enum']:
            raise ValueError(key + ' 不是接口支持的选项')
        if key.endswith(('_min', '_max')) and ('date' in key):
            from datetime import date
            try:
                date.fromisoformat(value)
            except (TypeError, ValueError):
                raise ValueError(key + ' 日期格式必须为 YYYY-MM-DD')
        if key.endswith('_min') and key[:-4] + '_max' in args and value > args[key[:-4] + '_max']:
            raise ValueError(key + ' 下限不能大于上限')
        if key.startswith(('star_range_', 'service_score_')) and value > 5:
            raise ValueError(key + ' 不得超过 5 分')
        if key.startswith('repurchase_rate_') and value > 100:
            raise ValueError('复购率不得超过 100%')
        if any(k in key for k in ('count_', 'volume_', 'sale_max', 'sale_min', 'rank_')) and isinstance(value, (int, float)) and int(value) != value:
            raise ValueError(key + ' 必须为整数')
    for key, options in {'shop_location': (1, 2), 'shop_type': (1, 2, 3), 'supplier_member_type': (1, 2), 'supplier_type': (1, 2)}.items():
        if key in args and args[key] not in options:
            raise ValueError(key + ' 不是文档支持的选项')
    if 'rights' in args and not re.fullmatch(r'[123](,[123])*', args['rights']):
        raise ValueError('1688 权益只能是 1、2、3 的逗号组合')
    if 'image_url' in args:
        u = urlsplit(args['image_url'])
        host = u.hostname or ''
        try:
            ipaddress.ip_address(host)
            numeric_host = True
        except ValueError:
            numeric_host = False
        if u.scheme != 'https' or not host or numeric_host or '.' not in host or host.endswith(('.localhost', '.local', '.internal')) or u.username or u.password or u.port not in (None, 443):
            raise ValueError('以图找货只接受公开 HTTPS 图片地址；不能使用本机、内网或含凭证地址')
    if 'shop_id' in args and not re.fullmatch(r'\d{1,30}', args['shop_id']):
        raise ValueError('店铺 ID 必须为数字标识')
    for key in ('name', 'search_name'):
        if key in args and (not isinstance(args[key], str) or not args[key].strip() or len(args[key]) > 200):
            raise ValueError('关键词不能为空且不得超过 200 字')
    if tool.endswith('search_from_name') and not args.get('name'):
        raise ValueError('缺少关键词')
    if tool == 'ali1688_similar_product' and not args.get('search_name'):
        raise ValueError('缺少 1688 中文搜索词')
    if any(x in tool for x in ('product_request', 'product_variations', 'product_trend')):
        if not re.fullmatch(r'\d{1,30}', str(args.get('product_id', ''))):
            raise ValueError('商品 ID 必须来自搜索结果中的数字标识')
    if 'page' in args and (type(args['page']) is not int or not 1 <= args['page'] <= 10000):
        raise ValueError('接口页码必须为 1–10000 的整数；显示分页不会调用接口')
    if 'node_id' in args or tool == 'shopee_category_request':
        if not re.fullmatch(r'\d{1,30}', str(args.get('node_id', ''))):
            raise ValueError('类目 ID 必须是来源中的数字标识')
    if 'query_date' in args:
        from datetime import date
        try:
            if date.fromisoformat(args['query_date']) > date.today():
                raise ValueError()
        except (TypeError, ValueError):
            raise ValueError('类目查询日期必须为非未来的 YYYY-MM-DD')
    if tool == 'shopee_product_trend':
        from datetime import date
        try:
            start, end = date.fromisoformat(args['query_start']), date.fromisoformat(args['query_end'])
            if start > end or (end - start).days > 365 or end > date.today():
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ValueError('趋势查询必须明确起止日期，跨度不超过 365 天且不能查询未来')
    return args


def unpack_response(result):
    if not isinstance(result, dict) or result.get('isError'):
        raise ConnectorError('PROVIDER_ERROR', '数据服务返回错误，未把错误当成空数据')
    structured = result.get('structuredContent')
    if isinstance(structured, dict) and 'data' in structured:
        return structured
    for item in result.get('content', []):
        if not isinstance(item, dict):
            continue
        if item.get('type') == 'text':
            try:
                # Financial fields retain decimal text; original MCP text is
                # stored independently and never reformatted as evidence.
                parsed = json.loads(item['text'], parse_float=str)
                if isinstance(parsed, dict) and 'data' in parsed:
                    return parsed
            except (ValueError, TypeError):
                continue
    raise ConnectorError('SCHEMA_CHANGED', '接口响应缺少已知 data 结构，已隔离，需检查字段契约')


class SorftimeClient:
    def __init__(self, key=None):
        self.key = key if key is not None else os.environ.get('SORFTIME_MCP_KEY', '')
        self.session = None
        self.protocol_version = '2025-03-26'
        self.request_id = 0
        self.tools = {}
        self.lock = threading.Lock()
        self.last_status = 'not_configured' if not self.key else 'not_tested'
        self.opener = build_opener(NoRedirect())

    def status(self):
        return {'configured': bool(self.key), 'status': self.last_status,
                'endpointHost': 'mcp.sorftime.com', 'transport': 'streamable-http',
                'readOnly': not any(t in MUTATING for t in self.tools), 'supportedTools': sorted(self.tools),
                'writeTools': sorted(t for t in self.tools if t in MUTATING),
                'catalog': [{**t, 'available': t['name'] in self.tools,
                             'runtimeInputSchema': self.tools.get(t['name'], {}).get('inputSchema')} for t in CATALOG],
                'credentialLocation': '仅当前服务进程内存；不在页面、数据库或日志中保存'}

    def rpc(self, method, params=None, notification=False):
        if not self.key:
            raise ConnectorError('NOT_CONFIGURED', '本机后端尚未配置 Sorftime 密钥；对话 MCP 连接不会自动共享给网页')
        self.request_id += 1
        rid = self.request_id
        message = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            message['params'] = params
        if not notification:
            message['id'] = rid
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
                   'MCP-Protocol-Version': self.protocol_version}
        if self.session:
            headers['Mcp-Session-Id'] = self.session
        request = Request(ENDPOINT + '?' + urlencode({'key': self.key}), data=json.dumps(message).encode(), headers=headers)
        try:
            with self.opener.open(request, timeout=30) as response:
                if response.headers.get('Mcp-Session-Id'):
                    self.session = response.headers['Mcp-Session-Id']
                if notification and response.status in (200, 202, 204):
                    return None
                content_type = response.headers.get('Content-Type', '')
                if 'text/event-stream' in content_type:
                    total, parts = 0, []
                    for raw in response:
                        total += len(raw)
                        if total > 12_000_000:
                            raise ConnectorError('RESPONSE_TOO_LARGE', '响应超过安全大小限制')
                        line = raw.decode('utf-8').rstrip('\r\n')
                        if line.startswith('data:'):
                            parts.append(line[5:].lstrip())
                        elif not line and parts:
                            obj = json.loads('\n'.join(parts))
                            parts = []
                            if isinstance(obj, dict) and obj.get('id') == rid:
                                return self.rpc_result(obj)
                    raise ConnectorError('INCOMPLETE_STREAM', '数据流未返回完整结果；没有自动重试以避免重复计费')
                if 'application/json' not in content_type:
                    raise ConnectorError('UNSUPPORTED_TRANSPORT', '响应不是 JSON 或 SSE，不能继续解析')
                raw = response.read(12_000_001)
                if len(raw) > 12_000_000:
                    raise ConnectorError('RESPONSE_TOO_LARGE', '响应超过安全大小限制')
                obj = json.loads(raw)
                if not isinstance(obj, dict) or obj.get('id') != rid:
                    raise ConnectorError('RPC_ID_MISMATCH', '响应标识不匹配，未接收数据')
                return self.rpc_result(obj)
        except HTTPError as e:
            self.last_status = 'auth_failed' if e.code in (401, 403) else 'rate_limited' if e.code == 429 else 'error'
            code = 'AUTH_REQUIRED' if e.code in (401, 403) else 'RATE_LIMITED' if e.code == 429 else 'HTTP_ERROR'
            if e.code == 404:
                self.session, self.tools = None, {}
            raise ConnectorError(code, f'Sorftime 返回 HTTP {e.code}；未重试、未使用旧值冒充新数据') from None
        except (URLError, TimeoutError, OSError):
            self.last_status = 'network_error'
            raise ConnectorError('NETWORK_ERROR', 'Sorftime 网络请求失败或超时；未自动重试，可能已消耗调用额度') from None
        except (json.JSONDecodeError, UnicodeError):
            raise ConnectorError('INVALID_JSON', '响应无法解析，未生成数据') from None

    @staticmethod
    def rpc_result(obj):
        if 'error' in obj:
            raise ConnectorError('RPC_ERROR', 'Sorftime 返回协议错误；敏感原始错误不回显')
        if 'result' not in obj:
            raise ConnectorError('RPC_ERROR', 'Sorftime 响应缺少 result')
        return obj['result']

    def connect(self):
        with self.lock:
            self._connect()
        return self.status()

    def _connect(self):
        self.session, self.tools = None, {}
        init = self.rpc('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
                                    'clientInfo': {'name': 'meeya-research', 'version': '0.3.0'}})
        if not isinstance(init, dict) or init.get('protocolVersion') not in ('2025-03-26', '2025-06-18', '2025-11-25'):
            raise ConnectorError('PROTOCOL_UNSUPPORTED', '服务协商的 MCP 版本不在已支持范围')
        self.protocol_version = init['protocolVersion']
        self.rpc('notifications/initialized', notification=True)
        discovered, cursor = [], None
        for _ in range(20):
            page = self.rpc('tools/list', {'cursor': cursor} if cursor else {})
            discovered.extend(page.get('tools', []))
            cursor = page.get('nextCursor')
            if not cursor:
                break
        else:
            raise ConnectorError('TOOL_PAGE_LIMIT', '工具目录分页异常')
        canonical = lambda value: re.sub(r'[^a-z0-9]', '', value.lower())
        for allowed in ALLOWED:
            matches = [t for t in discovered if canonical(t.get('name', '')) == canonical(allowed)]
            if len(matches) == 1:
                self.tools[allowed] = matches[0]
        if not self.tools:
            self.last_status = 'unsupported'
            raise ConnectorError('UNSUPPORTED', '当前账号未发现已适配的 Shopee/1688 只读工具，不能宣称数据已接通')
        self.last_status = 'connected'

    def call(self, tool, args, confirmed=False):
        validate_query(tool, args)
        if tool in MUTATING and confirmed is not True:
            raise ConnectorError('CONFIRMATION_REQUIRED', '此接口会修改 Sorftime 关键词收藏，必须对本次操作明确确认')
        with self.lock:
            if not self.tools:
                self._connect()
            if tool not in self.tools:
                raise ConnectorError('UNSUPPORTED', '当前账号工具目录没有这项能力；不会虚构接口成功')
            spec = self.tools[tool]
            properties = spec.get('inputSchema', {}).get('properties', {})
            if set(args) - set(properties) or set(spec.get('inputSchema', {}).get('required', [])) - set(args):
                raise ConnectorError('SCHEMA_CHANGED', '实际工具参数已变化，需要更新适配器')
            result = self.rpc('tools/call', {'name': spec['name'], 'arguments': args})
            self.last_status = 'connected'
            return result
