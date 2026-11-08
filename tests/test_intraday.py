import unittest,math
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import intraday_signals,market_model,event_risk

class IntradayTests(unittest.TestCase):
    def bars(self,closes):
        start=int(datetime(2026,11,2,14,30,tzinfo=timezone.utc).timestamp())
        return [{'time':start+i*900,'end':start+(i+1)*900,'open':c,'high':c+.5,'low':c-.5,'close':c,'volume':1000} for i,c in enumerate(closes)]
    def double_bottom(self):
        closes=[100.0]*40+[100-i*20/15 for i in range(1,16)]+[80+i*.5 for i in range(1,21)]+[90-i*1.1 for i in range(1,11)]+[79+i for i in range(1,7)]
        return self.bars(closes)
    def test_two_confirming_bars_are_needed_and_candidate_does_not_repaint_as_confirmed(self):
        bars=self.double_bottom();confirmed=intraday_signals.frame(bars,15)
        candidate=intraday_signals.frame(bars[:-6],15)
        self.assertTrue(confirmed['confirmed']);self.assertTrue(confirmed['evidence']['rsi_divergence'])
        self.assertGreaterEqual(confirmed['evidence']['bars_after'],2)
        self.assertFalse(candidate['confirmed']);self.assertTrue(candidate['candidate'])
    def test_top_divergence_is_the_directional_mirror(self):
        bottom=self.double_bottom();top=self.bars([200-b['close'] for b in bottom])
        result=intraday_signals.frame(top,15)
        self.assertTrue(result['top_confirmed']);self.assertFalse(result['confirmed'])
        self.assertGreater(result['top_evidence']['second_high'],result['top_evidence']['first_high'])
    def sessions(self,count=7):
        result=[];day=datetime(2026,10,19,9,30,tzinfo=ZoneInfo('America/New_York'))
        for d in range(count):
            while day.weekday()>4:day+=timedelta(days=1)
            for i in range(26):
                c=100+d*.1+i*.01
                result.append({'time':int((day+timedelta(minutes=i*15)).timestamp()),'open':c,'high':c+.5,'low':c-.5,'close':c,'volume':100 if i==25 else 10000})
            day+=timedelta(days=1)
        return result
    def test_volume_uses_same_clock_slot_not_the_intraday_u_shape(self):
        bars=self.sessions();bars[-1]['volume']=300
        result=intraday_signals.frame(intraday_signals.resample(bars,15),15)
        self.assertEqual(result['same_slot_volume_ratio'],3)
        self.assertEqual(result['volume_baselines'],6)
    def test_aggregation_never_bridges_sessions_and_labels_short_closing_bucket(self):
        bars=self.sessions(2);hourly=intraday_signals.resample(bars,60)
        self.assertEqual(len(hourly),14)
        self.assertTrue(hourly[-1]['session_tail'])
        self.assertEqual(hourly[-1]['end']-hourly[-1]['time'],1800)
        incomplete=intraday_signals.resample(bars[:2]+bars[3:],60)
        self.assertEqual(len(incomplete),13)
    def test_unfinished_candle_is_excluded_from_provider_response(self):
        bars=self.sessions(5);current=bars[-1]
        p={'chart':{'result':[{'meta':{'symbol':'SMH'},'timestamp':[b['time'] for b in bars],
              'indicators':{'quote':[{k:[b[k] for b in bars] for k in ('open','high','low','close','volume')}]}}]}}
        now=datetime.fromtimestamp(current['time']+300,timezone.utc)
        h=intraday_signals.parse_chart(p,'SMH',now)
        self.assertLess(h['bars'][-1]['time'],current['time'])
        self.assertTrue(all(b['time']+900<=now.timestamp() for b in h['bars']))
    def test_overbought_position_is_reported_as_well_as_oversold(self):
        from tests.test_unified_research import TwoMarketModelTests
        make=TwoMarketModelTests().history
        values=[100+math.sin(i/11)*.5 for i in range(700)];values[-1]=130
        h=[make(t,values if t!='^VIX' else [20]*700) for t in ('QQQ','SMH','SPY','^VIX')]
        result=market_model.analyze_market(h)
        setup=result['targets']['SMH']['setup']
        self.assertTrue(setup['overbought']);self.assertIn('超买',setup['label'])
        self.assertLessEqual(setup['upper_tail_pct'],1)
        risks=event_risk.assess_events([])
        environment=event_risk.trading_environment(result,risks)
        self.assertIn('避免追价',environment['SMH']['label'])

if __name__=='__main__':unittest.main()
