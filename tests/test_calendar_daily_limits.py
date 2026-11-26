"""Isolated regression tests for daily calendar reward caps and redemption integrity."""
import os,sqlite3,tempfile,unittest
from datetime import datetime,timedelta,timezone
import systems_extra

class CalendarDailyLimitTests(unittest.TestCase):
 def setUp(self):
  fd,self.path=tempfile.mkstemp(suffix=".sqlite");os.close(fd)
  systems_extra.initialize(self.path)
  with sqlite3.connect(self.path) as c:
   c.execute("CREATE TABLE users(user_id INTEGER PRIMARY KEY,points INTEGER NOT NULL DEFAULT 0)")
   c.execute("CREATE TABLE point_history(user_id INTEGER NOT NULL,amount INTEGER NOT NULL,reason TEXT NOT NULL)")
   c.executemany("INSERT INTO users(user_id,points) VALUES(?,0)",[(11,),(12,)])
  self.now=datetime.now(timezone.utc)
 def tearDown(self):
  try:os.unlink(self.path)
  except OSError:pass
 def campaign(self):
  return systems_extra.create_campaign(self.path,"calendar","Dia reward","", (self.now-timedelta(minutes=1)).isoformat(),(self.now+timedelta(hours=2)).isoformat(),25,0,1)
 def test_daily_cap_across_campaigns_and_users(self):
  a=self.campaign();b=self.campaign()
  systems_extra.set_calendar_daily_limit(self.path,11,1)
  self.assertEqual(systems_extra.claim_calendar_daily(self.path,a,11,self.now.date().isoformat()),25)
  with self.assertRaisesRegex(ValueError,"Limite diário"):
   systems_extra.claim_calendar_daily(self.path,b,11,self.now.date().isoformat())
  self.assertEqual(systems_extra.claim_calendar_daily(self.path,b,12,self.now.date().isoformat()),25)
  with sqlite3.connect(self.path) as c:
   self.assertEqual(c.execute("SELECT points FROM users WHERE user_id=11").fetchone()[0],25)
   self.assertEqual(c.execute("SELECT points FROM users WHERE user_id=12").fetchone()[0],25)
 def test_duplicate_daily_claim_and_window_validation(self):
  a=self.campaign();day=self.now.date().isoformat()
  systems_extra.claim_calendar_daily(self.path,a,11,day)
  with self.assertRaisesRegex(ValueError,"já resgatada"):
   systems_extra.claim_calendar_daily(self.path,a,11,day)
  expired=systems_extra.create_campaign(self.path,"calendar","Expirada","",(self.now-timedelta(hours=2)).isoformat(),(self.now-timedelta(hours=1)).isoformat(),10,0,1)
  with self.assertRaisesRegex(ValueError,"fora do período"):
   systems_extra.claim_calendar_daily(self.path,expired,11,day)

if __name__=="__main__":unittest.main()
