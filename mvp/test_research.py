"""Synthetic, isolated regression fixtures. Never supplier or market evidence."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import io
import json
import sqlite3
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import engine
import research as r
import sorftime as s
from seed import default_settings
import test_mvp
import server


def proof(**kwargs):
    return {'source': 'SYNTHETIC TEST ONLY', 'validUntil': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(), **kwargs}


def event(tool='shopee_product_search_from_name', data=None, doc=None, args=None):
    raw = data if data is not None else [dict(product_id='123', shop_id='456', title='Synthetic organizer', price='69', sales_count=12, his_sales_count=900, sales_calc_time='2026-08-24', shop_loc_type='本土店')]
    if args is None:
        args = {'site': 'PH', 'name': 'synthetic'} if tool == 'shopee_product_search_from_name' else {'product_id': '888'}
    return {'tool': tool, 'args': args, 'fetchedAt': engine.stamp(), 'response': {'content': [{'type': 'text', 'text': json.dumps({'doc': doc if doc is not None else {'price': 'Price PHP', 'sales_count': 'Monthly sales volume'}, 'data': raw})}]}}


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE records(kind TEXT,id TEXT,payload TEXT,PRIMARY KEY(kind,id))')
        self.db.execute('CREATE TABLE audit(time TEXT,action TEXT,subject TEXT,detail TEXT)')
        self.settings = default_settings()
        r.save(self.db, 'settings', {'id': 'main', **self.settings})
        self.batch = r.new_batch(self.db, 'SYNTHETIC TEST ONLY', 'test')

    def tearDown(self):
        self.db.close()

    def add(self, e=None):
        sid = r.ingest(self.db, e or event(), self.batch['id'], 'test')
        return [x for x in r.records(self.db, 'research_observation') if x['snapshotId'] == sid]

    def ready(self):
        market = self.add()[0]
        offer = self.add(event('ali1688_product_request', {'product_id': '888', 'title': 'Synthetic offer', 'price': '3.3', 'min_order_quantity': 1, 'stock_count': 200, 'is_drop_shipping': True}, {'price': 'CNY'}))[0]
        sku = self.add(event('ali1688_product_variations', [{'sku_id': '999', 'sku_name': 'Synthetic SKU', 'offer_price': '4.5'}], {'offer_price': 'CNY'}))[0]
        c = r.new_case(self.db, market['id'])
        c.update(offerObservationId=offer['id'], skuObservationId=sku['id'], specification='synthetic exact specification', mappingEvidence='synthetic evidence', mappingConfirmed=True,
                 pricePHP='500', buyerShippingPHP='0', marketMaxPHP='600', marketEvidence=proof(),
                 quote=proof(unitPrice='4.5', unitsPerSale='1', purchaseQuantity='1', moq='1', stock='200', leadDays='1', dropship='yes', confirmed=True),
                 package=proof(weightG='300', length='10', width='20', height='5'),
                 checks={k: 'yes' for k in c['checks']}, checksEvidence=proof(),
                 demandEvidence=proof(value='20', windowStart='2026-08-01', windowEnd='2026-08-31'),
                 cashEvidence=proof(requestedUnits='5'), costs={k: proof(amount='1') for k in engine.COST_FIELDS if k != 'purchase'})
        for i in range(10):
            o = self.add(event(data=[{'product_id': str(200+i), 'title': 'Synthetic comparison', 'shop_id': str(456+i), 'price': '500', 'shop_loc_type': '本土店' if i < 5 else '跨境店'}]))[0]
            end = datetime.now(timezone.utc).date() - timedelta(days=1)
            c['comparisons'].append(proof(observationId=o['id'], sameSpec='yes', arrivalPricePHP=str(500+i), specEvidence='synthetic exact variant', observedAt=engine.stamp(), sales30d='30', salesWindowStart=(end-timedelta(days=29)).isoformat(), salesWindowEnd=end.isoformat(), salesScope='same_spec_30d'))
        c['quote']['observedAt'] = engine.stamp()
        c['selectionEvidence'] = r.selection.empty_evidence()
        for key, fields in r.selection.FIELDS.items():
            c['selectionEvidence'][key].update(proof(observedAt=engine.stamp()))
            for field, _, typ in fields:
                c['selectionEvidence'][key][field] = 'yes' if typ == 'tri' else 'SYNTHETIC TEST' if typ == 'text' else '3'
        c['selectionEvidence']['logistics'].update(billableWeightG='300', leadHours='24', domesticHours='24', warehouseHours='24', deadlineHours='240')
        c['selectionEvidence']['cash'].update(dailyUnits='1', monthlyLossCNY='0')
        self.settings['rules'].update(verified=True, fx='0.1', commission='10', platformShipping='5', shippingCap='100', transaction='3', installment='8', growth='2', marketing='0', receiving='0', orderFee='5', targetMargin='20', targetProfit='10')
        self.settings.update(domesticDays=1, warehouseDays=1, shipDeadlineDays=10, bankBalance='20000', committed='0', reserve='5000')
        c['rulesEvidence'] = proof(version=self.settings['rules']['version'])
        return c

    def assess(self, c):
        return r.assess(c, self.settings, r.observations_with_conflicts(self.db), r.get_policy(self.db))

    def test_currency_conflict_does_not_infer_php(self):
        row = self.add(event(doc={'price': 'Price THB'}))[0]
        self.assertIsNone(row['currency'])
        self.assertIsNone(row['price'])
        self.assertEqual(row['rawPrice'], '69')
        self.assertIn('CURRENCY_CONFLICT', [q['code'] for q in row['quality']])

    def test_explicit_php_does_not_override_conflicting_thb_doc(self):
        row = self.add(event(data=[{'product_id': '123', 'price': '69', 'currency': 'PHP'}], doc={'price': 'THB'}))[0]
        self.assertIsNone(row['price'])

    def test_zero_and_sentinel_are_not_positive_price_or_known_sales(self):
        row = self.add(event(data=[{'product_id': '123', 'price': '0', 'sales_count': -1, 'his_sales_count': 900, 'sales_calc_time': '1970-01-01'}]))[0]
        self.assertIsNone(row['price'])
        self.assertIsNone(row['monthlySales'])
        self.assertIsNone(row['providerUpdatedAt'])
        self.assertEqual(row['cumulativeSales'], 900)

    def test_time_validation_and_timezone_normalization(self):
        self.assertEqual(r.valid_time('2026-01-01T08:00:00+08:00'), '2026-01-01T00:00:00+00:00')
        for value in ('1970-01-01', '2999-01-01', '2026-01-01T00:00:00', None, 0):
            self.assertIsNone(r.valid_time(value))
        self.assertFalse(r.current_evidence(proof(source={'fake': True})))

    def test_dispatch_city_moq_and_zero_dimensions(self):
        row = self.add(event('ali1688_product_request', {'product_id': '888', 'price': '3.3', 'shipping_time': '金华市', 'is_drop_shipping': True, 'min_order_quantity': 2}, {'price': 'CNY'}))[0]
        self.assertIsNone(row['dispatchHoursReported'])
        self.assertIn('MOQ_DROPSHIP_CONFLICT', [q['code'] for q in row['quality']])
        sku = self.add(event('ali1688_product_variations', [{'sku_id': '999', 'offer_price': '4.5', 'length': 0, 'width': 0, 'height': 0, 'weight': '0.3'}], {'offer_price': 'CNY', 'weight': 'kg', 'length': 'cm', 'width': 'cm', 'height': 'cm'}))[0]
        self.assertEqual(sku['package']['weightG'], '300.0')
        self.assertIsNone(sku['package']['length'])
        self.assertIsNone(sku['verifiedPurchaseCost'])

    def test_raw_snapshot_immutable_and_duplicate_ingest_idempotent(self):
        e = event()
        first = self.add(e)[0]
        self.add(e)
        self.assertEqual(len(r.records(self.db, 'research_observation')), 1)
        snap = r.read(self.db, 'research_snapshot', first['snapshotId'])
        self.assertEqual(snap['response'], e['response'])
        changed = deepcopy(snap)
        changed['response'] = 'tampered'
        r.save(self.db, 'research_snapshot', changed, immutable=True)
        self.assertEqual(r.read(self.db, 'research_snapshot', first['snapshotId'])['response'], e['response'])

    def test_conflicting_observations_retained(self):
        self.add()
        self.add(event('shopee_product_request', {'product_id': '123', 'sales_count': -1, 'price': '69'}, {'price': 'PHP'}, {'site': 'PH', 'product_id': '123'}))
        obs = r.observations_with_conflicts(self.db)
        self.assertEqual(len(obs), 2)
        self.assertEqual(len(r.latest_unique(obs)), 1)
        self.assertTrue(all(any(q['code'] == 'SALES_OBSERVATIONS_DIFFER' for q in o['quality']) for o in obs))

    def test_schema_change_and_provider_error_quarantined(self):
        for response in ({'content': [{'type': 'text', 'text': 'unknown structure'}]}, {'isError': True, 'content': []}):
            e = event()
            e['response'] = response
            self.add(e)
        self.assertEqual(len(r.records(self.db, 'research_snapshot')), 2)
        self.assertEqual(len(r.records(self.db, 'research_observation')), 0)
        self.assertEqual(len(r.read(self.db, 'research_batch', self.batch['id'])['notes']), 2)

    def test_bundle_import_idempotent_and_manual_origin(self):
        bundle = {'events': [event()], 'transport': 'backend_mcp'}
        a, b = r.import_bundle(self.db, bundle), r.import_bundle(self.db, bundle)
        self.assertEqual(a['id'], b['id'])
        self.assertEqual(a['transport'], 'manual_import')

    def test_empty_case_never_copies_demo_costs_or_passes(self):
        row = self.add()[0]
        c = r.new_case(self.db, row['id'])
        self.assertEqual(c['id'], r.new_case(self.db, row['id'])['id'])
        self.assertEqual(c['pricePHP'], '')
        self.assertTrue(all(v['amount'] == '' for v in c['costs'].values()))
        a = self.assess(c)
        self.assertIsNone(a['calculation'])
        self.assertFalse(a['canPublish'])
        self.assertEqual(a['state'], 'needs_evidence')

    def test_synthetic_complete_case_and_exact_ledger(self):
        c = self.ready()
        a = self.assess(c)
        self.assertEqual(a['state'], 'eligible_for_review', a)
        self.assertFalse(a['canPublish'])
        self.assertFalse(a['canPurchase'])
        self.assertEqual(a['calculation']['totalCost'], '23.00')
        self.assertEqual(a['calculation']['profit'], '27.00')
        self.assertEqual(sum(D(l['cny']) for l in a['calculation']['lines']), D('23'))
        self.assertEqual(a['maxPurchasePerSaleCNY'], '21.50')
        self.assertEqual(len(a['scenarios']), 6)
        self.assertEqual(a['comparison']['groups']['local']['count'], 5)
        self.assertEqual(a['comparison']['groups']['cross_border']['median'], '507.00')
        self.assertTrue(any('展示价' in w for w in a['warnings']))

    def test_each_cost_missing_or_expired_hides_profit(self):
        original = self.ready()
        for key in original['costs']:
            for field, value in [('amount', ''), ('source', ''), ('validUntil', '2020-01-01T00:00:00Z')]:
                c = deepcopy(original)
                c['costs'][key][field] = value
                self.assertIsNone(self.assess(c)['calculation'], (key, field))

    def test_unverified_or_changed_rule_version_hides_profit(self):
        c = self.ready()
        c['rulesEvidence']['version'] = 'WRONG'
        self.assertIsNone(self.assess(c)['calculation'])
        c['rulesEvidence']['version'] = self.settings['rules']['version']
        self.settings['rules']['verified'] = False
        self.assertIsNone(self.assess(c)['calculation'])

    def test_invalid_sku_mapping_hides_profit(self):
        c = self.ready()
        c['offerObservationId'] = ''
        self.assertIsNone(self.assess(c)['calculation'])

    def test_no_quote_or_missing_quantity_hides_profit(self):
        c = self.ready()
        c['quote']['purchaseQuantity'] = ''
        self.assertIsNone(self.assess(c)['calculation'])
        c['quote']['purchaseQuantity'] = '1'
        c['quote']['confirmed'] = False
        self.assertIsNone(self.assess(c)['calculation'])

    def test_moq_and_stock_fail(self):
        c = self.ready()
        c['quote']['moq'] = '2'
        a = self.assess(c)
        self.assertEqual(a['state'], 'rejected')
        self.assertIsNone(a['calculation'])
        c['quote']['moq'] = '1'
        c['quote']['stock'] = '0'
        self.assertEqual(self.assess(c)['state'], 'rejected')

    def test_package_and_home_category_gate(self):
        c = self.ready()
        c['package']['height'] = '0'
        self.assertEqual(self.assess(c)['state'], 'needs_evidence')
        c['checks']['homeCategory'] = 'no'
        self.assertEqual(self.assess(c)['state'], 'rejected')
        c['checks']['homeCategory'] = 'yes'
        c['checks']['simpleCertification'] = 'no'
        self.assertEqual(self.assess(c)['state'], 'rejected')

    def test_comparison_insufficient_or_expired_does_not_pass(self):
        c = self.ready()
        c['comparisons'][0]['validUntil'] = '2020-01-01T00:00:00Z'
        a = self.assess(c)
        self.assertEqual(a['comparison']['validCount'], 9)
        self.assertEqual(a['state'], 'needs_evidence')

    def test_demand_not_cumulative_and_window_required(self):
        c = self.ready()
        c['comparisons'][0]['salesWindowEnd'] = ''
        self.assertEqual(self.assess(c)['state'], 'needs_evidence')
        c = self.ready()
        for row in c['comparisons']:
            row['sales30d'] = '0'
        self.assertEqual(self.assess(c)['state'], 'rejected')

    def test_policy_price_limit_edit_recomputes_decision(self):
        c = self.ready()
        initial = self.assess(c)
        self.assertEqual(r.get_policy(self.db)['maxSellingPricePHP'], '1000')
        r.update_policy(self.db, {'revision': 1, 'maxSellingPricePHP': '400'})
        revised = self.assess(c)
        self.assertEqual(revised['state'], 'rejected')
        self.assertNotEqual(initial['assessmentFingerprint'], revised['assessmentFingerprint'])
        with self.assertRaises(ValueError):
            r.update_policy(self.db, {'revision': 1, 'maxSellingPricePHP': '300'})

    def test_cash_accounts_for_actual_lot(self):
        c = self.ready()
        c['quote'].update(moq='200', purchaseQuantity='200')
        self.settings['bankBalance'] = '5200'
        a = self.assess(c)
        self.assertEqual(a['cash']['requiredConservative'], '992.50')
        self.assertEqual(a['state'], 'rejected')

    def test_requested_units_cannot_exceed_confirmed_stock(self):
        c = self.ready()
        c['quote']['stock'] = '2'
        self.assertEqual(self.assess(c)['state'], 'rejected')

    def test_unknown_package_unit_not_converted(self):
        sku = self.add(event('ali1688_product_variations', [{'sku_id': '999', 'offer_price': '4.5', 'weight': '300'}], {'offer_price': 'CNY', 'weight': 'grams'}))[0]
        self.assertIsNone(sku['package']['weightG'])

    def test_expired_quote_does_not_compute(self):
        c = self.ready()
        c['quote']['validUntil'] = '2020-01-01T00:00:00Z'
        self.assertIsNone(self.assess(c)['calculation'])

    def test_oversized_cost_result_does_not_break_state(self):
        c = self.ready()
        c['quote'].update(unitPrice='10000000', unitsPerSale='2', purchaseQuantity='2')
        a = self.assess(c)
        self.assertIsNone(a['calculation'])
        self.assertTrue(any(n['code'] == 'CALCULATION_RANGE' for n in a['needs']))

    def test_pressure_scenario_out_of_range_is_explicit(self):
        c = self.ready()
        self.settings['rules']['fx'] = '0.000001'
        a = self.assess(c)
        self.assertTrue(any(s.get('error') for s in a['scenarios']))

    def test_revision_and_nonfinite_or_malformed_input_rejected(self):
        c = self.ready()
        saved = r.update_case(self.db, c)
        with self.assertRaises(ValueError):
            r.update_case(self.db, c)
        for value in ['NaN', '-1', True]:
            bad = deepcopy(saved)
            bad['quote']['unitPrice'] = value
            with self.assertRaises(ValueError):
                r.update_case(self.db, bad)
        saved['quote']['source'] = {'fabricated': True}
        with self.assertRaises(ValueError):
            r.update_case(self.db, saved)

    def test_comparison_duplicate_identity_rejected(self):
        c = self.ready()
        c['comparisons'].append(deepcopy(c['comparisons'][0]))
        with self.assertRaises(ValueError):
            r.update_case(self.db, c)


class FakeResponse(io.BytesIO):
    def __init__(self, raw, content_type='application/json', status=200):
        super().__init__(raw)
        self.headers = {'Content-Type': content_type, 'Mcp-Session-Id': 'synthetic-session'}
        self.status = status


class ConnectorTests(unittest.TestCase):
    def test_query_scope_and_readonly(self):
        for tool, args in [('shopee_product_request', {'site': 'TH', 'product_id': '1'}), ('buy', {}), ('ali1688_similar_product', {'search_name': 'x', 'page': 0}), ('shopee_category_request', {'site': 'PH'}), ('shopee_product_request', {'site': 'PH', 'product_id': 'https://bad'})]:
            with self.assertRaises(ValueError):
                s.validate_query(tool, args)
        s.validate_query('shopee_category_request', {'site': 'PH', 'node_id': '123', 'page': 1})

    def test_trend_dates_are_explicit_and_limited(self):
        for args in ({}, {'query_start': '2020-01-01', 'query_end': '2026-01-01'}, {'query_start': '2999-01-01', 'query_end': '2999-02-01'}):
            with self.assertRaises(ValueError):
                s.validate_query('shopee_product_trend', {'site': 'PH', 'product_id': '1', **args})

    def test_secret_not_in_status(self):
        client = s.SorftimeClient('SYNTHETIC_SECRET')
        self.assertNotIn('SYNTHETIC_SECRET', json.dumps(client.status()))
        self.assertTrue(client.status()['configured'])

    def test_json_and_sse_response_protocol(self):
        for raw, ct in [(b'{"jsonrpc":"2.0","id":1,"result":{"ok":true}}', 'application/json'), (b'data: {"method":"notifications/progress"}\n\ndata: {"id":1,"result":{"ok":true}}\n\n', 'text/event-stream')]:
            client = s.SorftimeClient('SYNTHETIC_SECRET')
            with patch.object(client.opener, 'open', return_value=FakeResponse(raw, ct)) as mock:
                self.assertEqual(client.rpc('tools/list'), {'ok': True})
                self.assertEqual(client.session, 'synthetic-session')
                self.assertIn('text/event-stream', mock.call_args.args[0].headers['Accept'])

    def test_rpc_error_redacted_and_id_checked(self):
        for raw in [b'{"id":1,"error":{"message":"SYNTHETIC_SECRET"}}', b'{"id":999,"result":{}}']:
            client = s.SorftimeClient('SYNTHETIC_SECRET')
            with patch.object(client.opener, 'open', return_value=FakeResponse(raw)):
                with self.assertRaises(s.ConnectorError) as raised:
                    client.rpc('tools/list')
                self.assertNotIn('SYNTHETIC_SECRET', str(raised.exception))

    def test_http_error_no_retry_no_credential_echo(self):
        client = s.SorftimeClient('SYNTHETIC_SECRET')
        with patch.object(client.opener, 'open', side_effect=HTTPError('https://example.invalid?key=SYNTHETIC_SECRET', 429, 'SYNTHETIC_SECRET', {}, None)) as mock:
            with self.assertRaises(s.ConnectorError) as raised:
                client.rpc('tools/list')
            self.assertEqual(mock.call_count, 1)
            self.assertNotIn('SYNTHETIC_SECRET', str(raised.exception))
            self.assertEqual(client.last_status, 'rate_limited')

    def test_handshake_only_discovers_readonly_allowlist(self):
        client = s.SorftimeClient('SYNTHETIC_SECRET')
        catalog = {'tools': [{'name': 'shopeeProductRequest', 'inputSchema': {'properties': {'site': {}, 'product_id': {}}, 'required': ['site', 'product_id']}}, {'name': 'place_order'}]}
        with patch.object(client, 'rpc', side_effect=[{'protocolVersion': '2025-06-18'}, None, catalog, {'content': []}]):
            client.connect()
            self.assertEqual(client.protocol_version, '2025-06-18')
            self.assertEqual(list(client.tools), ['shopee_product_request'])
            client.call('shopee_product_request', {'site': 'PH', 'product_id': '1'})


# Reuse only the test HTTP harness, not its test methods (avoids duplicates).
class ResearchApiTests(unittest.TestCase):
    setUpClass = classmethod(test_mvp.ApiTests.setUpClass.__func__)
    tearDownClass = classmethod(test_mvp.ApiTests.tearDownClass.__func__)
    setUp = test_mvp.ApiTests.setUp
    tearDown = test_mvp.ApiTests.tearDown
    request = test_mvp.ApiTests.request

    def test_research_static_state_and_csrf(self):
        for path in ['/research.js', '/research.css', '/api/research/state']:
            self.assertEqual(self.request(path)[0], 200)
        self.assertEqual(self.request('/api/research/policy', {'revision': 1, 'maxSellingPricePHP': '500'}, token=False)[0], 403)
        self.assertEqual(self.request('/api/research/policy', {'revision': 1, 'maxSellingPricePHP': '500'})[0], 200)
        body = json.loads(self.request('/api/research/state')[1])
        self.assertEqual(body['policy']['maxSellingPricePHP'], '500')
        self.assertEqual(body['cases'], [])

    def test_import_create_save_export_roundtrip_and_provenance(self):
        self.assertEqual(self.request('/api/research/import', {'events': [event()], 'transport': 'backend_mcp'})[0], 200)
        data = json.loads(self.request('/api/research/state')[1])
        self.assertEqual(data['snapshots'][0]['transport'], 'manual_import')
        o = data['observations'][0]
        self.assertEqual(self.request('/api/research/snapshot/' + o['snapshotId'])[0], 200)
        status, body, _ = self.request('/api/research/cases', {'observationId': o['id']})
        self.assertEqual(status, 200)
        c = json.loads(body)['case']
        self.assertEqual(self.request('/api/research/cases/save', c)[0], 200)
        exported = json.loads(self.request('/api/research/export/' + c['id'])[1])
        self.assertIsNone(exported['assessment']['calculation'])
        self.assertFalse(exported['assessment']['canPublish'])

    def test_unconfigured_query_never_returns_fake_success(self):
        with patch.object(server, 'SORFTIME', s.SorftimeClient('')):
            status, body, _ = self.request('/api/research/query', {'tool': 'shopee_product_search_from_name', 'args': {'site': 'PH', 'name': 'x'}})
            self.assertEqual(status, 400)
            self.assertIn('未连接', json.loads(body)['error'])

    def test_connect_key_not_in_response_or_backup(self):
        old = server.SORFTIME
        try:
            with patch.object(s.SorftimeClient, '_connect', lambda self: setattr(self, 'last_status', 'connected')):
                status, body, _ = self.request('/api/research/connect', {'key': 'SYNTHETIC_SECRET'})
            self.assertEqual(status, 200)
            self.assertNotIn(b'SYNTHETIC_SECRET', body)
            self.assertNotIn(b'SYNTHETIC_SECRET', self.request('/api/backup')[1])
        finally:
            server.SORFTIME = old

    def test_async_query_stores_result_without_retry(self):
        client = s.SorftimeClient('SYNTHETIC_SECRET')
        with patch.object(server, 'SORFTIME', client), patch.object(client, 'call', return_value=event()['response']) as mocked:
            status, body, _ = self.request('/api/research/query', {'tool': 'shopee_product_search_from_name', 'args': {'site': 'PH', 'name': 'synthetic'}})
            self.assertEqual(status, 202)
            job_id = json.loads(body)['job']['id']
            for _ in range(100):
                data = json.loads(self.request('/api/research/state')[1])
                job = next(j for j in data['jobs'] if j['id'] == job_id)
                if job['status'] in ('completed', 'failed'):
                    break
                time.sleep(.02)
            self.assertEqual(job['status'], 'completed')
            self.assertEqual(mocked.call_count, 1)
            self.assertEqual(data['snapshots'][0]['transport'], 'backend_mcp')
            self.assertEqual(len(data['observations']), 1)

    def test_worker_failure_does_not_generate_empty_market_data(self):
        client = s.SorftimeClient('SYNTHETIC_SECRET')
        with patch.object(server, 'SORFTIME', client), patch.object(client, 'call', side_effect=s.ConnectorError('TIMEOUT', 'synthetic timeout')) as mocked:
            self.assertEqual(self.request('/api/research/query', {'tool': 'shopee_product_request', 'args': {'site': 'PH', 'product_id': '123'}})[0], 202)
            for _ in range(100):
                data = json.loads(self.request('/api/research/state')[1])
                if data['jobs'][0]['status'] == 'failed':
                    break
                time.sleep(.02)
            self.assertEqual(data['jobs'][0]['status'], 'failed')
            self.assertEqual(mocked.call_count, 1)
            self.assertEqual(data['observations'], [])
            self.assertEqual(data['snapshots'], [])

    def test_provider_error_result_is_quarantined_not_success(self):
        client = s.SorftimeClient('SYNTHETIC_SECRET')
        with patch.object(server, 'SORFTIME', client), patch.object(client, 'call', return_value={'isError': True, 'content': []}):
            self.assertEqual(self.request('/api/research/query', {'tool': 'shopee_product_request', 'args': {'site': 'PH', 'product_id': '123'}})[0], 202)
            for _ in range(100):
                data = json.loads(self.request('/api/research/state')[1])
                if data['jobs'][0]['status'] == 'quarantined':
                    break
                time.sleep(.02)
            self.assertEqual(data['jobs'][0]['status'], 'quarantined')
            self.assertEqual(data['observations'], [])
            self.assertEqual(len(data['snapshots']), 1)


if __name__ == '__main__':
    unittest.main()
