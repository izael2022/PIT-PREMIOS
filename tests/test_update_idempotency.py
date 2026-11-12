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

    def test_replayed_payout_review_does_not_refund_twice(self):
        payout_id = db.create_payout_request(8101, 1000, "user@example.com", "EMAIL", 1000)
        first = db.review_payout(payout_id, 1, False, update_id=90006)
        replay = db.review_payout(payout_id, 1, False, update_id=90006)
        self.assertEqual(first["id"], replay["id"])
        self.assertEqual(db.get_user(8101)["points"], 5000)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM point_history WHERE reason=?", (f"Estorno do saque #{payout_id}",)).fetchone()[0], 1)

    def test_payout_review_idempotency_record_never_stores_plaintext_pix_key(self):
        payout_id = db.create_payout_request(8101, 1000, "private@example.com", "EMAIL", 1000)
        first = db.review_payout(payout_id, 1, True, update_id=90009)
        replay = db.review_payout(payout_id, 1, True, update_id=90009)
        self.assertEqual(first["pix_key"], "private@example.com")
        self.assertEqual(replay["pix_key"], "private@example.com")
        with db.connect() as conn:
            stored = conn.execute("SELECT result FROM idempotency_keys WHERE update_id=90009").fetchone()["result"]
        self.assertNotIn("private@example.com", stored)
        self.assertIn("enc:v1:", stored)

    def test_replayed_game_update_credits_only_once(self):
        first = db.play_daily_game(8101, "chest", 10, update_id=90007)
        replay = db.play_daily_game(8101, "chest", 10, update_id=90007)
        self.assertEqual(first, replay)
        self.assertEqual(db.get_user(8101)["points"], 5010)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM daily_games WHERE user_id=8101").fetchone()[0], 1)

    def test_replayed_code_redemption_credits_only_once(self):
        code = db.create_redeem_code(500, 1, 1)
        first = db.redeem_code(code, 8101, update_id=90008)
        replay = db.redeem_code(code, 8101, update_id=90008)
        self.assertEqual(first, replay)
        self.assertEqual(db.get_user(8101)["points"], 5500)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM redeem_code_uses WHERE code=? AND user_id=8101", (code,)).fetchone()[0], 1)

    def test_update_id_cannot_be_reused_for_a_different_financial_action(self):
        db.create_redemption(8101, 100, "Prize", update_id=90005)
        with self.assertRaises(ValueError):
            db.create_reward_order(8101, db.create_reward("Other", "Test", 100), update_id=90005)


if __name__ == "__main__":
    unittest.main()
