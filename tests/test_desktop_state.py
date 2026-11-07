import unittest
from datetime import datetime,timedelta,timezone

from desktop import current_price_gap


class DesktopStateTests(unittest.TestCase):
    def test_price_conflict_requires_recent_sources(self):
        now=datetime.now(timezone.utc)
        quote={'price':100,'fetched_at':now.isoformat()}
        current={'price':104,'fetched_at':(now-timedelta(minutes=5)).isoformat()}
        stale={'price':104,'fetched_at':(now-timedelta(days=2)).isoformat()}
        self.assertAlmostEqual(current_price_gap(quote,current),4.0)
        self.assertIsNone(current_price_gap(quote,stale))


if __name__=='__main__':unittest.main()
