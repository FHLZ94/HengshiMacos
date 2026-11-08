"""Regression coverage for research estimates, session prices and sector rotation."""
import copy
import gc
from datetime import date, datetime, timedelta, timezone
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path
import numpy as np
import data_service
import fund_valuation
import main
import market_model
from desktop import DesktopAPI, current_price_gap
from sector_rotation import rotation
from investment_reference import annual_reference


class ResearchRevisionTests(unittest.TestCase):
    def history(self,ticker,n=800):
        rng=np.random.default_rng(12)
        closes=100*np.exp(np.cumsum(rng.normal(.0003,.015,n)))
        start=date(2020,1,1)
        return {'ticker':ticker,'fetched_at':'2026-11-08T00:00:00+00:00','bars':[
            {'date':(start+timedelta(days=i)).isoformat(),'open':float(c),
             'close':float(c),'low':float(c*.98),'high':float(c*1.02),'volume':1000+i%7*100}
            for i,c in enumerate(closes)]}

    def test_after_hours_is_not_overwritten_by_close_or_stale_trade(self):
        row={'ticker':'AVGO','price':293.69,'asof':'Nov 6, 2026','market_status':'Closed'}
        ext={'ticker':'AVGO','price':295.27,'asof':'2026-11-06','session':'post','market_status':'Closed'}
        merged=data_service.merge_session_quote(row,ext)
        self.assertEqual(merged['price'],295.27)
        self.assertEqual(data_service.merge_session_quote(row,{**ext,'asof':'2026-11-05'})['price'],293.69)
        bars={'ticker':'AVGO','bars':[{'date':'2026-11-05','close':291.53},{'date':'2026-11-06','close':293.69}]}
        self.assertEqual(data_service.reconcile_closed_quotes([merged],[bars])[0]['price'],295.27)

    def test_premarket_must_not_replace_same_day_active_regular_trade(self):
        regular={'ticker':'MU','price':100,'asof':'2026-11-06','market_status':'Open'}
        pre={'ticker':'MU','price':95,'asof':'2026-11-06','session':'pre'}
        self.assertEqual(data_service.merge_session_quote(regular,pre)['price'],100)
        self.assertEqual(data_service.merge_session_quote(regular,{**pre,'asof':'2026-11-09'})['price'],95)

    def test_session_parser_checks_market_date_and_regular_session_state(self):
        base={'symbol':'AVGO','last':'293.69','previous_day_closing':'291.53',
              'last_timedate':'11/06/26 EST','curmktstatus':'POST_MKT',
              'ExtendedMktQuote':{'type':'POST_MKT','last':'295.27','last_time':'2026-11-06'}}
        parsed=data_service.parse_session_quotes([base],['AVGO'],'now')[0]
        self.assertEqual(parsed['price'],295.27)
        self.assertEqual(parsed['regular_close'],293.69)
        base['ExtendedMktQuote']['last_time']='2026-11-05'
        self.assertEqual(data_service.parse_session_quotes([base],['AVGO'],'now')[0]['price'],293.69)
        base['ExtendedMktQuote']['last_time']='2026-11-06';base['curmktstatus']='REG_MKT'
        self.assertEqual(data_service.parse_session_quotes([base],['AVGO'],'now')[0]['price'],293.69)

    def test_comparison_uses_same_session_close(self):
        now=datetime.now(timezone.utc).isoformat()
        q={'price':110,'regular_close':100,'session':'post','fetched_at':now}
        self.assertAlmostEqual(current_price_gap(q,{'price':100,'fetched_at':now}),0)

    def test_sparse_history_still_has_honest_baseline_not_fabricated_model(self):
        h=[self.history(t,400) for t in ('QQQ','SPY','SMH','^VIX')]
        r=market_model.analyze_market(h)
        self.assertTrue(r['available']);self.assertEqual(r['up5']['method'],'历史基准收缩')
        self.assertGreater(r['up5_pct'],0);self.assertLess(r['up5_pct'],100)
        self.assertEqual(r['up5']['validation_count'],0)

    def test_feature_vectors_cannot_see_future_bars(self):
        h=[self.history(t,800) for t in ('QQQ','SPY','SMH','^VIX')]
        rows=market_model._prepare(h);changed=copy.deepcopy(rows)
        for row in changed[601:]: row['qqq']['close']*=3;row['vix']*=3
        np.testing.assert_allclose(market_model._features(rows,600),market_model._features(changed,600))

    def test_walk_forward_scaling_and_labels_only_use_known_prefix(self):
        rng=np.random.default_rng(2);x=rng.normal(size=(1000,14));y=(rng.random(1000)>.45).astype(float)
        recorded=[];fit=market_model._fit
        def observe(a,b,penalty=35):
            if a.shape[1]==14:recorded.append((len(a),a[0].copy(),a[-1].copy(),b.copy()))
            return fit(a,b,penalty)
        with patch('market_model._fit',side_effect=observe):market_model._forecast(x,y,5)
        self.assertGreater(len(recorded),3)
        self.assertEqual(recorded[0][0],505)
        np.testing.assert_allclose(recorded[0][2],x[504])
        # Altering labels not yet known to the first fold cannot alter its fit.
        changed=y.copy();changed[505:]=1-changed[505:]
        first=market_model._fit(x[:505],y[:505]);other=market_model._fit(x[:505],changed[:505])
        np.testing.assert_allclose(first[2],other[2])

    def test_pe_percentile_uses_pe_samples_not_price_range(self):
        history=[{'date':f'{year}-{month:02d}-01','pe':10+(year-2015)*2+month/12}
                 for year in range(2015,2027) for month in range(1,13)]
        r=fund_valuation.percentile({'asof':'2026-11-06','pe':20,'history':history})
        self.assertEqual(r['samples'],120);self.assertGreater(r['percentile'],0);self.assertLess(r['percentile'],100)
        short=fund_valuation.percentile({'asof':'2026-11-06','pe':20,'history':history[-10:]})
        self.assertIsNone(short['percentile'])

    def test_rotation_is_signed_volume_pressure_and_benchmarked(self):
        h=[self.history(t,100) for t in ('SPY','SMH','XLV','XLP','XLU','XLF','XLK')]
        for item in h:
            if item['ticker']=='XLV':
                for b in item['bars']:b['close']=b['high']
            if item['ticker']=='SMH':
                for b in item['bars']:b['close']=b['low']
        r=rotation(h,5)
        by={x['ticker']:x for x in r['rows']}
        self.assertEqual(by['XLV']['pressure'],100)
        self.assertEqual(by['SMH']['pressure'],-100)
        self.assertIn('真实资金',r['definition'])

    def test_annual_historical_overlap_is_not_claimed_as_calibrated_probability(self):
        h=self.history('AVGO',2200)
        r=annual_reference(h,100,[90,100],130)
        self.assertTrue(r['available']);self.assertFalse(r['calibrated'])
        self.assertLess(r['independent_periods'],r['samples'])
        self.assertEqual(r['valuation_range'],[30.0,44.4])

    def test_offline_refresh_recalculates_before_network_finishes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch.object(main,'APP_DIR',root),patch.object(main,'DB',root/'events.sqlite3'),patch.object(main,'CONFIG',root/'settings.json'),patch.object(DesktopAPI,'_scheduler',lambda s:None),patch.object(DesktopAPI,'_refresh_worker',lambda s,c:None),patch.object(DesktopAPI,'_start_translation',lambda s:None):
                main.init_db()
                h=[self.history(t,400) for t in ('QQQ','SPY','SMH','^VIX')]
                main.save_snapshot([],[],histories=h)
                api=DesktopAPI()
                deadline=time.monotonic()+3
                while api.model_busy and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(api._model_result['available'])
                original_revision=api.revision
                api.refresh() # busy network group intentionally remains pending
                while api.model_busy and time.monotonic()<deadline:time.sleep(.01)
                self.assertGreater(api.revision,original_revision)
                self.assertTrue(api._model_result['available']);self.assertTrue(api.busy)
            gc.collect()

    def test_short_refresh_preserves_long_history_and_later_session_price(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch.object(main,'DB',root/'events.sqlite3'):
                main.init_db();h=self.history('QQQ',800)
                extended={'ticker':'AVGO','price':295.27,'asof':'2026-11-06',
                          'session':'post','market_status':'Closed','fetched_at':'2026-11-08T00:00:00+00:00'}
                main.save_snapshot([extended],[],histories=[h])
                main.save_snapshot([{**extended,'price':293.69,'session':'regular'}],[],
                                   histories=[{**h,'bars':h['bars'][-21:]}])
                self.assertEqual(len(main.load_histories(['QQQ'])[0]['bars']),800)
                self.assertEqual(main.load_snapshot(['AVGO'])[1][0]['price'],295.27)
            gc.collect()

    def test_unfinished_us_daily_bar_is_excluded_from_model(self):
        h=[self.history(t,400) for t in ('QQQ','SPY','SMH','^VIX')]
        for item in h:
            item['bars'][-2]['date']='2026-11-05';item['bars'][-1]['date']='2026-11-06'
        with patch('market_model.datetime') as dt:
            dt.now.return_value=datetime(2026,11,6,18,tzinfo=timezone.utc)
            self.assertEqual(market_model._prepare(h)[-1]['date'],'2026-11-05')
            dt.now.return_value=datetime(2026,11,6,23,tzinfo=timezone.utc)
            self.assertEqual(market_model._prepare(h)[-1]['date'],'2026-11-06')


if __name__=='__main__':unittest.main()
