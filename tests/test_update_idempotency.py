import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ADMIN_IDS", "1")

import database as db


class UpdateIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db.DATABASE_PATH = Path(self.temp_dir.name) / "idempotency_test.db"
        db.init_db()
        db.register_user(8101, "idempotent", "Idempotent")
        db.add_points(8101, 5000, "Initial test balance")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_replayed_redemption_returns_original_id_without_second_debit(self):
        first = db.create_redemption(8101, 700, "Prize", update_id=90001)
        replay = db.create_redemption(8101, 700, "Prize", update_id=90001)
        self.assertEqual(first, replay)
        self.assertEqual(db.get_user(8101)["points"], 4300)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM redemptions").fetchone()[0], 1)

    def test_replayed_shop_purchase_does_not_debit_or_consume_stock_twice(self):
        reward_id = db.create_reward("Single stock", "Test", 800, stock=1)
        first = db.create_reward_order(8101, reward_id, update_id=90002)
        replay = db.create_reward_order(8101, reward_id, update_id=90002)
        self.assertEqual(first, replay)
        self.assertEqual(db.get_user(8101)["points"], 4200)
        reward = next(row for row in db.all_rewards() if row["id"] == reward_id)
        self.assertEqual(reward["stock"], 0)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM reward_orders").fetchone()[0], 1)

    def test_replayed_payout_returns_original_id_without_second_reservation(self):
        first = db.create_payout_request(8101, 1000, "user@example.com", "EMAIL", 1000, update_id=90003)
        replay = db.create_payout_request(8101, 1000, "user@example.com", "EMAIL", 1000, update_id=90003)
        self.assertEqual(first, replay)
        self.assertEqual(db.get_user(8101)["points"], 4000)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM payout_requests").fetchone()[0], 1)

    def test_replayed_admin_adjustment_does_not_credit_twice(self):
        first = db.add_points(8101, 250, "Admin adjustment", update_id=90004)
        replay = db.add_points(8101, 250, "Admin adjustment", update_id=90004)
        self.assertTrue(first)
        self.assertFalse(replay)
        self.assertEqual(db.get_user(8101)["points"], 5250)
        with db.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM point_history WHERE reason='Admin adjustment'").fetchone()[0],
                1,
            )

    def test_update_id_cannot_be_reused_for_a_different_financial_action(self):
        db.create_redemption(8101, 100, "Prize", update_id=90005)
        with self.assertRaises(ValueError):
            db.create_reward_order(8101, db.create_reward("Other", "Test", 100), update_id=90005)


if __name__ == "__main__":
    unittest.main()
