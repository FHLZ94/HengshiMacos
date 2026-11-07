import unittest
from datetime import datetime, timezone

from valuation import calculate


class ValuationTests(unittest.TestCase):
    def test_management_guidance_has_higher_weight(self):
        now=datetime.now(timezone.utc)
        quote={'price':100}
        consensus={'eps':5,'basis':'ntm_4q'}
        guidance={'eps':9,'period':'未来12个月','source_url':'https://example.com/ir','updated_at':now.isoformat()}
        comparison={'trailing_pe':20,'fetched_at':now.isoformat()}
        result=calculate(quote,consensus,comparison,management=guidance,now=now)
        self.assertAlmostEqual(result['eps_used'],7.8)
        self.assertEqual(result['fair_price'],156)
        self.assertEqual(result['upside_pct'],56)

    def test_current_pe_without_management(self):
        now=datetime.now(timezone.utc)
        result=calculate({'price':116.1},{'eps':7.06,'basis':'ntm_4q'},
                         {'trailing_pe':18.2,'fetched_at':now.isoformat()},now=now)
        self.assertEqual(result['fair_price'],128.49)
        self.assertEqual(result['pe_basis'],'TradingView 当前滚动市盈率不变')

    def test_missing_source_does_not_use_management(self):
        result=calculate({'price':100},{'eps':5,'basis':'ntm_4q'},None,
                         management={'eps':9,'period':'未来12个月','source_url':''})
        self.assertEqual(result['eps_used'],5)
        self.assertIsNone(result['fair_price'])

    def test_expired_guidance_is_not_used(self):
        from datetime import timedelta
        now=datetime.now(timezone.utc)
        guidance={'eps':9,'period':'未来12个月','source_url':'https://example.com/ir',
                  'updated_at':(now-timedelta(days=181)).isoformat()}
        result=calculate({'price':100},{'eps':5,'basis':'ntm_4q'},
                         {'trailing_pe':20,'fetched_at':now.isoformat()},management=guidance,now=now)
        self.assertEqual(result['eps_used'],5)


if __name__=='__main__':unittest.main()
