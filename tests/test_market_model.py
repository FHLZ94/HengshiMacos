import unittest
from datetime import date,timedelta
from market_model import analyze_market


class MarketModelTests(unittest.TestCase):
    def make_history(self,ticker,values):
        start=date(2023,1,2)
        bars=[]
        for index,value in enumerate(values):
            day=(start+timedelta(days=index)).isoformat()
            bars.append({'date':day,'open':value,'high':value+1,'low':value-1,
                         'close':value,'volume':1000+(index%7)*30})
        return {'ticker':ticker,'bars':bars}

    def test_insufficient_history_does_not_publish_probability(self):
        histories=[self.make_history(ticker,[100+i*.1 for i in range(100)])
                   for ticker in ('QQQ','SPY','SMH','^VIX')]
        result=analyze_market(histories)
        self.assertFalse(result['available'])

    def test_market_targets_include_spy_and_orcl_with_own_history_methods(self):
        values=[100+i*.04+((i%31)-15)*.4 for i in range(800)]
        histories=[self.make_history(ticker,[value*(1+offset) for value in values])
                   for ticker,offset in [('QQQ',0),('SPY',.1),('SMH',.3),('^VIX',-.8)]]
        histories.append(self.make_history('ORCL',[90+i*.03+((i%17)-8)*.6 for i in range(800)]))
        result=analyze_market(histories)
        self.assertEqual(set(('QQQ','SPY','SMH','ORCL')),set(result['targets']))
        self.assertEqual(result['targets']['ORCL']['up5']['method'],'标的自身历史频率')
        self.assertGreater(result['targets']['SPY']['training_samples'],0)

    def test_probability_has_samples_and_chronological_validation(self):
        values=[100+i*.04+((i%31)-15)*.4 for i in range(800)]
        histories=[self.make_history(ticker,[value*(1+offset) for value in values])
                   for ticker,offset in [('QQQ',0),('SPY',.1),('SMH',.3),('^VIX',-.8)]]
        result=analyze_market(histories)
        self.assertTrue(result['available'])
        self.assertGreaterEqual(result['samples'],30)
        self.assertGreater(result['validation_count'],0)
        self.assertTrue(0<=result['up5_pct']<=100)
        self.assertLessEqual(result['up5_interval'][0],result['up5_pct'])
        self.assertGreaterEqual(result['up5_interval'][1],result['up5_pct'])


if __name__=='__main__':unittest.main()
