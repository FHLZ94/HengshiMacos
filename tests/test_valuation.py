import unittest
from datetime import datetime,timezone,timedelta
from valuation import calculate

class ValuationTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime.now(timezone.utc)
        self.quote={'price':100,'reported_ttm_eps':5,'fetched_at':self.now.isoformat()}
        self.comparison={'target_median':150,'target_source':'综合分析师中位数','fetched_at':self.now.isoformat()}
        self.history={'median':20,'basis':'reported','samples':20,'years':5,'fetched_at':self.now.isoformat(),'source':'历史PE'}
        self.guidance={'eps':9,'eps_basis':'reported','period':'未来12个月','source_url':'https://example.com/ir','updated_at':self.now.isoformat()}

    def test_management_is_used_at_full_weight_with_matching_historical_median(self):
        result=calculate(self.quote,{'eps':5,'basis':'ntm_4q'},self.comparison,management=self.guidance,historical_pe=self.history)
        self.assertEqual(result['eps_used'],9)
        self.assertEqual(result['reference_price'],180)
        self.assertEqual(result['current_pe'],20)
        self.assertEqual(result['upside_pct'],80)

    def test_no_management_uses_median_and_does_not_invent_current_multiple_projection(self):
        result=calculate(self.quote,{'eps':8,'basis':'ntm_4q'},self.comparison)
        self.assertEqual(result['reference_price'],150)
        self.assertEqual(result['reference_method'],'analyst_median')

    def test_missing_guidance_source_falls_back_to_analyst_median(self):
        result=calculate(self.quote,comparison=self.comparison,management={**self.guidance,'source_url':''},historical_pe=self.history)
        self.assertEqual(result['reference_price'],150)

    def test_expired_guidance_falls_back_to_median(self):
        old={**self.guidance,'updated_at':(self.now-timedelta(days=181)).isoformat()}
        self.assertEqual(calculate(self.quote,comparison=self.comparison,management=old,historical_pe=self.history)['reference_price'],150)

    def test_adjusted_guidance_does_not_mix_with_accounting_historical_pe(self):
        adjusted={**self.guidance,'eps_basis':'adjusted'}
        self.assertEqual(calculate(self.quote,comparison=self.comparison,management=adjusted,historical_pe=self.history)['reference_price'],150)

    def test_average_target_is_never_mislabeled_as_median(self):
        q={**self.quote,'target_price':190}
        result=calculate(q,{'eps':13.45,'basis':'ntm_4q'},{'trailing_pe':14.84,'fetched_at':self.now.isoformat()})
        self.assertIsNone(result['reference_price'])

    def test_firm_median_uses_latest_quote_per_firm_not_outlier_mean(self):
        rows=[{'firm':f,'price':v,'published':self.now.isoformat()} for f,v in [('美银',100),('瑞银',120),('高盛',1000)]]
        result=calculate(self.quote,comparison={'target_quotes':rows,'fetched_at':self.now.isoformat()})
        self.assertEqual(result['reference_price'],120)
        self.assertEqual(result['reference']['count'],3)

    def test_loss_pe_is_not_replaced_by_forward_earnings(self):
        result=calculate({**self.quote,'reported_ttm_eps':-2.39}, {'eps':.95,'basis':'ntm_4q'},self.comparison)
        self.assertIsNone(result['current_pe'])
        self.assertIn('亏损',result['pe_status'])
        self.assertEqual(result['reference_price'],150)

if __name__=='__main__':unittest.main()
