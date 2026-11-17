import unittest,math
from unittest.mock import patch
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

    def test_extended_hours_are_aggregated_as_separate_sessions(self):
        start=datetime(2026,11,2,4,0,tzinfo=ZoneInfo('America/New_York'))
        bars=[]
        for session,clock,count in (('盘前',(4,0),22),('常规',(9,30),26),('盘后',(16,0),16)):
            base=start.replace(hour=clock[0],minute=clock[1])
            for index in range(count):
                stamp=int((base+timedelta(minutes=index*15)).timestamp())
                close=100+index*.01
                bars.append({'time':stamp,'end':stamp+900,'session':session,'open':close,
                    'high':close+.5,'low':close-.5,'close':close,'volume':1000})
        hourly=intraday_signals.resample(bars,60)
        self.assertEqual(len(hourly),17)
        self.assertEqual({bar['session'] for bar in hourly},{'盘前','常规','盘后'})
        self.assertEqual(sum(bar['session_tail'] for bar in hourly),2)
    def test_unfinished_candle_is_excluded_from_provider_response(self):
        bars=self.sessions(5);current=bars[-1]
        p={'chart':{'result':[{'meta':{'symbol':'SMH'},'timestamp':[b['time'] for b in bars],
              'indicators':{'quote':[{k:[b[k] for b in bars] for k in ('open','high','low','close','volume')}]}}]}}
        now=datetime.fromtimestamp(current['time']+300,timezone.utc)
        h=intraday_signals.parse_chart(p,'SMH',now)
        self.assertLess(h['bars'][-1]['time'],current['time'])
        self.assertTrue(all(b['time']+900<=now.timestamp() for b in h['bars']))

    def test_chart_parser_keeps_completed_premarket_and_postmarket_bars(self):
        bars=[]
        for day in (datetime(2026,11,2,tzinfo=ZoneInfo('America/New_York')),
                    datetime(2026,11,3,tzinfo=ZoneInfo('America/New_York'))):
            for hour,minute,count,session in ((4,0,22,'盘前'),(9,30,26,'常规'),(16,0,16,'盘后')):
                base=day.replace(hour=hour,minute=minute)
                for index in range(count):
                    stamp=int((base+timedelta(minutes=index*15)).timestamp());close=100+index*.01
                    bars.append({'time':stamp,'session':session,'open':close,'high':close+.5,
                                 'low':close-.5,'close':close,'volume':1000})
        payload={'chart':{'result':[{'meta':{'symbol':'SMH'},'timestamp':[bar['time'] for bar in bars],
            'indicators':{'quote':[{key:[bar[key] for bar in bars]
                for key in ('open','high','low','close','volume')}]}}]}}
        now=bars[-1]['time']+3600
        parsed=intraday_signals.parse_chart(payload,'SMH',datetime.fromtimestamp(now,timezone.utc))
        self.assertEqual(len(parsed['bars']),128)
        self.assertEqual({bar['session'] for bar in parsed['bars']},{'盘前','常规','盘后'})

    def test_rsi1_preserves_two_decimal_precision_for_dashboard(self):
        bars=[{**bar,'end':bar['time']+900} for bar in self.sessions()]
        values=[None]*(len(bars)-1)+[27.726]
        with patch('intraday_signals.wilder_rsi',return_value=values):
            result=intraday_signals.frame(bars,15)
        self.assertEqual(result['rsi1'],27.73)
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

    def test_rsi_only_divergence_cannot_confirm_macd(self):
        bars=self.double_bottom()
        rsi,dif,hist=intraday_signals.indicators(bars)
        with patch('intraday_signals.indicators',return_value=(rsi,[-1.0]*len(bars),hist)):
            result=intraday_signals.frame(bars,30)
        self.assertFalse(result['confirmed']);self.assertFalse(result['candidate'])

    def test_thirty_minute_core_controls_structure_even_if_fifteen_confirms(self):
        empty={'available':True,'confirmed':False,'candidate':False,'top_confirmed':False,
               'top_candidate':False,'absorption':'承接偏弱','minutes':30}
        def make_frame(bars,minutes):
            return {**empty,'minutes':minutes,'confirmed':minutes==15}
        with patch('intraday_signals.frame',side_effect=make_frame):
            result=intraday_signals.analyze({'ticker':'SMH','bars':self.sessions()})
        self.assertEqual(result['primary'],'15分底背离确认')
        self.assertEqual(result['bottom_score'],40)
        self.assertEqual(result['weights']['15'],.4)
        self.assertIsNone(result['formation']['probability_pct'])

    def test_five_and_fifteen_minute_rsi_control_short_term_signal(self):
        def make_frame(bars,minutes):
            return {'available':True,'minutes':minutes,'bars':100,'rsi1':{5:27.72,15:29.4,30:45.2,60:51.1}[minutes],
                    'confirmed':False,'candidate':False,'top_confirmed':False,'top_candidate':False,
                    'absorption':'承接偏弱','asof':'2026-11-17T15:00:00-05:00'}
        with patch('intraday_signals.frame',side_effect=make_frame), \
             patch('intraday_signals.confirmation_reference',return_value={'available':False,'probability_pct':None}):
            result=intraday_signals.analyze({'ticker':'QQQ','bars':self.sessions(),'bars5':self.sessions()})
        self.assertEqual((result['rsi_5'],result['rsi_15'],result['rsi_30']),(27.72,29.4,45.2))
        self.assertEqual(result['rsi_signal'],'短线超卖，可小额关注')

    def test_rsi_pressure_weights_are_40_40_20_and_never_report_probability(self):
        values={5:20,15:35,30:80,60:50}
        def make_frame(bars,minutes):
            return {'available':True,'minutes':minutes,'bars':100,'rsi1':values[minutes],
                    'confirmed':False,'candidate':False,'top_confirmed':False,'top_candidate':False,
                    'absorption':'承接偏弱','asof':'2026-11-17T15:00:00-05:00'}
        with patch('intraday_signals.frame',side_effect=make_frame), \
             patch('intraday_signals.confirmation_reference',return_value={'available':False,'probability_pct':None}):
            result=intraday_signals.analyze({'ticker':'QQQ','bars':self.sessions(),'bars5':self.sessions()})
        self.assertEqual(result['rsi_weights'],{'5':.4,'15':.4,'30':.2})
        self.assertAlmostEqual(result['rsi_oversold_score'],.6)
        self.assertAlmostEqual(result['rsi_overbought_score'],.2)
        self.assertNotIn('rsi_probability',result)

    def test_existing_confirmed_shape_does_not_become_a_fake_100_percent_forecast(self):
        result=intraday_signals.confirmation_reference(self.double_bottom(),{'confirmed':True})
        self.assertEqual(result['status'],'confirmed');self.assertIsNone(result['probability_pct'])

    def test_too_few_candidate_episodes_do_not_generate_formation_probability(self):
        result=intraday_signals.confirmation_reference(self.double_bottom(),{'candidate':True})
        self.assertFalse(result['available']);self.assertIsNone(result['probability_pct'])

if __name__=='__main__':unittest.main()
