"""Editable tracking, independent benchmarks, and compatible earnings scenarios."""
import copy
import gc
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
import data_service
import main
import securities
import valuation
import fund_valuation
from desktop import DesktopAPI


@contextmanager
def profile():
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder)
        with patch.object(main,'APP_DIR',root),patch.object(main,'DB',root/'events.sqlite3'),patch.object(main,'CONFIG',root/'settings.json'),patch.object(DesktopAPI,'refresh',lambda s:None),patch.object(DesktopAPI,'_scheduler',lambda s:None),patch.object(DesktopAPI,'_start_translation',lambda s:None),patch.object(DesktopAPI,'_start_model',lambda s,**k:None):
            main.init_db()
            yield root
        gc.collect()


def quote(ticker,price=100):
    return {'ticker':ticker,'name':ticker,'price':price,'change':1,'asof':'2026-11-06',
            'fetched_at':datetime.now(timezone.utc).isoformat(),'target_price':150,
            'source':'Nasdaq','market_status':'Closed','session':'regular'}


class TrackingTests(unittest.TestCase):
    def test_seed_has_twelve_cards_with_goog_c_and_independent_qqq(self):
        with profile():
            api=DesktopAPI();state=api.get_state()
            codes=[r['ticker'] for r in state['actions']]
            self.assertEqual(len(codes),12);self.assertEqual(codes[0],'VGT')
            self.assertIn('GOOG',codes);self.assertIn('SKHY',codes);self.assertNotIn('GOOGL',codes)
            self.assertNotIn('QQQ',codes);self.assertIn('QQQ',api._quote_tickers())

    def test_upgrade_is_once_and_deleted_defaults_do_not_reappear(self):
        old={'watchlist':['QQQ','SPY','ORCL','NVDA','^VIX']}
        first=securities.migrate_settings(old)
        self.assertEqual(first['watchlist'][0],'VGT');self.assertIn('GOOG',first['watchlist'])
        first['watchlist'].remove('SKHY');first['watchlist'].remove('VGT')
        again=securities.migrate_settings(first)
        self.assertNotIn('SKHY',again['watchlist']);self.assertNotIn('VGT',again['watchlist'])
        self.assertIn('NVDA',again['watchlist'])

    def test_adding_valid_symbol_persists_identity_and_starts_targeted_sync(self):
        with profile():
            api=DesktopAPI();q=quote('AAPL')
            resolved={'ok':True,'ticker':'AAPL','quote':q,'security':{'name':'Apple Inc.','asset_type':'stocks','exchange':'NASDAQ','currency':'USD'}}
            with patch('data_service.resolve_security',return_value=resolved) as resolver,patch.object(api,'_sync_tracking_async') as sync:
                result=api.add_tracking(' aapl ')
                self.assertTrue(result['ok']);sync.assert_called_once_with('AAPL')
                self.assertIn('AAPL',main.load_settings()['watchlist'])
                self.assertEqual(api.get_state()['watch'][-1]['price'],100)
                self.assertFalse(api.add_tracking('AAPL')['ok']);self.assertEqual(resolver.call_count,1)

    def test_invalid_identity_does_not_create_empty_tracking_card(self):
        with profile():
            api=DesktopAPI();original=list(api.settings['watchlist'])
            with patch('data_service.resolve_security',return_value={'ok':False,'message':'未找到代码'}):
                self.assertFalse(api.add_tracking('NOTREAL')['ok'])
            self.assertEqual(api.settings['watchlist'],original)
            with patch('data_service.resolve_security') as resolver:
                self.assertFalse(api.add_tracking('<script>')['ok']);resolver.assert_not_called()

    def test_remove_preserves_position_and_reload_does_not_restore_deleted_card(self):
        with profile():
            main.save_position('ORCL',2,100);main.save_snapshot([quote('ORCL')],[])
            api=DesktopAPI();self.assertTrue(api.remove_tracking('ORCL')['ok'])
            self.assertEqual(main.load_positions()[0]['quantity'],2)
            self.assertIn('ORCL',api._quote_tickers())
            state=DesktopAPI().get_state()
            self.assertNotIn('ORCL',[x['ticker'] for x in state['actions']])
            self.assertEqual(state['portfolio'][0]['price'],100)

    def test_added_security_values_update_before_news_finishes(self):
        with profile():
            api=DesktopAPI();gate=threading.Event();now=datetime.now(timezone.utc).isoformat()
            q={**quote('NVDA'),'reported_ttm_eps':5};e={'ticker':'NVDA','eps':5,'period':'Dec 2026 - Sep 2027','basis':'ntm_4q','fetched_at':now}
            resolved={'ok':True,'ticker':'NVDA','quote':q,'security':{'name':'NVIDIA','asset_type':'stocks','exchange':'NASDAQ','currency':'USD'}}
            def news(*args):gate.wait(2);return [],[]
            with patch('data_service.resolve_security',return_value=resolved),patch('data_service.fetch_quotes',return_value=([q],[])),patch('data_service.fetch_estimates',return_value=([e],[])),patch('data_service.fetch_histories',return_value=([],[])),patch('data_service.fetch_comparison',return_value=([{'ticker':'NVDA','target_median':150,'fetched_at':now}],{'source':'test','status':'ok'})),patch('data_service.search_news',side_effect=news):
                self.assertTrue(api.add_tracking('NVDA')['ok'])
                deadline=time.monotonic()+2
                while not (any(x['ticker']=='NVDA' for x in api.estimates) and any(x['ticker']=='NVDA' for x in api.comparisons)) and time.monotonic()<deadline:time.sleep(.01)
                row=next(r for r in api.get_state()['watch'] if r['ticker']=='NVDA')
                self.assertEqual(row['analyst_target'],150);self.assertEqual(row['current_pe'],20)
                self.assertEqual(api.tracking_sync['NVDA'],'正在更新')
                gate.set()
                while api.tracking_sync['NVDA']=='正在更新' and time.monotonic()<deadline:time.sleep(.01)
                self.assertNotEqual(api.tracking_sync['NVDA'],'正在更新')

    def test_dynamic_etf_is_not_sent_to_company_earnings_endpoint(self):
        cfg={'securities':{'TESTETF':{'asset_type':'etf','exchange':'NYSE Arca'}}}
        self.assertTrue(securities.is_fund('TESTETF',cfg))
        self.assertEqual(securities.tv_symbol('TESTETF',cfg),'AMEX:TESTETF')
        with patch('data_service._estimate') as estimate:
            rows,_=data_service.fetch_estimates(['TESTETF','VGT'],cfg)
            self.assertEqual(rows,[]);estimate.assert_not_called()

    def test_previous_full_refresh_cannot_hide_newly_added_security(self):
        with profile():
            api=DesktopAPI();old=copy.deepcopy(api.settings)
            api.settings['watchlist'].append('NVDA');main.save_settings(api.settings)
            main.save_snapshot([quote('NVDA')],[])
            with patch('data_service.fetch_session_quotes',return_value=([],{})),patch('main.fetch_quotes',return_value=([],[])),patch('data_service.fetch_histories',return_value=([],[])),patch('data_service.fetch_estimates',return_value=([],[])),patch('fund_valuation.fetch_fund_valuations',return_value=({},[])),patch('reference_data.fetch_histories',return_value=({},[])),patch('data_service.fetch_comparison',return_value=([],{})),patch('data_service.fetch_cnn_fear_greed',return_value=(None,None)),patch('data_service.fetch_sp500_breadth',return_value=(None,None)),patch('main.fetch_news',return_value=([],[])):
                api._refresh_worker(old)
            row=next(r for r in api.get_state()['watch'] if r['ticker']=='NVDA')
            self.assertEqual(row['price'],100)

    def test_loss_accounting_pe_is_not_used_as_positive_valuation_multiple(self):
        now=datetime.now(timezone.utc)
        q={**quote('LITE',540.32),'reported_ttm_eps':-77.94,'reported_trailing_pe':-6.91}
        e={'eps':22.85,'basis':'ntm_4q','fetched_at':now.isoformat(),'reported_eps_ttm':9.52,
           'reported_basis':'nasdaq_earnings_surprise','reported_period':'Dec 2025 - Sep 2026'}
        r=valuation.calculate(q,e,None,now=now)
        self.assertIsNone(r['current_pe'])
        self.assertIn('亏损',r['pe_status'])
        self.assertIsNone(r['reference_price'])
        r=valuation.calculate(q,e,{'target_median':1100,'fetched_at':now.isoformat()},now=now)
        self.assertEqual(r['reference_price'],1100)
        self.assertEqual(r['reference_method'],'analyst_median')

    def test_reported_quarters_need_four_consecutive_already_published_periods(self):
        now=datetime(2026,11,8,tzinfo=timezone.utc)
        rows=[{'fiscalQtrEnd':p,'dateReported':d,'eps':v} for p,d,v in
              [('Sep 2026','11/2/2026',3.76),('Jun 2026','8/11/2026',2.64),('Mar 2026','5/5/2026',1.88),('Dec 2025','2/3/2026',1.24)]]
        self.assertEqual(data_service.select_reported_eps(rows,now)['reported_eps_ttm'],9.52)
        self.assertIsNone(data_service.select_reported_eps(rows[:3],now))
        rows[0]['dateReported']='11/20/2026'
        self.assertIsNone(data_service.select_reported_eps(rows,now))

    def test_a_loss_quarter_does_not_hide_positive_twelve_month_earnings(self):
        rows=[{'fiscalEnd':p,'consensusEPSForecast':v,'noOfEstimates':5,'up':0,'down':0}
              for p,v in [('Dec 2026',-.1),('Mar 2027',.2),('Jun 2027',.2),('Sep 2027',.3)]]
        self.assertAlmostEqual(data_service.select_ntm_forecast(rows,datetime(2026,11,8,tzinfo=timezone.utc))['eps'],.6)

    def test_vgt_issuer_pe_needs_matching_fund_and_keeps_report_date(self):
        text='Vanguard Information Technology ETF | VGT As of September 30, 2026 Price/earnings ratio 32.8x 32.8x'
        now=datetime(2026,11,8,tzinfo=timezone.utc)
        result=fund_valuation.parse_vanguard_vgt(text,now)
        self.assertEqual(result['pe'],32.8);self.assertEqual(result['asof'],'2026-09-30')
        self.assertIsNone(result['percentile'])
        with self.assertRaises(ValueError):fund_valuation.parse_vanguard_vgt(text.replace('| VGT','| VOO'),now)

    def test_dynamic_company_name_links_news_without_a_literal_ticker(self):
        cfg={'securities':{'AAPL':{'name':'Apple Inc. Common Stock'}}}
        self.assertIn('AAPL',data_service.ticker_matches('Apple raises its revenue forecast',['AAPL'],cfg))
        self.assertIn('SKHY',data_service.ticker_matches('SK Hynix raises HBM output',['SKHY']))

    def test_smh_issuer_pe_has_report_date_and_never_invents_history_percentile(self):
        report='SMH VanEck Semiconductor ETF As of October 31, 2026 Price/Earnings Ratio* 28.46'
        value=fund_valuation.parse_vaneck_smh(report,datetime(2026,11,8,tzinfo=timezone.utc))
        self.assertEqual(value['pe'],28.46);self.assertEqual(value['asof'],'2026-10-31')
        self.assertIsNone(value['percentile'])


if __name__=='__main__':unittest.main()
