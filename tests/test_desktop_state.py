import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch

from desktop import DesktopAPI,current_price_gap,merge_news,quote_is_stale,quote_time_label,wilder_rsi


class DesktopStateTests(unittest.TestCase):
    def test_market_source_timestamp_is_converted_to_beijing_time(self):
        self.assertEqual(quote_time_label('2026-11-17T15:10:00-05:00'),'11-18 04:10 北京时间')
        self.assertEqual(quote_time_label('11/17/26 03:10 PM EST'),'11-18 04:10 北京时间')

    def test_quote_freshness_uses_source_time_and_requires_time_precision_while_open(self):
        now=datetime(2026,11,17,10,0,tzinfo=timezone(timedelta(hours=-5)))
        recent={'session':'regular','market_status':'Open','source_time':'2026-11-17T09:50:00-05:00'}
        old={**recent,'source_time':'2026-11-17T09:00:00-05:00'}
        date_only={**recent,'source_time':'2026-11-17'}
        self.assertFalse(quote_is_stale(recent,now))
        self.assertTrue(quote_is_stale(old,now))
        self.assertTrue(quote_is_stale(date_only,now))

    def test_price_conflict_requires_recent_sources(self):
        now=datetime.now(timezone.utc)
        quote={'price':100,'fetched_at':now.isoformat()}
        current={'price':104,'fetched_at':(now-timedelta(minutes=5)).isoformat()}
        stale={'price':104,'fetched_at':(now-timedelta(days=2)).isoformat()}
        self.assertAlmostEqual(current_price_gap(quote,current),4.0)
        self.assertIsNone(current_price_gap(quote,stale))

    def test_ui2_market_slots_are_validated_and_persisted(self):
        api=DesktopAPI.__new__(DesktopAPI)
        with tempfile.TemporaryDirectory() as folder, patch('desktop.main.APP_DIR',Path(folder)):
            self.assertEqual(api.get_market_slots()['slots'],['QQQ','SPY','SMH','ORCL'])
            saved=api.save_market_slots(['QQQ','SMH','ORCL','NVDA'])
            self.assertTrue(saved['ok'])
            self.assertEqual(api.get_market_slots()['slots'],['QQQ','SMH','ORCL','NVDA'])
            self.assertFalse(api.save_market_slots(['QQQ','QQQ'])['ok'])

    def test_ui2_custom_ticker_rsi_uses_cached_history(self):
        api=DesktopAPI.__new__(DesktopAPI)
        api.lock=threading.RLock()
        closes=[100+i for i in range(30)]
        api.histories=[{'ticker':'ORCL','bars':[{'date':f'2026-01-{i+1:02d}','close':close}
                                             for i,close in enumerate(closes)]}]
        result=api.get_market_rsi('ORCL','2026-01-30')
        self.assertTrue(result['ok'])
        self.assertEqual(result['rsi14'],100.0)
        self.assertEqual(result['bars'],30)
        self.assertIsNone(wilder_rsi(closes[:14]))

    def test_news_merge_prefers_official_source_and_preserves_corroboration(self):
        title='NVIDIA expands AI datacenter optical deployment'
        old={'title':title,'link':'https://news.google.com/story','source':'Google News · AI infrastructure',
             'publisher':'CNBC','published':'2026-11-10T12:00:00+00:00','independent_publishers':['CNBC']}
        primary={**old,'link':'https://developer.nvidia.com/story','source':'NVIDIA Developer · AI and GPU',
                 'publisher':'NVIDIA','published':'2026-11-10T11:00:00+00:00',
                 'independent_publishers':['NVIDIA']}
        merged=merge_news([old],[primary])
        self.assertEqual(merged[0]['source'],primary['source'])
        self.assertEqual(set(merged[0]['independent_publishers']),{'CNBC','NVIDIA'})


if __name__=='__main__':unittest.main()
