"""Synthetic admission-boundary and approval-bypass regressions, no business writes."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal as D
import unittest
import selection
import research
import server
import engine
from seed import seed_products, seed_suppliers
import test_research as previous


class SelectionTests(unittest.TestCase):
    setUp = previous.EvidenceTests.setUp
    tearDown = previous.EvidenceTests.tearDown
    add = previous.EvidenceTests.add
    ready = previous.EvidenceTests.ready
    assess = previous.EvidenceTests.assess

    def test_complete_case_and_optional_repeat_not_required(self):
        c = self.ready(); c['selectionEvidence']['expansion'] = {}
        a = self.assess(c)
        self.assertTrue(a['canReviewListing'], a)
        self.assertFalse(a['canPublish'])
        self.assertEqual(a['selection']['metrics']['sampleSales30d'], '300')
        self.assertGreaterEqual(a['selection']['score'], 75)
        self.assertEqual(a['selection']['dimensions'][-1]['score'], 0)

    def test_old_record_and_missing_evidence_fail_closed(self):
        c = self.ready(); c.pop('selectionEvidence')
        a = self.assess(c)
        self.assertFalse(a['canReviewListing'])
        self.assertIsNone(a['selection']['score'])
        # Upgraded legacy cases must accept new evidence through autosave.
        research.save(self.db, 'research_case', c)
        payload = {**c, 'selectionEvidence': selection.empty_evidence(), 'requestId':'synthetic-upgrade-01', 'draftRevision':0}
        saved = research.autosave_case(self.db,payload)
        self.assertIn('selectionEvidence',saved['case'])

    def test_each_required_proof_expired_and_future(self):
        c = self.ready()
        for key in selection.FIELDS:
            if key == 'expansion': continue
            for field,delta in [('observedAt',timedelta(days=1)),('validUntil',timedelta(days=-1))]:
                changed = deepcopy(c)
                changed['selectionEvidence'][key][field] = (datetime.now(timezone.utc)+delta).isoformat()
                self.assertFalse(self.assess(changed)['canReviewListing'],(key,field))

    def test_no_sentinel_cumulative_mixed_or_future_sales(self):
        c = self.ready()
        for field,value in [('sales30d','-1'),('salesWindowEnd','1970-01-01'),('salesScope','cumulative'),('salesScope','mixed_variants'),('salesWindowEnd','2999-01-01'),('sales30d','3.5')]:
            changed = deepcopy(c); changed['comparisons'][0][field]=value
            a = self.assess(changed)
            self.assertFalse(a['canReviewListing'], (field,value))
            self.assertEqual(a['selection']['metrics']['validMarketSamples'],9)

    def test_sales_threshold_and_sample_concentration(self):
        c = self.ready(); c['comparisons'][0]['sales30d']='29'
        self.assertIn('样本30天销量合计不足300件',';'.join(self.assess(c)['failures']))
        c = self.ready(); c['comparisons'][0]['sales30d']='10000'
        self.assertIn('前三店',';'.join(self.assess(c)['failures']))

    def test_same_shop_and_duplicate_observations_do_not_inflate_sample(self):
        c = self.ready()
        observations = research.observations_with_conflicts(self.db)
        for obs in observations:
            if obs['platform']=='shopee': obs['shopId']='456'
        a = research.assess(c,self.settings,observations)
        self.assertEqual(a['selection']['metrics']['distinctShops'],1)
        self.assertFalse(a['canReviewListing'])
        c['comparisons'].append(deepcopy(c['comparisons'][0]))
        a = self.assess(c)
        self.assertEqual(a['selection']['metrics']['validMarketSamples'],10)

    def test_cross_border_evidence_and_price_premium(self):
        c = self.ready(); observations = research.observations_with_conflicts(self.db)
        for row in observations: row['group']='local'
        self.assertFalse(research.assess(c,self.settings,observations)['canReviewListing'])
        c['buyerShippingPHP']='100'
        self.assertIn('到手价超过',';'.join(self.assess(c)['failures']))

    def test_fresh_quote_no_forced_inventory_and_stock_minimum(self):
        c = self.ready()
        for field,value in [('moq','2'),('purchaseQuantity','2'),('stock','9')]:
            x=deepcopy(c);x['quote'][field]=value
            self.assertFalse(self.assess(x)['canReviewListing'],field)
        c['quote']['observedAt']=(datetime.now(timezone.utc)-timedelta(hours=25)).isoformat()
        self.assertFalse(self.assess(c)['canReviewListing'])

    def test_weight_timing_and_conflicting_day_hour_units(self):
        c = self.ready()
        for field,value in [('billableWeightG','501'),('billableWeightG','200'),('deadlineHours','95'),('leadHours','1'),('deadlineHours','241')]:
            x=deepcopy(c);x['selectionEvidence']['logistics'][field]=value
            self.assertFalse(self.assess(x)['canReviewListing'],(field,value))
        c['selectionEvidence']['logistics']['deadlineHours']='96'
        self.assertTrue(self.assess(c)['canReviewListing'])

    def test_cash_loss_reserve_and_28_day_limit(self):
        c=self.ready()
        for field,value in [('monthlyLossCNY','4000'),('dailyUnits','100'),('dailyUnits','')]:
            x=deepcopy(c);x['selectionEvidence']['cash'][field]=value
            self.assertFalse(self.assess(x)['canReviewListing'])
        self.settings['reserve']='4999'
        self.assertFalse(self.assess(c)['canReviewListing'])

    def test_each_exclusion_cannot_be_overridden_by_score(self):
        c=self.ready()
        for key in selection.EXCLUSIONS:
            x=deepcopy(c); x['selectionEvidence']['compliance'][key]='no'
            a=self.assess(x)
            self.assertEqual(a['state'],'rejected',key)
            self.assertFalse(a['canReviewListing'])

    def test_profit_and_all_logistics_stress_are_enforced(self):
        c=self.ready()
        c['costs']['overhead']['amount']='13.01'
        self.assertEqual(self.assess(c)['calculation']['profit'],'14.99')
        self.assertTrue(any('基准' in x for x in self.assess(c)['failures']))
        c=self.ready()
        pressure=self.assess(c)['selection']['stress']
        for label in ['国内运费','云仓操作','包材','SLS 卖家净物流']:
            self.assertEqual(next(l['cny'] for l in pressure['lines'] if l['name']==label),'1.15')
        self.settings['rules']['installment']='80'
        self.assertTrue(any('组合压力' in x for x in self.assess(c)['failures']))

    def test_invalid_nested_inputs_preserve_draft_but_freeze_result(self):
        c=self.ready()
        c['selectionEvidence']['cash']['dailyUnits']='NaN'
        with self.assertRaises(ValueError): research.update_case(self.db,c)
        result=research.autosave_case(self.db,{**c,'requestId':'synthetic-invalid-01','draftRevision':0})
        self.assertEqual(result['draft']['status'],'draft')
        a=research.assessment_with_draft(result['case'],self.settings,research.observations_with_conflicts(self.db),research.get_policy(self.db),result['draft'])
        self.assertFalse(a['canReviewListing'])
        self.assertIsNone(a['selection']['score'])
        self.assertFalse(a['selection']['eligible'])

    def test_real_product_cannot_bypass_with_old_manual_scores(self):
        p=seed_products()[0];p['demo']=False;p['scores']=[20,15,25,20,10,10]
        a=server.analyze_product(self.db,p,self.settings,seed_suppliers()[0])
        self.assertFalse(a['canApprove'])
        self.assertIn('七维',';'.join(a['blockers']))

    def test_real_approval_is_bound_to_current_research_and_costs(self):
        c=self.ready();research.save(self.db,'research_case',c)
        p=seed_products()[0];p.update(demo=False,researchCaseId=c['id'],name=c['title'],supplierSku='999',price='500',buyerShipping='0',weight='300',payment='normal',orderFeeExempt=False,source='SYNTHETIC',quoteValidUntil=c['quote']['validUntil'],approval=None)
        p['costs']={k:'1' for k in engine.COST_FIELDS};p['costs']['purchase']='4.50'
        p['checks']={k:True for k in p['checks']};p['content']={'title':'SYNTHETIC','description':'SYNTHETIC'}
        supplier=seed_suppliers()[0];supplier['demo']=False
        a=server.analyze_product(self.db,p,self.settings,supplier)
        self.assertTrue(a['canApprove'],a)
        p['approval']={'fingerprint':engine.fingerprint(p,self.settings,supplier),'selectionFingerprint':a['selectionFingerprint']}
        self.assertTrue(server.analyze_product(self.db,p,self.settings,supplier)['approvalValid'])
        p['price']='501'
        self.assertFalse(server.analyze_product(self.db,p,self.settings,supplier)['canApprove'])
        p['price']='500';c['selectionEvidence']['compliance']['noPowered']='no';research.save(self.db,'research_case',c)
        self.assertFalse(server.analyze_product(self.db,p,self.settings,supplier)['approvalValid'])

if __name__=='__main__': unittest.main()
