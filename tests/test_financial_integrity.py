import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# database.py imports config.py, which validates these settings at import time.
os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ADMIN_IDS", "1")

import database as db


class FinancialIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db.DATABASE_PATH = Path(self.temp_dir.name) / "pit_premios_test.db"
        db.init_db()
        db.register_user(1001, "tester", "Tester")
        db.add_points(1001, 5000, "Saldo inicial de teste")

    def tearDown(self):
        self.temp_dir.cleanup()

    def balance(self):
        return db.get_user(1001)["points"]

    def test_payout_cancel_refunds_only_once(self):
        payout_id = db.create_payout_request(1001, 1000, "teste@example.com", "EMAIL", 1000)
        self.assertEqual(self.balance(), 4000)
        self.assertIsNotNone(db.cancel_payout_request(1001, payout_id))
        self.assertIsNone(db.cancel_payout_request(1001, payout_id))
        self.assertEqual(self.balance(), 5000)

    def test_rejected_payout_refunds_only_once(self):
        payout_id = db.create_payout_request(1001, 1000, "teste@example.com", "EMAIL", 1000)
        self.assertIsNotNone(db.review_payout(payout_id, 1, False))
        self.assertIsNone(db.review_payout(payout_id, 1, False))
        self.assertEqual(self.balance(), 5000)

    def test_approved_payout_is_not_refunded(self):
        payout_id = db.create_payout_request(1001, 1000, "teste@example.com", "EMAIL", 1000)
        self.assertIsNotNone(db.review_payout(payout_id, 1, True))
        self.assertIsNone(db.review_payout(payout_id, 1, False))
        self.assertEqual(self.balance(), 4000)

    def test_rejected_redemption_refunds_only_once(self):
        redemption_id = db.create_redemption(1001, 500, "Prêmio de teste")
        self.assertIsNotNone(db.review_redemption(redemption_id, 1, False))
        self.assertIsNone(db.review_redemption(redemption_id, 1, False))
        self.assertEqual(self.balance(), 5000)

    def test_reward_order_cancel_restores_points_and_stock_once(self):
        reward_id = db.create_reward("Prêmio limitado", "Teste", 700, stock=1)
        order_id = db.create_reward_order(1001, reward_id)
        self.assertEqual(self.balance(), 4300)
        self.assertIsNotNone(db.cancel_reward_order(1001, order_id))
        self.assertIsNone(db.cancel_reward_order(1001, order_id))
        self.assertEqual(self.balance(), 5000)
        reward = next(row for row in db.all_rewards() if row["id"] == reward_id)
        self.assertEqual(reward["stock"], 1)

    def test_limited_stock_cannot_be_sold_twice_concurrently(self):
        reward_id = db.create_reward("Última unidade", "Teste concorrente", 1000, stock=1)

        def buy():
            try:
                return db.create_reward_order(1001, reward_id)
            except ValueError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: buy(), range(2)))

        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(self.balance(), 4000)
        reward = next(row for row in db.all_rewards() if row["id"] == reward_id)
        self.assertEqual(reward["stock"], 0)

    def test_task_approval_credits_only_once(self):
        task_id = db.create_task("Tarefa teste", "Comprovação", 250, True)
        submission_id = db.submit_task(task_id, 1001, "comprovante")
        self.assertIsNotNone(db.review_task_submission(submission_id, 1, True))
        self.assertIsNone(db.review_task_submission(submission_id, 1, True))
        self.assertEqual(self.balance(), 5250)

    def test_welcome_bonus_is_credited_once_only_for_new_real_users(self):
        created, referrer, review_id = db.register_user(
            3001, "welcome_user", "Welcome User", welcome_reward=1000
        )
        self.assertTrue(created)
        self.assertIsNone(referrer)
        self.assertIsNone(review_id)
        self.assertEqual(db.get_user(3001)["points"], 1000)
        with db.connect() as conn:
            history = conn.execute(
                "SELECT amount,reason FROM point_history WHERE user_id=?", (3001,)
            ).fetchall()
            weekly = conn.execute(
                "SELECT points,source FROM weekly_earnings WHERE user_id=?", (3001,)
            ).fetchall()
        self.assertEqual([(row["amount"], row["reason"]) for row in history], [(1000, "Bônus de boas-vindas")])
        self.assertEqual([(row["points"], row["source"]) for row in weekly], [(1000, "welcome")])
        created_again, _, _ = db.register_user(
            3001, "welcome_user", "Welcome User", welcome_reward=1000
        )
        self.assertFalse(created_again)
        self.assertEqual(db.get_user(3001)["points"], 1000)

    def test_welcome_bonus_and_referral_reward_are_separate(self):
        created, referrer, review_id = db.register_user(
            3002, "referred_user", "Referred User", referrer=1001,
            referral_reward=1000, welcome_reward=1000
        )
        self.assertTrue(created)
        self.assertEqual(referrer, 1001)
        self.assertIsNone(review_id)
        self.assertEqual(db.get_user(3002)["points"], 1000)
        self.assertEqual(db.get_user(1001)["points"], 6000)

    def test_referral_approval_credits_only_once(self):
        db.register_user(2002, "indicado", "Indicado", referrer=1001, is_bot=True)
        with db.connect() as conn:
            review = conn.execute(
                "SELECT id FROM referral_reviews WHERE referred_user_id=?",
                (2002,),
            ).fetchone()
        self.assertIsNotNone(review)
        self.assertIsNotNone(db.review_referral(review["id"], 1, True, 100))
        self.assertIsNone(db.review_referral(review["id"], 1, True, 100))
        self.assertEqual(self.balance(), 5100)

    def test_zero_daily_reward_advances_streak_without_invalid_weekly_row(self):
        claimed, streak, earned = db.daily_claim(1001, [0, 5])
        self.assertTrue(claimed)
        self.assertEqual(streak, 1)
        self.assertEqual(earned, 0)
        self.assertEqual(self.balance(), 5000)
        with db.connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM weekly_earnings WHERE user_id=? AND source='daily_checkin'",
                (1001,),
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_redemption_rejects_invalid_values(self):
        for points, reward in ((0, "Prêmio"), (-1, "Prêmio"), (10, ""), (10, "x" * 501)):
            with self.subTest(points=points, reward_length=len(reward)):
                with self.assertRaises(ValueError):
                    db.create_redemption(1001, points, reward)
        self.assertEqual(self.balance(), 5000)


    def test_admin_stats_returns_all_dashboard_fields(self):
        stats = db.stats()
        self.assertEqual(stats["users"], 1)
        self.assertEqual(stats["points"], 5000)
        self.assertEqual(stats["pending_redemptions"], 0)
        self.assertEqual(stats["pending_payouts"], 0)
        self.assertEqual(stats["pending_reward_orders"], 0)
        self.assertEqual(stats["pending_tasks"], 0)
        self.assertEqual(stats["pending_fraud"], 0)

    def test_configurable_daily_reward_sequence_validation(self):
        from config import parse_daily_rewards

        self.assertEqual(parse_daily_rewards("3, 4,5, 10"), (3, 4, 5, 10))
        self.assertEqual(parse_daily_rewards("0,5"), (0, 5))
        for invalid in ("", "1,,2", "1,abc", "-1,2"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    parse_daily_rewards(invalid)


    def test_referral_approval_uses_configured_reward_and_zero_disables_credit(self):
        db.register_user(2003, "indicado_zero", "Indicado Zero", referrer=1001, is_bot=True)
        with db.connect() as conn:
            review = conn.execute(
                "SELECT id FROM referral_reviews WHERE referred_user_id=?", (2003,)
            ).fetchone()
        self.assertIsNotNone(db.review_referral(review["id"], 1, True, 0))
        self.assertEqual(self.balance(), 5000)

    def test_referral_rejects_negative_reward_without_changing_review(self):
        db.register_user(2004, "indicado_neg", "Indicado Neg", referrer=1001, is_bot=True)
        with db.connect() as conn:
            review = conn.execute(
                "SELECT id FROM referral_reviews WHERE referred_user_id=?", (2004,)
            ).fetchone()
        with self.assertRaises(ValueError):
            db.review_referral(review["id"], 1, True, -1)
        with db.connect() as conn:
            status = conn.execute(
                "SELECT status FROM referral_reviews WHERE id=?", (review["id"],)
            ).fetchone()["status"]
        self.assertEqual(status, "pending")
        self.assertEqual(self.balance(), 5000)

    def test_default_payout_minimum_is_ten_thousand_points(self):\n        from config import MIN_PAYOUT_POINTS\n\n        self.assertEqual(MIN_PAYOUT_POINTS, 10000)\n        db.add_points(1001, 10000, "Saldo adicional para teste de saque")\n        with self.assertRaisesRegex(ValueError, "10,000 pontos"):\n            db.create_payout_request(1001, 9999, "user@example.com", "EMAIL")\n        payout_id = db.create_payout_request(1001, 10000, "user@example.com", "EMAIL")\n        with db.connect() as conn:\n            payout = conn.execute(\n                "SELECT points,amount_cents FROM payout_requests WHERE id=?", (payout_id,)\n            ).fetchone()\n        self.assertEqual((payout["points"], payout["amount_cents"]), (10000, 1000))\n        self.assertEqual(self.balance(), 5000)\n\n    def test_payout_validates_configured_minimum_and_pix_type(self):
        with self.assertRaises(ValueError):
            db.create_payout_request(1001, 900, "user@example.com", "EMAIL", 1000)
        with self.assertRaises(ValueError):
            db.create_payout_request(1001, 1000, "user@example.com", "INVALID", 1000)
        self.assertEqual(self.balance(), 5000)

    def test_set_vip_reports_missing_user(self):
        self.assertFalse(db.set_vip(999999, True))
        self.assertTrue(db.set_vip(1001, True))
        self.assertTrue(db.get_user(1001)["is_vip"])


    def test_payout_reduction_refunds_difference_and_records_history_and_audit(self):
        payout_id = db.create_payout_request(1001, 2000, "teste@example.com", "EMAIL", 1000)
        result = db.reduce_pending_payout(payout_id, 1000, 1)
        self.assertEqual(result["refunded_points"], 1000)
        self.assertEqual(result["amount_cents"], 100)
        self.assertEqual(self.balance(), 4000)
        with db.connect() as conn:
            payout = conn.execute("SELECT points,amount_cents,status FROM payout_requests WHERE id=?", (payout_id,)).fetchone()
            history = conn.execute("SELECT amount,reason FROM point_history WHERE user_id=1001 ORDER BY id DESC LIMIT 1").fetchone()
            audit = conn.execute("SELECT admin_id,action,details FROM admin_audit_log ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual((payout["points"], payout["amount_cents"], payout["status"]), (1000, 100, "pending"))
        self.assertEqual(history["amount"], 1000)
        self.assertIn(f"#{payout_id}", history["reason"])
        self.assertEqual((audit["admin_id"], audit["action"]), (1, "payout_reduced"))
        self.assertIn(f"#{payout_id}", audit["details"])

    def test_new_payout_uses_1000_points_per_real(self):
        payout_id = db.create_payout_request(1001, 1500, "teste@example.com", "EMAIL", 1000)
        with db.connect() as conn:
            payout = conn.execute("SELECT points,amount_cents FROM payout_requests WHERE id=?", (payout_id,)).fetchone()
        self.assertEqual((payout["points"], payout["amount_cents"]), (1500, 150))

    def test_legacy_pending_payout_keeps_historical_conversion_when_reduced(self):
        payout_id = db.create_payout_request(1001, 2000, "teste@example.com", "EMAIL", 1000)
        with db.connect() as conn:
            conn.execute("UPDATE payout_requests SET conversion_version=1,amount_cents=2000 WHERE id=?", (payout_id,))
            conn.commit()
        result = db.reduce_pending_payout(payout_id, 1000, 1)
        self.assertEqual(result["amount_cents"], 1000)
        with db.connect() as conn:
            payout = conn.execute("SELECT points,amount_cents,conversion_version FROM payout_requests WHERE id=?", (payout_id,)).fetchone()
        self.assertEqual((payout["points"], payout["amount_cents"], payout["conversion_version"]), (1000, 1000, 1))
        self.assertEqual(self.balance(), 4000)

    def test_payout_reduction_cannot_go_below_configured_minimum(self):
        payout_id = db.create_payout_request(1001, 2000, "teste@example.com", "EMAIL", 1000)
        with self.assertRaisesRegex(ValueError, "inferior ao mínimo"):
            db.reduce_pending_payout(payout_id, 990, 1, 1000)
        self.assertEqual(self.balance(), 3000)
        with db.connect() as conn:
            payout = conn.execute("SELECT points,amount_cents FROM payout_requests WHERE id=?", (payout_id,)).fetchone()
        self.assertEqual((payout["points"], payout["amount_cents"]), (2000, 200))

    def test_payout_reduction_rejects_non_admin(self):
        payout_id = db.create_payout_request(1001, 2000, "teste@example.com", "EMAIL", 1000)
        with self.assertRaisesRegex(ValueError, "Apenas administradores"):
            db.reduce_pending_payout(payout_id, 1000, 999)
        self.assertEqual(self.balance(), 3000)
        with db.connect() as conn:
            payout = conn.execute("SELECT points,amount_cents FROM payout_requests WHERE id=?", (payout_id,)).fetchone()
        self.assertEqual((payout["points"], payout["amount_cents"]), (2000, 200))

    def test_payout_reduction_rejects_invalid_or_non_reducing_amount(self):
        payout_id = db.create_payout_request(1001, 2000, "teste@example.com", "EMAIL", 1000)
        for invalid in (0, -10, 999, 2000, 2010):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    db.reduce_pending_payout(payout_id, invalid, 1)
        self.assertEqual(self.balance(), 3000)

    def test_payout_reduction_only_works_while_pending(self):
        payout_id = db.create_payout_request(1001, 2000, "teste@example.com", "EMAIL", 1000)
        self.assertIsNotNone(db.review_payout(payout_id, 1, False))
        self.assertIsNone(db.reduce_pending_payout(payout_id, 1000, 1))
        self.assertEqual(self.balance(), 5000)

    def test_concurrent_payout_reduction_refunds_only_once(self):
        payout_id = db.create_payout_request(1001, 2000, "teste@example.com", "EMAIL", 1000)
        def reduce_once():
            try:
                return db.reduce_pending_payout(payout_id, 1000, 1)
            except ValueError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: reduce_once(), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(self.balance(), 4000)
        with db.connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM point_history WHERE user_id=1001 AND reason=?",
                (f"Devolução após redução do saque #{payout_id}",),
            ).fetchone()[0]
        self.assertEqual(count, 1)



if __name__ == "__main__":
    unittest.main()
