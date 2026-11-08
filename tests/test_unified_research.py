from datetime import datetime,timedelta,timezone
import unittest,copy,json,sqlite3
from unittest.mock import patch
import main,market_model,event_risk,public_intelligence
from desktop import DesktopAPI
from tests.test_tracking import profile,quote

class ConsistencyTests(unittest.TestCase):
    def test_same_reference_and_upside_in_cards_table_and_event_context(self):
        with profile():
            now=datetime.now(timezone.utc).isoformat();q={**quote('ORCL',100),'reported_ttm_eps':5}
            e={'ticker':'ORCL','eps':6,'basis':'ntm_4q','fetched_at':now,'period':'Dec 2026 - Sep 2027'}
            c={'ticker':'ORCL','price':100,'target_median':225,'fetched_at':now}
            main.save_snapshot([q],[],estimates=[e],comparisons=[c])
            article={'title':'Oracle earnings update','summary':'Oracle issues an earnings update','link':'https://example.com/event','source':'test','published':now,'tickers':['ORCL'],'impact':'中','sentiment':50,'label':'中性'}
            main.save_events([article]);a=DesktopAPI();s=a.get_state()
            w=next(x for x in s['watch'] if x['ticker']=='ORCL');card=next(x for x in s['actions'] if x['ticker']=='ORCL');context=a.event_market_context(article['link'])['rows'][0]
            self.assertEqual(w['fair_price'],225);self.assertEqual(card['reference_price'],225);self.assertEqual(context['target'],225)
            self.assertEqual(w['upside_pct'],125);self.assertEqual(card['annual']['upside_pct'],125);self.assertEqual(context['upside_pct'],125)
            self.assertNotEqual(q['target_price'],w['fair_price'])
            main.save_snapshot([],[],comparisons=[{**c,'target_median':240}])
            with a.lock:a._reload_tracking_data();a.revision+=1
            newer=a.get_state();self.assertNotEqual(s['reference_key'],newer['reference_key'])
            self.assertEqual(a.event_market_context(article['link'])['rows'][0]['target'],240)

    def test_fund_has_no_invented_one_year_price_forecast(self):
        with profile():
            main.save_snapshot([quote('SMH',100)],[],comparisons=[{'ticker':'SMH','target_median':300,'fetched_at':datetime.now(timezone.utc).isoformat()}])
            a=DesktopAPI();s=a.get_state();card=next(x for x in s['actions'] if x['ticker']=='SMH')
            self.assertIsNone(card['reference_price']);self.assertIsNone(card['annual']['upside_pct'])
            self.assertTrue(card['is_fund']);self.assertIn('fund_valuation',card)


class EventRiskTests(unittest.TestCase):
    def setUp(self):self.now=datetime(2026,11,8,12,tzinfo=timezone.utc)
    def news(self,title,url='https://www.whitehouse.gov/presidential-actions/ai',hours=0):
        return {'title':title,'summary':title,'link':url,'published':(self.now-timedelta(hours=hours)).isoformat(),'source':'Reuters','publisher':'Reuters','tickers':['SMH'],'independent_publishers':[]}
    def model(self):
        return {'targets':{t:{'date':'2026-11-06','up3_pct':58,'up5_pct':57,'setup':{'oversold':True,'recovery_confirmed':True,'lower_tail_pct':2}} for t in ('QQQ','SMH')}}
    def test_last_24_hours_stance_uses_industry_weight_and_keeps_proposal_below_enacted(self):
        proposal=self.news('Senator calls for a moratorium on AI data centers','https://www.senate.gov/statement')
        enacted=self.news('Commerce Department semiconductor export ban signed into law and effective immediately')
        result=event_risk.assess_events([proposal,enacted],now=self.now)
        self.assertIn(result['半导体产业链']['label'],('偏负面','极度负面','中性整理'))
        self.assertEqual(result['半导体产业链']['window_hours'],24)

    def test_senator_proposal_is_not_treated_as_enacted_policy(self):
        n=self.news('Senator calls for a moratorium on AI data centers','https://www.senate.gov/statement')
        r=event_risk.assess_events([n],now=self.now)
        self.assertEqual(r['events'][0]['stage'],'提议或呼吁');self.assertFalse(r['SMH']['critical_negative'])
    def test_verified_enacted_policy_vetoes_buying_without_inventing_90_percent(self):
        n=self.news('AI export ban signed into law and effective immediately')
        r=event_risk.assess_events([n],now=self.now);m=self.model();before=copy.deepcopy(m)
        env=event_risk.trading_environment(m,r)
        self.assertTrue(r['SMH']['critical_negative']);self.assertIn('控制',env['SMH']['label'])
        self.assertIsNone(r['news_probability_adjustment']);self.assertEqual(m,before)
    def test_denial_cannot_become_verified_negative_evidence(self):
        n=self.news('White House denies AI export ban rumor')
        r=event_risk.assess_events([n],now=self.now)
        self.assertEqual(r['events'][0]['direction'],0);self.assertFalse(r['SMH']['critical_negative'])
    def test_refresh_does_not_make_old_information_fresh(self):
        n=self.news('AI export ban signed into law',hours=119);n['fetched_at']=self.now.isoformat()
        old=event_risk.assess_events([n],now=self.now)
        fresh=event_risk.assess_events([{**n,'published':self.now.isoformat()}],now=self.now)
        self.assertLess(old['SMH']['risk_score'],fresh['SMH']['risk_score'])
    def test_repeated_headline_does_not_multiply_impact(self):
        n=self.news('AI export ban signed into law')
        one=event_risk.assess_events([n],now=self.now);many=event_risk.assess_events([n,{**n,'link':'https://example.com/reprint'}],now=self.now)
        self.assertEqual(one['SMH']['risk_score'],many['SMH']['risk_score']);self.assertEqual(len(many['events']),1)
    def test_social_post_alone_is_capped_and_keeps_original_time(self):
        url='https://x.com/elonmusk/status/1585841080431321088'
        payload={'url':url,'author_name':'Elon Musk','html':'<blockquote><p>AI development should stop</p></blockquote>'}
        with patch('data_service.http_get') as get:
            get.return_value.json.return_value=payload
            post=public_intelligence.public_post(url,{},lambda s:(20,'偏负面'),lambda s:'高')
        self.assertTrue(post['published'].startswith('2022-10-28'))
        self.assertEqual(event_risk.assess_events([post],now=self.now)['events'],[])
        new={**post,'published':self.now.isoformat()};r=event_risk.assess_events([new],now=self.now)
        self.assertLessEqual(r['SMH']['risk_score'],30);self.assertFalse(r['SMH']['critical_negative'])
    def test_obvious_oversold_without_absorption_is_not_unconditional_buy(self):
        m=self.model();m['targets']['SMH']['setup']['recovery_confirmed']=False
        risks=event_risk.assess_events([],now=self.now)
        self.assertIn('等待承接',event_risk.trading_environment(m,risks)['SMH']['label'])


class TwoMarketModelTests(unittest.TestCase):
    def history(self,ticker,values):
        start=datetime(2020,1,1).date()
        return {'ticker':ticker,'bars':[{'date':(start+timedelta(days=i)).isoformat(),'open':v,'close':v,'high':v+1,'low':v-1,'volume':1000+i%7*10} for i,v in enumerate(values)]}
    def test_qqq_and_smh_use_their_own_future_prices(self):
        h=[self.history('QQQ',[100+i*.1 for i in range(650)]),self.history('SPY',[200+i*.1 for i in range(650)]),self.history('SMH',[300-i*.1 for i in range(650)]),self.history('^VIX',[20]*650)]
        rows=market_model._prepare(h)
        self.assertEqual(market_model._outcome(rows,300,5,'QQQ'),1)
        self.assertEqual(market_model._outcome(rows,300,5,'SMH'),0)
        r=market_model.analyze_market(h);json.dumps(r)
        self.assertGreater(r['targets']['QQQ']['up5_pct'],r['targets']['SMH']['up5_pct']+50)
        for target in r['targets'].values():
            self.assertEqual(len(target['up5']['feature_weights']),14)
            self.assertTrue(0<=target['setup']['lower_tail_pct']<=100)
    def test_prospective_observation_is_not_overwritten_on_refresh(self):
        with profile():
            m={'available':True,'date':'2026-11-06','model_version':'3','targets':{'QQQ':{'up5_pct':55,'up3_pct':56,'setup':{}}}}
            r={'events':[],'QQQ':{'risk_score':20}}
            main.save_research_observations(m,r,{})
            main.save_research_observations({**m,'targets':{'QQQ':{'up5_pct':90,'up3_pct':90,'setup':{}}}},r,{})
            with sqlite3.connect(main.DB) as con:rows=con.execute('SELECT payload FROM research_observations').fetchall()
            con.close()
            self.assertEqual(len(rows),1);self.assertEqual(json.loads(rows[0][0])['up5_pct'],55)

if __name__=='__main__':unittest.main()
