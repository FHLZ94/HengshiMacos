import unittest
from datetime import datetime,timezone
from market_view import compose


class MarketViewTests(unittest.TestCase):
    def test_evidence_and_uncalibrated_risk_are_explicit(self):
        now=datetime.now(timezone.utc)
        model={'available':True,'vix':29,'qqq_return5':-4.8,'volume_ratio':1.4,
               'absorption':'反弹量能偏弱','regime':'极度悲观','regime_score':14,
               'validated_better_than_baseline':False,'samples':45,'validation_count':50}
        cnn={'score':21,'rating':'extreme fear','asof':now.isoformat()}
        breadth={'above_20d':120,'valid':500,'ratio_pct':24,
                 'fetched_at':now.isoformat()}
        result=compose(model,cnn,breadth,now)
        self.assertIn('承接尚未确认',result['headline'])
        self.assertIn('标普500',result['evidence'][2])
        self.assertFalse(result['validated'])

    def test_fear_with_healthy_breadth_and_sector_divergence(self):
        now=datetime.now(timezone.utc)
        model={'available':True,'vix':29,'qqq_return5':-5,'smh_return5':-11,
               'volume_ratio':1.5,'absorption':'反弹量能偏弱','regime':'极度悲观',
               'regime_score':13,'validated_better_than_baseline':False,
               'samples':45,'validation_count':50}
        cnn={'score':22,'rating':'extreme fear','asof':now.isoformat()}
        breadth={'above_20d':297,'valid':500,'ratio_pct':59.4,'fetched_at':now.isoformat()}
        result=compose(model,cnn,breadth,now)
        self.assertIn('半导体承压更集中',result['headline'])


if __name__=='__main__': unittest.main()
