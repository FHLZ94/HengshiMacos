import unittest
from datetime import datetime, timezone

from event_intelligence import assess, classify_materiality, key_facts, price_reaction


class EventIntelligenceTests(unittest.TestCase):
    def test_related_story_does_not_override_primary_trade(self):
        title='Linden Rose Investment LLC Purchases 12,700 Shares of Intel'
        lead=('Linden Rose Investment LLC purchased 12,700 shares of Intel stock. '
              'The filing described a 0.8% ownership stake. ')
        other=('Management also discusses earnings outlook. CEO Tan bought 150,000 shares '
               'for $9.7 million at an average price of $64 per share. ')
        body=lead+('Other background unrelated to this filing. '*75)+other
        facts=key_facts(body,title)
        self.assertEqual(facts['share_count'],'12,700 shares')
        self.assertIsNone(facts['purchase_price'])
        self.assertEqual(classify_materiality(title,body),'股权交易')

    def test_portfolio_weight_is_not_company_ownership(self):
        body=('Linden Rose Investment LLC acquired a new stake in Intel. '
              'The institutional investor acquired 12,700 shares, valued at $1,527,000. '
              'Intel accounts for about 1.3% of its investment portfolio. ')
        facts=key_facts(body,'Linden Rose Investment LLC Purchases 12,700 Shares of Intel')
        self.assertEqual(facts['share_count'],'12,700 shares')
        self.assertEqual(facts['portfolio_weight_pct'],'1.3%')
        self.assertIsNone(facts['ownership_pct'])
        self.assertIsNone(facts['purchase_price'])

    def test_missing_trade_details_are_not_printed(self):
        article={'title':'Fund bought shares of Intel','summary':'','source':'Test',
                 'label':'中性','published':datetime.now(timezone.utc).isoformat(),
                 'tickers':['INTC'],'independent_publishers':['Test']}
        result=assess(article,'Fund bought shares of Intel. '+('More background. '*30),
                      'https://example.com/story',None,[])
        self.assertNotIn('未提及',result['conclusion'])
        self.assertNotIn('持股比例',result['conclusion'])

    def test_after_close_news_waits_for_next_session(self):
        article={'published':'2026-11-06T22:00:00+00:00','tickers':['ORCL']}
        history=[{'ticker':'ORCL','bars':[{'date':'2026-11-05','close':100,'low':98},
                                             {'date':'2026-11-06','close':101,'low':99}]}]
        self.assertEqual(price_reaction(article,history)['status'],'事件后尚无可用收盘数据')

    def test_denied_contract_collapse_is_not_negative_confirmation(self):
        article={'title':'Oracle denies Microsoft data center deal collapsed',
                 'summary':'Oracle says the wider agreement remains on track',
                 'source':'Data Center Dynamics','publisher':'Data Center Dynamics',
                 'label':'偏负面','published':datetime.now(timezone.utc).isoformat(),
                 'tickers':['ORCL'],'independent_publishers':['Data Center Dynamics']}
        body=('Oracle denies reports that its Microsoft data center deal collapsed. '
              'The company says the wider AI infrastructure agreement is still on track. ')*5
        result=assess(article,body,'https://example.com/oracle',None,[])
        self.assertEqual(result['event_type'],'合同变化')
        self.assertEqual(result['direction'],'事实争议，待核验')
        self.assertIn('不能把单一项目调整',result['conclusion'])


if __name__=='__main__': unittest.main()
