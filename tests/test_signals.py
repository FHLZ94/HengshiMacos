import unittest

from signals import analyze_history, flow_proxy, scenario


class SignalTests(unittest.TestCase):
    def history(self, closes, volumes):
        return {'ticker':'QQQ','bars':[{'date':f'2026-10-{i+1:02d}','open':c,'high':c+2,'low':c-2,
                                       'close':c,'volume':v} for i,(c,v) in enumerate(zip(closes,volumes))]}

    def test_short_history_has_no_signal(self):
        self.assertIsNone(analyze_history(self.history([10]*10,[100]*10)))
        self.assertIsNone(analyze_history({'ticker':'^VIX','bars':[{'date':'2026-10-01','close':20}]*30}))

    def test_uptrend_with_volume_has_conditional_action(self):
        closes=[100+i for i in range(21)]
        volumes=[100]*20+[160]
        result=analyze_history(self.history(closes,volumes))
        self.assertEqual(result['trend'],'上行')
        advice=scenario(result)
        self.assertEqual(advice['action'],'回撤买入候选')
        self.assertIn('20日低点',advice['invalidate'])
        self.assertEqual(len(advice['watch_zone']),2)
        self.assertIsNotNone(advice['buy_trigger'])

    def test_rebound_without_volume_is_not_institutional_flow(self):
        metric={'previous_change':-3,'previous_volume_ratio':1.8,'day_change':1.2,
                'volume_vs_previous':0.5,'close_position':0.8,'volume_ratio':1.0}
        self.assertIn('尚不能确认',flow_proxy(metric))

    def test_held_discounted_rebound_has_prices_and_risk_limit(self):
        metric={'price':106.0,'support20':100.0,'ma5':108.0,'ma20':115.0,
                'day_change':1.5,'close_position':0.75,'volume_ratio':1.4,
                'trend':'下行','return5':-8.0}
        advice=scenario(metric,held=True,fair_price=140.0,analyst_target=155.0)
        self.assertEqual(advice['action'],'分批加仓候选')
        self.assertEqual(advice['watch_zone'],[100.5,108.0])
        self.assertEqual(advice['buy_trigger'],108.0)
        self.assertLess(advice['risk_price'],metric['support20'])


if __name__=='__main__':
    unittest.main()
