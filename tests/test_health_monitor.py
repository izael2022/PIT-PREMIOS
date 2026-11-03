import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ADMIN_IDS", "1")

import database as db


class HealthMonitorStateTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db.DATABASE_PATH = Path(self.temp_dir.name) / "health_test.db"
        db.init_db()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_health_snapshot_reports_integrity_and_pending_updates(self):
        db.enqueue_update({"update_id": 99101, "message": {"text": "pending"}})
        snapshot = db.health_snapshot()
        self.assertEqual(snapshot["database_integrity"], "ok")
        self.assertEqual(snapshot["pending_updates"], 1)
        self.assertIsNotNone(snapshot["oldest_pending_at"])

    def test_alert_is_notified_once_during_cooldown(self):
        self.assertTrue(db.should_notify_health_alert("telegram_api", "connection down", 30))
        self.assertFalse(db.should_notify_health_alert("telegram_api", "still down", 30))
        active = db.active_health_alerts()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["alert_key"], "telegram_api")
        self.assertEqual(active[0]["details"], "still down")

    def test_resolved_alert_can_notify_again_on_new_incident(self):
        self.assertTrue(db.should_notify_health_alert("backup", "failed", 30))
        self.assertTrue(db.resolve_health_alert("backup"))
        self.assertFalse(db.resolve_health_alert("backup"))
        self.assertTrue(db.should_notify_health_alert("backup", "failed again", 30))

    def test_alert_details_are_bounded(self):
        db.should_notify_health_alert("large_detail", "x" * 1500)
        self.assertEqual(len(db.active_health_alerts()[0]["details"]), 1000)


if __name__ == "__main__":
    unittest.main()
