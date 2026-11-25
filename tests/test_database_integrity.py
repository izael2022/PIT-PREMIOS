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


    def test_stock_cannot_be_consumed_twice_concurrently(self):
        import threading
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            conn.execute("INSERT INTO users(user_id,first_name,points) VALUES(10,'Buyer',1000)")
            conn.execute("INSERT INTO rewards(title,points_cost,stock,active) VALUES('Single item',100,1,1)")
        barrier = threading.Barrier(2)
        outcomes = []
        def purchase():
            barrier.wait()
            try:
                outcomes.append(("ok", database.create_reward_order(10, 1)))
            except ValueError as exc:
                outcomes.append(("blocked", str(exc)))
        threads = [threading.Thread(target=purchase) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=10)
        self.assertFalse(any(thread.is_alive() for thread in threads), "Threads did not finish")
        self.assertEqual(sum(kind == "ok" for kind, _ in outcomes), 1)
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            self.assertEqual(conn.execute("SELECT stock FROM rewards WHERE id=1").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM reward_orders").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT points FROM users WHERE user_id=10").fetchone()[0], 900)

    def test_review_reward_order_is_one_time(self):
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            conn.execute("INSERT INTO users(user_id,first_name,points) VALUES(20,'Reviewer test',500)")
            conn.execute("INSERT INTO rewards(title,points_cost,stock,active) VALUES('Review item',100,2,1)")
            conn.execute("INSERT INTO reward_orders(reward_id,user_id,points_spent,status) VALUES(1,20,100,'pending')")
        first = database.review_reward_order(1, 999, True)
        second = database.review_reward_order(1, 999, True)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM point_history WHERE user_id=20").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT status FROM reward_orders WHERE id=1").fetchone()[0], "approved")

    def test_user_points_constraint(self):
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            conn.execute("INSERT INTO users(user_id,first_name,points) VALUES(1,'Test',0)")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE users SET points=-1 WHERE user_id=1")


if __name__ == "__main__":
    unittest.main()
