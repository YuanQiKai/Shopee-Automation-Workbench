"""Zero-dependency regression tests; use a temporary database, never seller data."""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import io
import json
from pathlib import Path
import random
import tempfile
import threading
import time
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import zipfile

import engine
import server
from seed import default_settings, seed_products, seed_suppliers


def fixture():
    p = seed_products()[0]
    r = default_settings()['rules']
    p['price'] = '1000'
    p['marketMax'] = ''
    p['costs'] = dict.fromkeys(engine.COST_FIELDS, '0')
    p['costs']['purchase'] = '20'
    r.update(fx='0.1', commission='10', platformShipping='5', shippingCap='100',
             transaction='3', installment='8', growth='2', marketing='0',
             receiving='0', orderFee='5', targetMargin='20', targetProfit='10')
    return p, r


class PricingTests(unittest.TestCase):
    def test_exact_cost_ledger(self):
        p, r = fixture()
        c = engine.evaluate(p, r)
        self.assertEqual((c['revenue'], c['totalCost'], c['profit'], c['margin']), ('100.00', '40.50', '59.50', '59.50'))
        self.assertEqual(sum(D(x['cny']) for x in c['lines']), D(c['totalCost']))

    def test_payment_modes_are_mutually_exclusive(self):
        p, r = fixture()
        p['payment'] = 'installment'
        c = engine.evaluate(p, r)
        self.assertEqual(c['profit'], '54.50')
        self.assertNotIn('transaction', [x['key'] for x in c['lines']])
        self.assertEqual([x['key'] for x in c['lines']].count('installment'), 1)

    def test_buyer_shipping_is_fee_base_not_product_revenue(self):
        p, r = fixture()
        p['buyerShipping'] = '50'
        c = engine.evaluate(p, r)
        self.assertEqual(c['revenue'], '100.00')
        self.assertEqual(c['profit'], '59.35')

    def test_shipping_cap_and_order_exemption(self):
        p, r = fixture()
        p['price'] = '3000'
        c = engine.evaluate(p, r)
        self.assertEqual(next(x['original'] for x in c['lines'] if x['key'] == 'platformShipping'), '100.00')
        p['orderFeeExempt'] = True
        self.assertEqual(D(engine.evaluate(p, r)['profit']) - D(c['profit']), D('0.50'))

    def test_cost_rounding_reconciles_to_displayed_ledger(self):
        p, r = fixture()
        p['costs']['purchase'] = '20.005'
        c = engine.evaluate(p, r)
        self.assertEqual(sum(D(x['cny']) for x in c['lines']), D(c['totalCost']))
        self.assertEqual(c['lines'][0]['original'], '20.01')

    def test_invalid_or_unknown_costs_are_not_zero(self):
        p, r = fixture()
        for value in ['', None, 'NaN', 'Infinity', '-1', True]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                engine.num(value)
        s = default_settings()
        p['costs']['tax'] = ''
        a = engine.analyze(p, s, seed_suppliers()[0])
        self.assertIsNone(a['calculation'])
        self.assertIn('税费暂估', a['blockers'])
        self.assertFalse(a['canApprove'])

    def test_minimum_price_satisfies_both_targets(self):
        p, r = fixture()
        result = engine.solve_price(p, r)
        self.assertTrue(result['meetsTarget'])
        self.assertFalse(engine.evaluate(p, r, str(D(result['price']) - 1))['meetsTarget'])

    def test_solver_matches_exact_brute_force_across_caps(self):
        rng = random.Random(42)
        for i in range(18):
            p, r = fixture()
            p['costs']['purchase'] = str(rng.randrange(1, 1800) / 100)
            p['buyerShipping'] = str(rng.randrange(50))
            p['payment'] = 'installment' if i % 2 else 'normal'
            r.update(fx=str(rng.choice(['0.125', '0.11', '0.18'])), shippingCap=str(rng.randrange(1, 30)),
                     platformShipping=str(rng.randrange(1, 20)), targetMargin=str(rng.randrange(5, 45)),
                     targetProfit=str(rng.randrange(1, 12)))
            expected = next(n for n in range(1, 2500) if engine.evaluate(p, r, str(n))['meetsTarget'])
            with self.subTest(i=i):
                self.assertEqual(int(D(engine.solve_price(p, r)['price'])), expected)

    def test_infeasible_price_returns_quickly(self):
        p, r = fixture()
        r['commission'] = '100'
        start = time.monotonic()
        self.assertIsNone(engine.solve_price(p, r))
        self.assertLess(time.monotonic() - start, 0.5)

    def test_very_small_fx_bound_is_safe(self):
        p, r = fixture()
        p['costs'] = dict.fromkeys(engine.COST_FIELDS, '0')
        r.update(fx='0.000001', commission='0', growth='0', transaction='0', platformShipping='0', orderFee='0', targetMargin='0', targetProfit='0.01')
        self.assertEqual(engine.solve_price(p, r)['price'], '5000.00')

    def test_content_does_not_invent_product_claims(self):
        p, _ = fixture()
        p['facts'] = {'material': 'Silicone', 'size': '', 'pack': '1 piece', 'use': ''}
        c = engine.generate_content(p)
        self.assertIn('Material: Silicone', c['description'])
        self.assertNotIn('Size:', c['description'])
        self.assertIn('未调用 AI', c['method'])

    def test_supply_and_evidence_gates(self):
        p = seed_products()[0]
        s = default_settings()
        sup = seed_suppliers()[0]
        p.update(demo=False, supplierSku='', quoteValidUntil=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat())
        a = engine.analyze(p, s, sup)
        for label in ['真实商品不能关联示例供应商', '店铺费率尚未核实', '供应商 SKU 待录入', '报价已过期']:
            self.assertIn(label, a['blockers'])


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_db = server.DB_PATH
        cls.httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.httpd.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()
        server.DB_PATH = cls.original_db

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='meeya-test-')
        server.DB_PATH = Path(self.temp.name) / 'test.sqlite3'
        server.init_db()

    def tearDown(self):
        # The HTTP response can arrive before its handler exits the database
        # context; wait for the same lock before cleaning up on Windows.
        with server.LOCK:
            self.temp.cleanup()

    def request(self, path, body=None, token=True, headers=None):
        h = dict(headers or {})
        if body is not None:
            h['Content-Type'] = 'application/json'
            if token:
                h['X-MVP-Token'] = server.TOKEN
        req = Request(self.base + path, data=json.dumps(body).encode() if body is not None else None, headers=h)
        try:
            response = urlopen(req, timeout=10)
        except HTTPError as e:
            response = e
        with response:
            return response.status, response.read(), response.headers

    def state(self):
        status, body, _ = self.request('/api/state')
        self.assertEqual(status, 200)
        return json.loads(body)

    def product(self, id='product-1'):
        return next(p for p in self.state()['products'] if p['id'] == id)

    def approve_demo(self):
        p = self.product()
        self.assertEqual(self.request('/api/products/product-1/content', {'revision': p['revision']})[0], 200)
        p = self.product()
        self.assertTrue(p['analysis']['canApprove'], p['analysis']['blockers'])
        self.assertEqual(self.request('/api/products/product-1/approve', {'revision': p['revision']})[0], 200)
        return self.product()

    def test_static_assets_and_health(self):
        for path in ['/', '/app.js', '/style.css', '/favicon.svg', '/api/health']:
            status, body, headers = self.request(path)
            self.assertEqual(status, 200, path)
            self.assertTrue(body)
            self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(self.request('/server.py')[0], 404)

    def test_seed_state_and_persistence(self):
        s = self.state()
        self.assertEqual(len(s['products']), 8)
        self.assertEqual(len(s['suppliers']), 3)
        self.assertTrue(all(p['demo'] for p in s['products']))
        self.assertFalse(s['productionConnected'])
        server.init_db()
        self.assertEqual(len(self.state()['products']), 8)
        self.assertEqual(len(self.state()['audit']), 1)

    def test_forged_origin_token_and_host_rejected(self):
        self.assertEqual(self.request('/api/export', {'ids': ['product-1']}, token=False)[0], 403)
        self.assertEqual(self.request('/api/export', {'ids': ['product-1']}, headers={'Origin': 'https://attacker.invalid'})[0], 403)
        self.assertEqual(self.request('/api/state', headers={'Host': 'attacker.invalid'})[0], 403)

    def test_new_product_cannot_forge_demo_or_approval(self):
        p = self.product()
        p.update(id='product-1', demo=True, approval={'fingerprint': 'fake'})
        status, body, _ = self.request('/api/products', p)
        self.assertEqual(status, 200)
        created = json.loads(body)['product']
        self.assertNotEqual(created['id'], 'product-1')
        self.assertFalse(created['demo'])
        self.assertIsNone(created['approval'])
        self.assertFalse(self.product(created['id'])['analysis']['canApprove'])

    def test_revision_conflict_preserves_saved_product(self):
        p = self.product()
        old = deepcopy(p)
        p['price'] = '559'
        self.assertEqual(self.request('/api/products/product-1', p)[0], 200)
        old['price'] = '1'
        self.assertEqual(self.request('/api/products/product-1', old)[0], 400)
        self.assertEqual(self.product()['price'], '559')

    def test_invalid_payload_does_not_mutate_data(self):
        p = self.product()
        p['costs']['purchase'] = '-1'
        self.assertEqual(self.request('/api/products/product-1', p)[0], 400)
        self.assertEqual(D(self.product()['costs']['purchase']), D('12.50'))
        p['costs'] = None
        self.assertEqual(self.request('/api/products/product-1', p)[0], 400)

    def test_full_content_review_export_and_idempotence(self):
        p = self.approve_demo()
        self.assertTrue(p['analysis']['approvalValid'])
        self.assertFalse(p['analysis']['canPublish'])
        status, body, h = self.request('/api/export', {'ids': ['product-1', 'product-1']})
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            self.assertIn('products.csv', z.namelist())
            self.assertIn('未真实上架', z.read('README.txt').decode())
            self.assertTrue(z.read('products.csv').startswith(b'\xef\xbb\xbf'))
            self.assertEqual(len(json.loads(z.read('products.json'))), 1)
        status2, _, h2 = self.request('/api/export', {'ids': ['product-1']})
        self.assertEqual(status2, 200)
        self.assertEqual(h['X-Export-Id'], h2['X-Export-Id'])
        self.assertEqual(len(self.state()['exports']), 1)

    def test_edits_invalidate_approval(self):
        p = self.approve_demo()
        p['price'] = '560'
        self.assertEqual(self.request('/api/products/product-1', p)[0], 200)
        p = self.product()
        self.assertEqual(p['analysis']['state'], 'stale')
        self.assertFalse(p['analysis']['approvalValid'])
        self.assertEqual(self.request('/api/export', {'ids': ['product-1']})[0], 400)

    def test_supplier_change_invalidates_approval(self):
        self.approve_demo()
        sup = next(s for s in self.state()['suppliers'] if s['id'] == 'supplier-1')
        sup['stock'] = 0
        self.assertEqual(self.request('/api/suppliers', sup)[0], 200)
        self.assertFalse(self.product()['analysis']['approvalValid'])

    def test_rule_change_invalidates_approval(self):
        self.approve_demo()
        s = self.state()['settings']
        s['rules']['commission'] = '13'
        self.assertEqual(self.request('/api/settings', s)[0], 200)
        self.assertFalse(self.product()['analysis']['approvalValid'])

    def test_fact_change_requires_regenerating_content(self):
        p = self.approve_demo()
        p['facts']['material'] = 'Steel'
        self.assertEqual(self.request('/api/products/product-1', p)[0], 200)
        self.assertIsNone(self.product()['content'])
        self.assertFalse(self.product()['analysis']['canApprove'])

    def test_scenarios_do_not_modify_saved_product(self):
        p = self.product()
        status, raw, _ = self.request('/api/pricing', {'product': p})
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(raw)['scenarios']), 4)
        self.assertEqual(p, self.product())

    def test_image_upload_and_backup(self):
        png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jkP8AAAAASUVORK5CYII='
        p = self.product()
        body = {'dataUrl': 'data:image/png;base64,' + png, 'rights': True, 'productId': p['id'], 'revision': p['revision']}
        self.assertEqual(self.request('/api/assets', body)[0], 200)
        p = self.product()
        status, raw, _ = self.request(p['imageUrl'])
        self.assertEqual(status, 200)
        self.assertEqual(raw, base64.b64decode(png))
        status, raw, _ = self.request('/api/backup')
        self.assertEqual(status, 200)
        backup = json.loads(raw)
        self.assertEqual(backup['schemaVersion'], 1)
        self.assertTrue(any(r['kind'] == 'asset' for r in backup['records']))
        self.assertTrue(backup['audit'])

    def test_csv_formula_injection_is_escaped(self):
        self.assertEqual(server.csv_cell('=1+1'), "'=1+1")
        self.assertEqual(server.csv_cell(' @danger'), "' @danger")
        self.assertEqual(server.csv_cell('ordinary'), 'ordinary')


if __name__ == '__main__':
    unittest.main(verbosity=2)
