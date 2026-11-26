"""Regression tests for persistent notification expiry and idempotent announcement delivery."""
import os,tempfile,unittest
from pathlib import Path
import database as db

class NotificationPersistenceTests(unittest.TestCase):
 def setUp(self):
  fd,self.path=tempfile.mkstemp(suffix=".sqlite");os.close(fd)
  self.original=db.DATABASE_PATH;db.DATABASE_PATH=Path(self.path);db.init_db()
  with db.connect() as conn:
   conn.execute("INSERT INTO users(user_id,first_name,points) VALUES(501,'Test',0)")
   conn.execute("INSERT INTO users(user_id,first_name,points) VALUES(502,'Test',0)")
   conn.commit()
 def tearDown(self):
  db.DATABASE_PATH=self.original
  for suffix in ("","-wal","-shm"):
   try:os.unlink(self.path+suffix)
   except OSError:pass
 def test_keyed_notice_is_inserted_once_and_expires(self):
  db.record_notification(501,"news","Aviso","Mensagem",expires_at="2000-01-01 00:00:00",event_key="ann:1")
  db.record_notification(501,"news","Aviso","Mensagem",expires_at="2000-01-01 00:00:00",event_key="ann:1")
  self.assertEqual(db.notification_count(501),0)
  self.assertEqual(db.notification_unread_count(501),0)
  self.assertEqual(db.notification_history(501),[])
 def test_keyed_notice_deduplicates_active_delivery(self):
  db.record_notification(502,"news","Aviso","Mensagem",event_key="ann:2")
  db.record_notification(502,"news","Aviso","Mensagem alterada",event_key="ann:2")
  self.assertEqual(db.notification_count(502),1)
  self.assertEqual(db.notification_unread_count(502),1)
  self.assertEqual(db.notification_history(502)[0]["message"],"Mensagem")
  db.mark_notifications_read(502)
  self.assertEqual(db.notification_unread_count(502),0)
if __name__=="__main__":unittest.main()
