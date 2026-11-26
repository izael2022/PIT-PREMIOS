import tempfile
import unittest
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
import systems_extra


class ChallengeProgressIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=str(Path(self.tmp.name)/"test.db")
        systems_extra.initialize(self.path)
        with sqlite3.connect(self.path) as c:
            c.execute("CREATE TABLE users(user_id INTEGER PRIMARY KEY,points INTEGER NOT NULL DEFAULT 0)")
            c.execute("CREATE TABLE point_history(user_id INTEGER,amount INTEGER,reason TEXT)")
            c.execute("INSERT INTO users(user_id,points) VALUES(7,0)")
        now=datetime.now(timezone.utc)
        self.start=(now-timedelta(minutes=1)).isoformat()
        self.end=(now+timedelta(hours=1)).isoformat()
        self.campaign=systems_extra.create_campaign(self.path,"challenge","Teste","",self.start,self.end,0,5,1)

    def tearDown(self):
        self.tmp.cleanup()

    def test_event_progress_is_idempotent(self):
        self.assertTrue(systems_extra.record_challenge_progress(self.path,self.campaign,7,2,"evt-1"))
        self.assertFalse(systems_extra.record_challenge_progress(self.path,self.campaign,7,2,"evt-1"))
        self.assertEqual(systems_extra.challenge_progress(self.path,self.campaign,7),2)

    def test_progress_cannot_exceed_target(self):
        systems_extra.record_challenge_progress(self.path,self.campaign,7,4,"evt-1")
        with self.assertRaises(ValueError):
            systems_extra.record_challenge_progress(self.path,self.campaign,7,2,"evt-2")
        self.assertEqual(systems_extra.challenge_progress(self.path,self.campaign,7),4)

    def test_invalid_amount_rejected(self):
        for amount in (0,-1,True):
            with self.assertRaises(ValueError):
                systems_extra.record_challenge_progress(self.path,self.campaign,7,amount,"invalid-"+str(amount))

    def test_progress_rejected_outside_window(self):
        systems_extra.update_campaign(self.path,self.campaign,"challenge","Teste","","2000-01-01T00:00:00+00:00","2000-01-02T00:00:00+00:00",0,5)
        with self.assertRaises(ValueError):
            systems_extra.record_challenge_progress(self.path,self.campaign,7,1,"late")

    def test_inactive_challenge_rejected(self):
        systems_extra.set_campaign_active(self.path,self.campaign,False)
        with self.assertRaises(ValueError):
            systems_extra.record_challenge_progress(self.path,self.campaign,7,1,"inactive")


if __name__=="__main__":
    unittest.main()
