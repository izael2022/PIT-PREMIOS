import sqlite3,tempfile,os,unittest
from datetime import datetime,timezone,timedelta
import systems_extra

class ExtraSystemsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.NamedTemporaryFile(delete=False);self.path=self.tmp.name;self.tmp.close()
  with sqlite3.connect(self.path) as c:
   c.executescript("CREATE TABLE users(user_id INTEGER PRIMARY KEY,points INTEGER NOT NULL DEFAULT 0); CREATE TABLE point_history(id INTEGER PRIMARY KEY,user_id INTEGER,amount INTEGER,reason TEXT); INSERT INTO users(user_id,points) VALUES(7,0);")
  systems_extra.initialize(self.path)
  now=datetime.now(timezone.utc)
  self.start=(now-timedelta(hours=1)).isoformat();self.end=(now+timedelta(hours=1)).isoformat()
 def tearDown(self):os.unlink(self.path)
 def test_campaign_claim_credit_and_duplicate_guard(self):
  cid=systems_extra.create_campaign(self.path,"event","Evento","",self.start,self.end,25)
  self.assertEqual(systems_extra.claim_campaign(self.path,cid,7),25)
  with sqlite3.connect(self.path) as c:self.assertEqual(c.execute("SELECT points FROM users WHERE user_id=7").fetchone()[0],25)
  with self.assertRaises(ValueError):systems_extra.claim_campaign(self.path,cid,7)
 def test_collective_goal_blocks_until_target(self):
  cid=systems_extra.create_campaign(self.path,"collective_goal","Meta","",self.start,self.end,10,5)
  with self.assertRaises(ValueError):systems_extra.claim_campaign(self.path,cid,7)
  systems_extra.contribute_goal(self.path,cid,7,5)
  self.assertEqual(systems_extra.claim_campaign(self.path,cid,7),10)
 def test_achievement_claim_is_once(self):
  systems_extra.create_achievement(self.path,"first","Primeira","",3)
  self.assertEqual(systems_extra.claim_achievement(self.path,"first",7),3)
  with self.assertRaises(sqlite3.IntegrityError):systems_extra.claim_achievement(self.path,"first",7)
 def test_rejects_naive_datetime(self):
  with self.assertRaises(ValueError):systems_extra.create_campaign(self.path,"event","Inválida","", "2026-11-01T00:00:00", "2026-12-01T00:00:00")
 def test_goal_rejects_contribution_after_target(self):
  cid=systems_extra.create_campaign(self.path,"collective_goal","Meta","",self.start,self.end,10,2)
  systems_extra.contribute_goal(self.path,cid,7,2)
  with self.assertRaises(ValueError):systems_extra.contribute_goal(self.path,cid,7,1)
 def test_season_ranking(self):
  sid=systems_extra.create_season(self.path,"Temporada",self.start,self.end)
  systems_extra.add_season_score(self.path,sid,7,10);systems_extra.add_season_score(self.path,sid,7,2)
  self.assertEqual(systems_extra.season_ranking(self.path,sid)[0]["score"],12)
if __name__=="__main__":unittest.main()
