import unittest
from datetime import date,timedelta,datetime,timezone
from zoneinfo import ZoneInfo
from unittest.mock import patch
from market_model import analyze_market,analyze_single_security,completed_daily_bars,history_key,live_price_position


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

    def test_live_position_uses_latest_quote_without_mutating_daily_history(self):
        history=self.make_history('QQQ',[100+i*.02+((i%13)-6)*.3 for i in range(500)])
        original=history['bars'][-1]['close']
        low=live_price_position(history,history['bars'][-1]['close']*.9,history['bars'][-1]['date'])
        high=live_price_position(history,history['bars'][-1]['close']*1.1,history['bars'][-1]['date'])
        self.assertTrue(low['available']);self.assertTrue(high['available'])
        self.assertLess(low['percentile'],high['percentile'])
        self.assertEqual(history['bars'][-1]['close'],original)

    def test_single_security_daily_model_excludes_unfinished_current_session(self):
        history=self.make_history('ORCL',[100+i*.03+((i%11)-5)*.2 for i in range(260)])
        history['bars'][-1]['date']='2026-11-17'
        history['bars'][-2]['date']='2026-11-16'
        current=datetime(2026,11,17,15,0,tzinfo=ZoneInfo('America/New_York'))
        with patch('market_model.datetime') as mocked:
            mocked.now.return_value=current
            result=analyze_single_security(history)
        self.assertEqual(result['date'],'2026-11-16')

    def test_daily_model_key_ignores_an_unfinished_current_day_bar(self):
        current=datetime(2026,11,17,15,0,tzinfo=ZoneInfo('America/New_York'))
        histories=[self.make_history(ticker,[100+i*.1 for i in range(320)])
                   for ticker in ('QQQ','SPY','SMH','^VIX')]
        for history in histories:history['bars'][-1]['date']='2026-11-17'
        with patch('market_model.datetime') as mocked:
            mocked.now.return_value=current
            before=history_key(histories)
            histories[0]['bars'][-1]['close']*=1.2
            after=history_key(histories)
            self.assertEqual(before,after)
            self.assertEqual(completed_daily_bars(histories[0]['bars'])[-1]['date'],
                             histories[0]['bars'][-2]['date'])


if __name__=='__main__':unittest.main()
