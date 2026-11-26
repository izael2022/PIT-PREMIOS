import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import systems_extra


class SeasonScoreAudit(unittest.TestCase):
    def test_awards_only_active_valid_seasons_in_current_window(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite") as tmp:
            c=sqlite3.connect(tmp.name)
            systems_extra.initialize(tmp.name)
            now=datetime.now(timezone.utc)
            start=(now-timedelta(hours=1)).isoformat()
            end=(now+timedelta(hours=1)).isoformat()
            # Same instant, deliberately represented with a non-UTC offset.
            offset_start=(now-timedelta(hours=1)).astimezone(timezone(timedelta(hours=3))).isoformat()
            offset_end=(now+timedelta(hours=1)).astimezone(timezone(timedelta(hours=3))).isoformat()
            c.execute("INSERT INTO extra_seasons(title,start_at,end_at,active,created_by) VALUES(?,?,?,?,?)",("UTC",start,end,1,1))
            c.execute("INSERT INTO extra_seasons(title,start_at,end_at,active,created_by) VALUES(?,?,?,?,?)",("Offset",offset_start,offset_end,1,1))
            c.execute("INSERT INTO extra_seasons(title,start_at,end_at,active,created_by) VALUES(?,?,?,?,?)",("Inactive",start,end,0,1))
            c.execute("INSERT INTO extra_seasons(title,start_at,end_at,active,created_by) VALUES(?,?,?,?,?)",("Future", (now+timedelta(days=1)).isoformat(),(now+timedelta(days=2)).isoformat(),1,1))
            c.execute("INSERT INTO extra_seasons(title,start_at,end_at,active,created_by) VALUES(?,?,?,?,?)",("Malformed","invalid","invalid",1,1))
            systems_extra._award_active_seasons(c,42,75)
            scores=c.execute("SELECT season_id,score FROM extra_season_scores ORDER BY season_id").fetchall()
            self.assertEqual(scores,[(1,75),(2,75)])
            systems_extra._award_active_seasons(c,42,75)
            scores=c.execute("SELECT season_id,score FROM extra_season_scores ORDER BY season_id").fetchall()
            self.assertEqual(scores,[(1,150),(2,150)])
            systems_extra._award_active_seasons(c,42,0)
            self.assertEqual(c.execute("SELECT score FROM extra_season_scores WHERE season_id=1").fetchone()[0],150)
            c.close()


if __name__=="__main__":
    unittest.main()
