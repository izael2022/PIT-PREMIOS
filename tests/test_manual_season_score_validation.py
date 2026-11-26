import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import systems_extra


class ManualSeasonScoreValidation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.NamedTemporaryFile(suffix=".sqlite")
        systems_extra.initialize(self.tmp.name)
        self.c=sqlite3.connect(self.tmp.name)
        now=datetime.now(timezone.utc)
        self.start=(now-timedelta(minutes=5)).isoformat()
        self.end=(now+timedelta(minutes=5)).isoformat()
        self.c.execute("INSERT INTO extra_seasons(title,start_at,end_at,active,created_by) VALUES(?,?,?,?,?)",("Open",self.start,self.end,1,1))
        self.c.execute("INSERT INTO extra_seasons(title,start_at,end_at,active,created_by) VALUES(?,?,?,?,?)",("Disabled",self.start,self.end,0,1))
        self.c.execute("INSERT INTO extra_seasons(title,start_at,end_at,active,created_by) VALUES(?,?,?,?,?)",("Expired",(now-timedelta(days=2)).isoformat(),(now-timedelta(days=1)).isoformat(),1,1))
        self.c.commit()

    def tearDown(self):
        self.c.close()
        self.tmp.close()

    def test_valid_award(self):
        systems_extra.add_season_score(self.tmp.name,1,55,20)
        self.assertEqual(self.c.execute("SELECT score FROM extra_season_scores WHERE season_id=1 AND user_id=55").fetchone()[0],20)

    def test_invalid_user_and_score_rejected(self):
        for args in [(1,0,5),(1,55,0),(1,55,-1),(1,55,True),(0,55,10)]:
            with self.assertRaises(ValueError):
                systems_extra.add_season_score(self.tmp.name,*args)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM extra_season_scores").fetchone()[0],0)

    def test_inactive_and_expired_rejected(self):
        for season_id in (2,3,99):
            with self.assertRaises(ValueError):
                systems_extra.add_season_score(self.tmp.name,season_id,55,10)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM extra_season_scores").fetchone()[0],0)


if __name__=="__main__":
    unittest.main()
