import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ADMIN_IDS", "1")

import database as db
import main as bot
import threading
from unittest.mock import patch


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

    def test_health_metrics_survive_reopening_database(self):
        db.set_health_metric("last_backup_ok", "2026-11-03 14:00:00")
        metric = db.get_health_metric("last_backup_ok")
        self.assertEqual(metric["metric_value"], "2026-11-03 14:00:00")
        self.assertIsNotNone(metric["updated_at"])

    def test_recent_health_alerts_include_resolved_incidents(self):
        db.should_notify_health_alert("worker", "queue stalled")
        db.resolve_health_alert("worker")
        rows = db.recent_health_alerts(5)
        self.assertEqual(rows[0]["alert_key"], "worker")
        self.assertEqual(rows[0]["status"], "resolved")

    def test_health_metrics_are_keyed_and_updated(self):
        db.set_health_metric("last_backup_ok", "first")
        db.set_health_metric("last_backup_ok", "second")
        self.assertEqual(db.get_health_metric("last_backup_ok")["metric_value"], "second")

    def test_alert_details_are_bounded(self):
        db.should_notify_health_alert("large_detail", "x" * 1500)
        self.assertEqual(len(db.active_health_alerts()[0]["details"]), 1000)


class BackgroundWorkerSupervisionTests(unittest.TestCase):
    def setUp(self):
        self.names = ("test-worker-reuse", "test-worker-restart")
        with bot.BACKGROUND_THREADS_LOCK:
            for name in self.names:
                bot.BACKGROUND_THREADS.pop(name, None)
                bot.BACKGROUND_RESTART_AT.pop(name, None)
                bot.BACKGROUND_FAILURES.pop(name, None)

    def tearDown(self):
        with bot.BACKGROUND_THREADS_LOCK:
            for name in self.names:
                bot.BACKGROUND_THREADS.pop(name, None)
                bot.BACKGROUND_RESTART_AT.pop(name, None)
                bot.BACKGROUND_FAILURES.pop(name, None)

    def test_running_worker_is_not_duplicated(self):
        release = threading.Event()
        started = threading.Event()

        def worker():
            started.set()
            release.wait(2)

        first = bot.ensure_background_worker(self.names[0], worker, restart_backoff=0)
        self.assertTrue(started.wait(1))
        second = bot.ensure_background_worker(self.names[0], worker, restart_backoff=0)
        self.assertIs(first, second)
        release.set()
        first.join(1)

    def test_stopped_worker_is_restarted(self):
        runs = []
        done = threading.Event()

        def worker():
            runs.append(True)
            done.set()

        with patch.object(bot, "report_health_issue") as report:
            first = bot.ensure_background_worker(self.names[1], worker, restart_backoff=0)
            self.assertTrue(done.wait(1))
            first.join(1)
            done.clear()
            second = bot.ensure_background_worker(self.names[1], worker, restart_backoff=0)
            self.assertIsNot(first, second)
            self.assertTrue(done.wait(1))
            second.join(1)
            self.assertEqual(len(runs), 2)
            report.assert_called_once()


if __name__ == "__main__":
    unittest.main()
