"""Isolated tests for surprise/event redemption caps and campaign windows."""
import os,sqlite3,tempfile,unittest
from datetime import datetime,timedelta,timezone
import systems_extra
class SurpriseClaimLimitTests(unittest.TestCase):
 def setUp(self):
  fd,self.path=tempfile.mkstemp(suffix=".sqlite");os.close(fd)
  systems_extra.initialize(self.path)
  with sqlite3.connect(self.path) as c:
   c.execute("CREATE TABLE users(user_id INTEGER PRIMARY KEY,points INTEGER NOT NULL DEFAULT 0)")
   c.execute("CREATE TABLE point_history(user_id INTEGER NOT NULL,amount INTEGER NOT NULL,reason TEXT NOT NULL)")
   c.execute("INSERT INTO users(user_id,points) VALUES(77,0)")
  self.now=datetime.now(timezone.utc)
 def tearDown(self):
  try:os.unlink(self.path)
  except OSError:pass
 def make_campaign(self,start=None,end=None):
  start=start or (self.now-timedelta(minutes=1)).isoformat()
  end=end or (self.now+timedelta(minutes=30)).isoformat()
  return systems_extra.create_campaign(self.path,"surprise","Surpresa","",start,end,40,0,1)
 def test_cap_zero_blocks_and_one_allows(self):
  campaign=self.make_campaign()
  systems_extra.set_campaign_user_limit(self.path,campaign,0)
  with self.assertRaisesRegex(ValueError,"Limite de resgate"):
   systems_extra.claim_campaign(self.path,campaign,77,"event")
  systems_extra.set_campaign_user_limit(self.path,campaign,1)
  self.assertEqual(systems_extra.claim_campaign(self.path,campaign,77,"event"),40)
  with self.assertRaisesRegex(ValueError,"já resgatada"):
   systems_extra.claim_campaign(self.path,campaign,77,"event")
 def test_inactive_and_expired_campaigns_block(self):
  expired=self.make_campaign((self.now-timedelta(hours=2)).isoformat(),(self.now-timedelta(hours=1)).isoformat())
  with self.assertRaisesRegex(ValueError,"fora do período"):
   systems_extra.claim_campaign(self.path,expired,77,"event")
  inactive=self.make_campaign()
  systems_extra.set_campaign_active(self.path,inactive,False)
  with self.assertRaisesRegex(ValueError,"inativa"):
   systems_extra.claim_campaign(self.path,inactive,77,"event")
if __name__=="__main__":unittest.main()
