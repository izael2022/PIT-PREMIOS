import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "test-token-not-valid")
os.environ.setdefault("ADMIN_IDS", "123456789")

import database


class IsolatedDatabaseSchemaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DATABASE_PATH = Path(self.tmp.name) / "isolated_test.db"
        database.init_db()

    def tearDown(self):
        self.tmp.cleanup()

    def test_integrity_check(self):
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_expected_core_tables_exist(self):
        expected = {"users", "point_history", "payout_requests", "reward_orders", "task_submissions", "referral_reviews", "durable_updates", "processed_updates", "admin_audit_log", "health_alert_state"}
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            actual = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue(expected.issubset(actual), f"Missing tables: {expected - actual}")

    def test_user_points_constraint(self):
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            conn.execute("INSERT INTO users(user_id,first_name,points) VALUES(1,'Test',0)")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE users SET points=-1 WHERE user_id=1")


if __name__ == "__main__":
    unittest.main()
