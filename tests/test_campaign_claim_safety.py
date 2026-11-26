import tempfile
import unittest
from datetime import datetime, timedelta, timezone
import sqlite3
import systems_extra


class ExtraCampaignSafetyTests(unittest.TestCase):
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
        self.start=(now-timedelta(minutes=5)).isoformat()
        self.end=(now+timedelta(days=1)).isoformat()

    def test_goal_contribution_cannot_exceed_remaining_target(self):
        cid=systems_extra.create_campaign(self.path,"collective_goal","Meta","",self.start,self.end,0,5,1)
        systems_extra.contribute_goal(self.path,cid,7,3)
        with self.assertRaises(ValueError):
            systems_extra.contribute_goal(self.path,cid,7,3)
        systems_extra.contribute_goal(self.path,cid,7,2)
        with self.assertRaises(ValueError):
            systems_extra.contribute_goal(self.path,cid,7,1)

    def test_bool_campaign_and_contribution_inputs_rejected(self):
        cid=systems_extra.create_campaign(self.path,"collective_goal","Meta","",self.start,self.end,0,5,1)
        for bad in (True,0,-1):
            with self.assertRaises(ValueError): systems_extra.contribute_goal(self.path,bad,7,1)
        for bad in (True,10**13):
            with self.assertRaises(ValueError): systems_extra.contribute_goal(self.path,cid,7,bad)

    def test_invalid_contribution_inputs_rejected(self):
        cid=systems_extra.create_campaign(self.path,"collective_goal","Meta","",self.start,self.end,0,5,1)
        for amount in (0,-1,1.5):
            with self.assertRaises(ValueError):
                systems_extra.contribute_goal(self.path,cid,7,amount)
        with self.assertRaises(ValueError):
            systems_extra.contribute_goal(self.path,cid,-7,1)

    def test_corrupted_goal_progress_rejected(self):
        cid=systems_extra.create_campaign(self.path,"collective_goal","Meta","",self.start,self.end,0,5,1)
        with sqlite3.connect(self.path) as conn: conn.execute("INSERT INTO extra_campaign_progress(campaign_id,user_id,progress) VALUES(?,?,?)",(cid,9,-3))
        with self.assertRaises(ValueError): systems_extra.contribute_goal(self.path,cid,7,1)

    def test_corrupted_campaign_reward_is_rejected_without_credit(self):
        cid=systems_extra.create_campaign(self.path,"event","Evento","",self.start,self.end,100,0,1)
        with sqlite3.connect(self.path) as conn: conn.execute("UPDATE extra_campaigns SET reward_points=-5 WHERE id=?",(cid,))
        with self.assertRaises(ValueError): systems_extra.claim_campaign(self.path,cid,7)
        with sqlite3.connect(self.path) as conn: self.assertEqual(conn.execute("SELECT points FROM users WHERE user_id=7").fetchone()[0],0)

    def test_campaign_claim_cannot_repeat_with_alternate_claim_key(self):
        cid=systems_extra.create_campaign(self.path,"event","Evento","",self.start,self.end,100,0,1)
        self.assertEqual(systems_extra.claim_campaign(self.path,cid,7,"standard"),100)
        with self.assertRaises(ValueError):
            systems_extra.claim_campaign(self.path,cid,7,"alternate")
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("SELECT points FROM users WHERE user_id=7").fetchone()[0],100)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM extra_campaign_claims WHERE campaign_id=? AND user_id=?",(cid,7)).fetchone()[0],1)

    def test_campaign_claim_is_idempotent(self):
        cid=systems_extra.create_campaign(self.path,"event","Evento","",self.start,self.end,100,0,1)
        self.assertEqual(systems_extra.claim_campaign(self.path,cid,7),100)
        with self.assertRaises(ValueError):
            systems_extra.claim_campaign(self.path,cid,7)
        with sqlite3.connect(self.path) as c:
            self.assertEqual(c.execute("SELECT points FROM users WHERE user_id=7").fetchone()[0],100)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM point_history").fetchone()[0],1)

    def test_invalid_claim_key_and_user_rejected(self):
        cid=systems_extra.create_campaign(self.path,"event","Evento","",self.start,self.end,100,0,1)
        for key in ("", " " , "x"*101):
            with self.assertRaises(ValueError):
                systems_extra.claim_campaign(self.path,cid,7,key)
        with self.assertRaises(ValueError):
            systems_extra.claim_campaign(self.path,cid,-7)


if __name__=="__main__":
    unittest.main()
