import unittest
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import patch

import data_service
import main


class DataServiceTests(unittest.TestCase):
    def test_ticker_boundaries_and_aliases(self):
        watch=['ORCL','MRVL','MU','LITE']
        self.assertEqual(data_service.ticker_matches('Oracle expands datacenter capacity',watch),['ORCL'])
        self.assertEqual(data_service.ticker_matches('A big ultralight product',watch),[])
        self.assertEqual(data_service.ticker_matches('MRVL reports earnings',watch),['MRVL'])
        self.assertEqual(data_service.ticker_matches('DRAM demand rises',watch),[])
        self.assertEqual(data_service.ticker_matches('Micron raises guidance',watch),['MU'])

    def test_sector_leaders_link_to_smh_without_claiming_holdings(self):
        coverage=['SMH',*data_service.INTELLIGENCE_TICKERS]
        tickers=data_service.ticker_matches('NVIDIA raises AI chip guidance',coverage)
        self.assertIn('NVDA',tickers)
        self.assertNotIn('SMH',tickers)
        self.assertIn('SMH 行业相关',data_service.intelligence_topics(tickers))
        self.assertIn('存储',data_service.intelligence_topics([],'SK Hynix expands HBM memory'))

    def test_global_intelligence_filters_irrelevant_geopolitical_and_crime_stories(self):
        self.assertFalse(data_service.intelligence_relevant('Poland investigates a terror incident', 'national police inquiry', []))
        self.assertFalse(data_service.intelligence_relevant('Celebrity event draws attention', 'entertainment story', []))
        self.assertTrue(data_service.intelligence_relevant('Commerce Department tightens semiconductor export controls', 'AI chip supply chain policy', []))
        self.assertTrue(data_service.intelligence_relevant('Oracle expands AI datacenter capacity', 'capital expenditure guidance', ['ORCL']))

    def test_impact_words_do_not_match_inside_other_words(self):
        self.assertEqual(main.impact_level('Forward outlook for software'), '低')
        self.assertEqual(main.impact_level('War disrupts chip supply'), '高')

    def test_deduplicates_same_title_across_sources(self):
        row={'title':'Oracle raises guidance - Publisher A','summary':'','link':'https://a.example/1',
             'source':'A','published':'2026-11-07T00:00:00+00:00','impact':'中',
             'sentiment':62,'label':'偏正面','tickers':['ORCL']}
        other={**row,'title':'Oracle raises guidance - Publisher B','link':'https://b.example/2','source':'B'}
        with patch.object(data_service,'_feed',side_effect=[([row],{'source':'A','status':'ok'}),
                                                          ([other],{'source':'B','status':'ok'})]):
            rows,health=data_service.fetch_news([], [('A','https://a.example'),('B','https://b.example')],{},
                                                main.sentiment_score,main.impact_level)
        self.assertEqual(len(rows),1)
        self.assertEqual(len(health),2)
        self.assertEqual(set(rows[0]['independent_publishers']),{'A','B'})

    def test_offline_sources_return_visible_errors(self):
        with patch('data_service.requests.get',side_effect=data_service.requests.Timeout):
            rows,health=data_service.fetch_news([], [('Test','https://example.com/feed')],{},
                                                main.sentiment_score,main.impact_level)
        self.assertEqual(rows,[])
        self.assertEqual(health[0]['reason'],'连接超时')

    def test_source_update_time_is_not_used_as_publication_time(self):
        entry={'title':'Oracle raises guidance','link':'https://example.com/story',
               'updated':'Sun, 08 Nov 2026 03:00:00 GMT'}
        parsed=SimpleNamespace(entries=[entry],bozo=False)
        response=SimpleNamespace(content=b'<rss/>',raise_for_status=lambda:None)
        with patch('data_service.http_get',return_value=response),patch('data_service.feedparser.parse',return_value=parsed):
            rows,status=data_service._feed('测试来源','https://example.com/rss',{},main.sentiment_score,
                                           main.impact_level,['ORCL'])
        self.assertEqual(status['status'],'ok')
        self.assertEqual(rows[0]['published'],'')
        self.assertEqual(data_service.parse_date('2026-11-07T20:00:00+08:00'),'2026-11-07T12:00:00+00:00')

    def test_sp500_breadth_uses_valid_constituent_count(self):
        rows=[{'s':'NYSE:AAA','d':['AAA',101,100]},
              {'s':'NASDAQ:BBB','d':['BBB',90,100]},
              {'s':'NASDAQ:AAA','d':['AAA',101,100]}]
        with patch('data_service.calculate_sp500_breadth',wraps=data_service.calculate_sp500_breadth):
            with self.assertRaises(ValueError):
                data_service.calculate_sp500_breadth(rows,500)
        enough=[{'s':f'NYSE:T{i}','d':[f'T{i}',101 if i<250 else 90,100]} for i in range(450)]
        result=data_service.calculate_sp500_breadth(enough,500)
        self.assertEqual(result['valid'],450)
        self.assertEqual(result['above_20d'],250)

    def test_closed_quote_uses_same_day_historical_close(self):
        quote={'ticker':'ORCL','price':116.01,'change':.74,'asof':'Nov 6, 2026',
               'market_status':'Closed','price_label':'延迟最近成交'}
        history={'ticker':'ORCL','bars':[{'date':'2026-11-05','close':115.16},
                                         {'date':'2026-11-06','close':116.10}]}
        row=data_service.reconcile_closed_quotes([quote],[history])[0]
        self.assertEqual(row['price'],116.10)
        self.assertEqual(row['price_label'],'最近收盘')
        self.assertAlmostEqual(row['change'],.8163,places=3)
        stale={**history,'bars':[{'date':'2026-11-04','close':114},
                                 {'date':'2026-11-05','close':115.16}]}
        self.assertEqual(data_service.reconcile_closed_quotes([quote],[stale])[0]['price'],116.01)

    def test_no_calibrated_probability(self):
        regime=main.market_regime([],[])
        self.assertEqual(regime['label'],'数据不足')
        self.assertNotIn('probability',regime)

    def test_ntm_uses_four_future_quarters_and_rejects_gaps(self):
        periods=[{'fiscalEnd':date,'consensusEPSForecast':eps,'noOfEstimates':10,'up':0,'down':0}
                 for date,eps in [('Aug 2026',1.0),('Nov 2026',1.5),('Feb 2027',1.6),
                                  ('May 2027',1.8),('Aug 2027',2.0)]]
        result=data_service.select_ntm_forecast(periods,datetime(2026,11,7,tzinfo=timezone.utc))
        self.assertEqual(result['eps'],6.9)
        self.assertEqual(result['period'],'Nov 2026 - Aug 2027')
        self.assertIsNone(data_service.select_ntm_forecast(periods[:3],datetime(2026,11,7,tzinfo=timezone.utc)))


if __name__=='__main__':
    unittest.main()
