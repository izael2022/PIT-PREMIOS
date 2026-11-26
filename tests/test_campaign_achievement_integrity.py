import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import systems_extra


class CampaignAchievementIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.NamedTemporaryFile(suffix=".db",delete=False)
        self.path=self.tmp.name
        self.tmp.close()
        systems_extra.initialize(self.path)
        with sqlite3.connect(self.path) as c:
            c.execute("CREATE TABLE users(user_id INTEGER PRIMARY KEY,points INTEGER NOT NULL DEFAULT 0)")
            c.execute("CREATE TABLE point_history(user_id INTEGER,amount INTEGER,reason TEXT)")
            c.execute("INSERT INTO users(user_id,points) VALUES(7,0)")
        now=datetime.now(timezone.utc)
        self.start=(now-timedelta(minutes=1)).isoformat()
        self.end=(now+timedelta(days=1)).isoformat()

    def tearDown(self):
        self.tmp.close()

    def test_achievement_claim_duplicate_is_controlled_and_atomic(self):
        systems_extra.create_achievement(self.path,"first","First",reward_points=25)
        self.assertEqual(systems_extra.claim_achievement(self.path,"first",7),25)
        with self.assertRaisesRegex(ValueError,"já resgatada"):
            systems_extra.claim_achievement(self.path,"first",7)
        with sqlite3.connect(self.path) as c:
            self.assertEqual(c.execute("SELECT points FROM users WHERE user_id=7").fetchone()[0],25)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM point_history").fetchone()[0],1)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM extra_achievement_claims").fetchone()[0],1)

    def test_bool_user_and_campaign_id_rejected(self):
        cid=systems_extra.create_campaign(self.path,"event","Evento","",self.start,self.end,10,0,1)
        for invalid in (True,0,-1):
            with self.assertRaises(ValueError):
                systems_extra.claim_campaign(self.path,invalid,7)
            with self.assertRaises(ValueError):
                systems_extra.claim_campaign(self.path,cid,invalid)

    def test_achievement_reward_validation(self):
        for reward in (-1,True,1.5,10**13):
            with self.assertRaises(ValueError):
                systems_extra.create_achievement(self.path,"bad","Bad",reward_points=reward)


if __name__=="__main__":
    unittest.main()
