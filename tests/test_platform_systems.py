import sqlite3,tempfile,unittest
import systems_platform as p

class PlatformSystemsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.NamedTemporaryFile(suffix=".db",delete=False);self.path=self.tmp.name;self.tmp.close();p.initialize(self.path)
 def tearDown(self):self.tmp.close()
 def test_ticket_lifecycle_and_owner_filter(self):
  t=p.open_ticket(self.path,5,"Ajuda","Preciso de ajuda")
  self.assertEqual(len(p.ticket_list(self.path,5)),1);self.assertEqual(p.ticket_list(self.path,6),[])
  self.assertTrue(p.answer_ticket(self.path,t,9,"Resposta",True));self.assertEqual(p.ticket_list(self.path,5)[0]["status"],"closed")
  self.assertFalse(p.answer_ticket(self.path,t,9,"Outra",True))
 def test_limits_atomic_and_per_period(self):
  p.set_limit(self.path,"mission","daily",2,9)
  self.assertTrue(p.consume_limit(self.path,"mission","daily",5,"2026-11-26",2))
  self.assertFalse(p.consume_limit(self.path,"mission","daily",5,"2026-11-26",1))
  self.assertTrue(p.consume_limit(self.path,"mission","daily",5,"2026-11-27",1))
 def test_fraud_review_once(self):
  r=p.flag_user(self.path,5,"multi-account","Suspeita")
  self.assertTrue(p.review_flag(self.path,r,9,"blocked"));self.assertFalse(p.review_flag(self.path,r,9,"approved"))
 def test_levels_are_xp_based_without_wallet(self):
  p.add_xp(self.path,5,1500);self.assertEqual(p.level_info(self.path,5),{"xp":1500,"level":2,"next_level_xp":2000})
 def test_badge_claim_once(self):
  p.create_badge(self.path,"early","Pioneiro")
  self.assertTrue(p.award_badge(self.path,5,"early"));self.assertFalse(p.award_badge(self.path,5,"early"))
 def test_announcement_and_admin_log(self):
  a=p.create_announcement(self.path,"Aviso","Mensagem",9)
  self.assertEqual(p.active_announcements(self.path)[0]["id"],a)
  p.admin_log(self.path,9,"edit campaign","test");self.assertEqual(len(p.admin_logs(self.path)),1)
 def test_notification_expiry_and_read(self):
  n=p.add_notification(self.path,5,"Aviso","Conteúdo","2000-01-01T00:00:00+00:00")
  self.assertEqual(p.notifications(self.path,5),[])
  n=p.add_notification(self.path,5,"Aviso","Conteúdo")
  self.assertEqual(len(p.notifications(self.path,5)),1);self.assertTrue(p.mark_notification_read(self.path,5,n))
  self.assertEqual(p.notifications(self.path,5),[])
 def test_validation(self):
  with self.assertRaises(ValueError):p.open_ticket(self.path,True,"a","b")
  with self.assertRaises(ValueError):p.set_limit(self.path,"bad","x",1,9)
if __name__=="__main__":unittest.main()
