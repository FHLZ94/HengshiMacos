import sqlite3
import tempfile
import unittest
import gc
from datetime import date,timedelta
from pathlib import Path
from unittest.mock import patch

import main


class ValuationHistoryTests(unittest.TestCase):
    def test_one_year_average_requires_span_and_samples(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(main,'DB',Path(folder)/'test.sqlite3'):
            main.init_db()
            with sqlite3.connect(main.DB) as con:
                today=date.today()
                for index in range(120):
                    day=(today-timedelta(days=240)+timedelta(days=index*2)).isoformat()
                    con.execute('INSERT INTO ntm_valuation_history VALUES (?,?,?,?,?,?)',
                                ('ORCL',day,100,5,20,'下一年'))
            stats=main.one_year_ntm_average()['ORCL']
            self.assertEqual(stats['samples'],120)
            self.assertIsNone(stats['average'])
            with sqlite3.connect(main.DB) as con:
                con.execute('INSERT INTO ntm_valuation_history VALUES (?,?,?,?,?,?)',
                            ('ORCL',(today-timedelta(days=300)).isoformat(),100,5,20,'下一年'))
            stats=main.one_year_ntm_average()['ORCL']
            self.assertEqual(stats['average'],20)
            con.close()
            gc.collect()


if __name__=='__main__':unittest.main()
