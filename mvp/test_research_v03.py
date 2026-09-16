"""Isolated synthetic v0.3 fixtures, never imported into business records."""
import json
import time
import unittest
from copy import deepcopy
from unittest.mock import patch

import research as r
import server
import sorftime as s
import test_mvp
import test_research as previous
from test_research import event


class DraftAndShapeTests(unittest.TestCase):
    setUp = previous.EvidenceTests.setUp
    tearDown = previous.EvidenceTests.tearDown
    add = previous.EvidenceTests.add
    ready = previous.EvidenceTests.ready

    def draft(self, case, request='synthetic-request-01', revision=0):
        return r.autosave_case(self.db, {**case, 'requestId': request, 'draftRevision': revision})

    def test_nested_multi_filter_response_retains_every_field_and_page(self):
        raw = {'product_id': '100', 'price': '30', 'photo': ['https://down-ph.img.susercontent.com/test'],
               'sales_count': 100, 'new_metric': {'zero': 0, 'false': False}, 'seven_days_sale_count': 7}
        e = event('shopee_product_search', {'page': 2, 'page_count': 299, 'products': [raw]},
                  {'products.price': 'Price THB', 'products.new_metric': 'New field', 'page_count': 'Total pages'},
                  {'site': 'PH', 'page': 2, 'node_id': '11021436'})
        row = self.add(e)[0]
        self.assertIsNone(row['price'])
        self.assertEqual(row['rowPath'], '/data/products/0')
        self.assertEqual(row['fieldProvenance']['price'], '/data/products/0/price')
        detail = r.observation_details(self.db, row['id'])
        self.assertEqual(detail['raw'], raw)
        self.assertEqual(detail['doc']['price'], 'Price THB')
        self.assertEqual(detail['originalDoc']['page_count'], 'Total pages')
        self.assertEqual(detail['envelopeFields']['data']['page_count'], 299)
        state = r.research_state(self.db, {})
        self.assertEqual(state['snapshots'][0]['resultInfo'], {'page': 2, 'pageCount': 299, 'returnedRows': 1})

    def test_list_and_single_detail_paths(self):
        row = self.add()[0]
        self.assertEqual(row['rowPath'], '/data/0')
        self.assertEqual(r.observation_details(self.db, row['id'])['raw']['product_id'], '123')
        row = self.add(event('shopee_product_request', {'product_id': '124', 'price': 1}, args={'site': 'PH', 'product_id': '124'}))[0]
        self.assertEqual(row['rowPath'], '/data')

    def test_empty_result_and_unknown_wrapper_do_not_invent_products(self):
        self.assertEqual(self.add(event('shopee_product_search', {'products': [], 'page': 1}, args={'site': 'PH'})), [])
        self.assertEqual(self.add(event('shopee_product_search', {'unrecognized': []}, args={'site': 'PH'})), [])
        self.assertEqual(len(r.records(self.db, 'research_snapshot')), 2)
        self.assertTrue(any('隔离' in n for n in r.read(self.db, 'research_batch', self.batch['id'])['notes']))

    def test_raw_non_product_tree_is_saved_without_fake_observations(self):
        self.assertEqual(self.add(event('shopee_category_tree', [{'node_id': '100', 'name': 'SYNTHETIC'}], args={'site': 'PH'})), [])
        self.assertEqual(len(r.records(self.db, 'research_snapshot')), 1)

    def test_both_image_shapes_and_sku_photo(self):
        for photo in ('https://cbu01.alicdn.com/test', ['https://cbu01.alicdn.com/test']):
            row = self.add(event('ali1688_product_request', {'product_id': '888', 'photo': photo}, {}))[0]
            self.assertEqual(row['photos'], ['https://cbu01.alicdn.com/test'])
        sku = self.add(event('ali1688_product_variations', [{'sku_id': '999', 'photo': ['https://cbu01.alicdn.com/sku']}], {}))[0]
        self.assertEqual(sku['photos'], ['https://cbu01.alicdn.com/sku'])

    def test_valid_autosave_is_durable_and_retry_is_idempotent(self):
        c = r.new_case(self.db, self.add()[0]['id'])
        c['title'] = 'Synthetic changed title'
        first = self.draft(c)
        second = self.draft(c)
        self.assertEqual(first, second)
        self.assertEqual(first['draft']['status'], 'committed')
        self.assertEqual(r.read(self.db, 'research_case', c['id'])['title'], c['title'])
        self.assertEqual(first['case']['revision'], c['revision'] + 1)

    def test_invalid_draft_retained_without_old_positive_assessment(self):
        c = r.update_case(self.db, self.ready())
        r.save(self.db, 'settings', {'id': 'main', **self.settings})
        c['quote']['unitPrice'] = '-'
        result = self.draft(c)
        self.assertEqual(result['draft']['status'], 'draft')
        self.assertEqual(result['draft']['payload']['quote']['unitPrice'], '-')
        self.assertEqual(r.read(self.db, 'research_case', c['id'])['quote']['unitPrice'], '4.5')
        a = r.research_state(self.db, {})['cases'][0]['assessment']
        self.assertEqual(a['state'], 'needs_evidence')
        for field in ('calculation', 'recommended', 'cash', 'stockCashUpperBound', 'maxPurchasePerSaleCNY'):
            self.assertIsNone(a[field])
        self.assertFalse(a['canPurchase'])
        self.assertEqual(a['needs'][0]['code'], 'DRAFT_PENDING')

    def test_draft_correction_commits_and_clears_pending_gate(self):
        c = r.new_case(self.db, self.add()[0]['id'])
        c['pricePHP'] = '-'
        draft = self.draft(c)
        c['pricePHP'] = '100'
        result = self.draft(c, 'synthetic-request-02', draft['draft']['revision'])
        self.assertEqual(result['draft']['status'], 'committed')
        self.assertNotIn('DRAFT_PENDING', [n['code'] for n in r.research_state(self.db, {})['cases'][0]['assessment']['needs']])

    def test_concurrent_valid_edits_preserve_losing_copy(self):
        c = r.new_case(self.db, self.add()[0]['id'])
        first = self.draft({**c, 'title': 'First writer'})
        second = self.draft({**c, 'title': 'Other writer'}, 'synthetic-request-02')
        self.assertTrue(second['conflict'])
        self.assertEqual(r.read(self.db, 'research_case', c['id'])['title'], 'First writer')
        self.assertEqual(r.read(self.db, 'research_conflict_draft', second['recoveryId'])['payload']['title'], 'Other writer')

    def test_two_invalid_drafts_conflict_even_unchanged_case_revision(self):
        c = r.new_case(self.db, self.add()[0]['id'])
        c['pricePHP'] = '-'
        first = self.draft(c)
        c['pricePHP'] = 'bad'
        second = self.draft(c, 'synthetic-request-02')
        self.assertTrue(second['conflict'])
        self.assertEqual(second['draft'], first['draft'])

    def test_missing_request_id_does_not_write(self):
        c = r.new_case(self.db, self.add()[0]['id'])
        with self.assertRaises(ValueError):
            r.autosave_case(self.db, c)
        self.assertEqual(r.records(self.db, 'research_draft'), [])

    def test_keyword_write_receipt_is_preserved_without_parsing_as_products(self):
        e = event('shopee_favorite_keyword', args={'site': 'PH', 'keyword': 'synthetic'})
        e['response'] = {'content': [{'type': 'text', 'text': 'SYNTHETIC receipt'}]}
        self.assertEqual(self.add(e), [])
        self.assertFalse(any(n.startswith('快照隔离') for n in r.read(self.db, 'research_batch', self.batch['id'])['notes']))


class AllToolContractTests(unittest.TestCase):
    def test_catalog_has_22_exact_tools_with_19_reads_and_3_guarded_writes(self):
        self.assertEqual(len(s.CATALOG), 22)
        self.assertEqual(len(s.MUTATING), 3)
        self.assertEqual(sum(not t['mutating'] for t in s.CATALOG), 19)
        for t in s.CATALOG:
            self.assertEqual(set(t['inputSchema']['properties']), s.ALLOWED[t['name']])

    def test_every_catalog_tool_has_a_valid_minimal_explicit_request(self):
        for spec in s.CATALOG:
            args = {'site': 'PH'} if spec['name'].startswith('shopee_') else {}
            for name in spec['inputSchema']['required']:
                args[name] = 'https://example.com/image.jpg' if name == 'image_url' else '123' if name.endswith('_id') else 'synthetic'
            if spec['name'] == 'shopee_product_trend':
                args.update(query_start='2026-01-01', query_end='2026-01-02')
            with self.subTest(tool=spec['name']):
                self.assertEqual(s.validate_query(spec['name'], args), args)

    def test_remote_filter_parameters_preserved_without_local_price_assumption(self):
        args = {'site': 'PH', 'page': 50, 'node_id': '11021436', 'price_range_min': 0, 'price_range_max': 999,
                'shop_location': 1, 'month_sale_volume_range_min': 0, 'star_range_min': 4.5}
        self.assertEqual(s.validate_query('shopee_product_search', args), args)
        args = {'rights': '1,2,3', 'supplier_name': 'synthetic', 'stock_count_min': 10, 'repurchase_rate_min': 10, 'page': 100}
        self.assertEqual(s.validate_query('ali1688_product_search', args), args)

    def test_invalid_filter_values_fail_before_network(self):
        bad = [{'price_range_min': 10, 'price_range_max': 5}, {'star_range_min': 6}, {'page': 1.5},
               {'page': True}, {'shop_type': 4}, {'online_date_range_min': 'bad'}, {'name': 'not supported'},
               {'price_range_min': float('nan')}, {'month_sale_volume_range_min': 0.5}]
        for args in bad:
            with self.subTest(args=args), self.assertRaises(ValueError):
                s.validate_query('shopee_product_search', {'site': 'PH', **args})

    def test_image_search_rejects_local_or_credentialed_url(self):
        for url in ['http://example.com/x', 'https://127.0.0.1/x', 'https://localhost/x', 'https://test.internal/x', 'https://key:secret@example.com/x']:
            with self.assertRaises(ValueError):
                s.validate_query('ali1688_product_search_from_image', {'image_url': url})

    def test_write_calls_require_confirmation_before_even_handshake(self):
        client = s.SorftimeClient('SYNTHETIC_SECRET')
        with patch.object(client, 'rpc') as rpc:
            for tool, args in [('shopee_favorite_keyword', {'keyword': 'synthetic'}),
                               ('shopee_del_favorite_keyword', {'keyword': 'synthetic'}),
                               ('shopee_change_favorite_keyword', {'keyword': 'synthetic', 'to_dict': 'new'})]:
                with self.assertRaises(s.ConnectorError) as error:
                    client.call(tool, {'site': 'PH', **args})
                self.assertEqual(error.exception.code, 'CONFIRMATION_REQUIRED')
            rpc.assert_not_called()

    def test_all_tools_are_discovered_but_unrelated_tools_are_not(self):
        client = s.SorftimeClient('SYNTHETIC_SECRET')
        catalog = {'tools': [{'name': t['name'], 'inputSchema': t['inputSchema']} for t in s.CATALOG] + [{'name': 'place_order'}]}
        with patch.object(client, 'rpc', side_effect=[{'protocolVersion': '2025-03-26'}, None, catalog]):
            client.connect()
        self.assertEqual(len(client.tools), 22)
        self.assertEqual(len(client.status()['writeTools']), 3)
        self.assertNotIn('SYNTHETIC_SECRET', json.dumps(client.status()))


class V03ApiTests(unittest.TestCase):
    setUpClass = classmethod(test_mvp.ApiTests.setUpClass.__func__)
    tearDownClass = classmethod(test_mvp.ApiTests.tearDownClass.__func__)
    setUp = test_mvp.ApiTests.setUp
    tearDown = test_mvp.ApiTests.tearDown
    request = test_mvp.ApiTests.request

    def new_case(self):
        self.request('/api/research/import', {'events': [event()]})
        state = json.loads(self.request('/api/research/state')[1])
        obs = state['observations'][0]
        case = json.loads(self.request('/api/research/cases', {'observationId': obs['id']})[1])['case']
        return case, obs

    def test_new_assets_and_image_csp(self):
        for path in ['/research-autosave.js', '/research-browser.js', '/research-interactions.js']:
            status, body, headers = self.request(path)
            self.assertEqual(status, 200)
            self.assertIn('https://*.susercontent.com', headers['Content-Security-Policy'])

    def test_autosave_api_conflict_and_latest_invalid_export(self):
        c, obs = self.new_case()
        c.update(pricePHP='-', requestId='synthetic-request-01', draftRevision=0)
        self.assertEqual(self.request('/api/research/cases/autosave', c, token=False)[0], 403)
        self.assertEqual(self.request('/api/research/cases/autosave', c)[0], 200)
        exported = json.loads(self.request('/api/research/export/' + c['id'])[1])
        self.assertEqual(exported['draft']['payload']['pricePHP'], '-')
        self.assertIsNone(exported['assessment']['calculation'])
        self.assertEqual(exported['assessment']['needs'][0]['code'], 'DRAFT_PENDING')
        c['requestId'] = 'synthetic-request-02'
        self.assertEqual(self.request('/api/research/cases/autosave', c)[0], 409)
        detail = json.loads(self.request('/api/research/observation/' + obs['id'])[1])
        self.assertEqual(detail['raw']['product_id'], '123')

    def test_write_requires_confirmation_and_idempotence_does_not_repeat_network(self):
        client = s.SorftimeClient('SYNTHETIC_SECRET')
        body = {'tool': 'shopee_favorite_keyword', 'args': {'site': 'PH', 'keyword': 'synthetic'}}
        with patch.object(server, 'SORFTIME', client), patch.object(client, 'call', return_value={'content': [{'type': 'text', 'text': 'SYNTHETIC receipt'}]}) as call:
            self.assertEqual(self.request('/api/research/query', body)[0], 400)
            call.assert_not_called()
            body.update(confirmedExternalChange=True, requestId='synthetic-write-request')
            first = json.loads(self.request('/api/research/query', body)[1])
            for _ in range(100):
                state = json.loads(self.request('/api/research/state')[1])
                if state['jobs'][0]['status'] in ('completed', 'failed', 'quarantined'):
                    break
                time.sleep(.02)
            second = json.loads(self.request('/api/research/query', body)[1])
            self.assertEqual(first['job']['id'], second['job']['id'])
            self.assertEqual(state['jobs'][0]['status'], 'completed')
            call.assert_called_once_with(body['tool'], body['args'], confirmed=True)
            self.assertEqual(state['observations'], [])


if __name__ == '__main__':
    unittest.main()
