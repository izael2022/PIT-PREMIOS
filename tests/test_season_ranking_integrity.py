import sqlite3
import tempfile
import unittest
from datetime import datetime,timedelta,timezone

import systems_extra


class SeasonRankingIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.NamedTemporaryFile(suffix=".sqlite")
        systems_extra.initialize(self.tmp.name)
        c=sqlite3.connect(self.tmp.name)
        now=datetime.now(timezone.utc)
        c.execute("INSERT INTO extra_seasons(title,start_at,end_at,active,created_by) VALUES(?,?,?,?,?)",("Ranking", (now-timedelta(days=1)).isoformat(),(now+timedelta(days=1)).isoformat(),1,1))
        c.execute("INSERT INTO extra_season_scores(season_id,user_id,score) VALUES(1,10,100)")
        c.execute("INSERT INTO extra_season_scores(season_id,user_id,score) VALUES(1,20,100)")
        c.execute("INSERT INTO extra_season_scores(season_id,user_id,score) VALUES(1,30,-5)")
        c.execute("INSERT INTO extra_season_scores(season_id,user_id,score) VALUES(1,40,0)")
        c.commit();c.close()

    def tearDown(self):
        self.tmp.close()

    def test_invalid_scores_filtered_and_ties_deterministic(self):
        rows=systems_extra.season_ranking(self.tmp.name,1,50)
        self.assertEqual(rows,[{"user_id":10,"score":100},{"user_id":20,"score":100}])

    def test_limit_clamped(self):
        self.assertEqual(len(systems_extra.season_ranking(self.tmp.name,1,1000)),2)
        self.assertEqual(len(systems_extra.season_ranking(self.tmp.name,1,0)),1)

    def test_unknown_season_and_invalid_id_rejected(self):
        for sid in (0,-1,999,True):
            with self.assertRaises(ValueError):
                systems_extra.season_ranking(self.tmp.name,sid)

if __name__=="__main__":
    unittest.main()
