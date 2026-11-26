import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ADMIN_IDS", "1")
os.environ.setdefault("BACKUP_ENCRYPTION_KEY", "eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg=")

import database as db


class BulkSystemRegressionAudit(unittest.TestCase):
    """Cross-system regression checks in isolated SQLite fixtures."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DATABASE_PATH = Path(self.tmp.name) / "bulk_audit.sqlite"
        db.init_db()
        db.register_user(91001, "audit_user", "Audit User")

    def tearDown(self):
        self.tmp.cleanup()

    def test_points_ledger_reconciles_after_multiple_reward_sources(self):
        db.add_points(91001, 100, "Audit credit")
        ok, streak, earned = db.daily_claim(91001, [50, 75])
        self.assertTrue(ok)
        self.assertEqual(earned, 50)
        report = db.financial_dashboard()
        self.assertEqual(report["wallet_balance_points"], 150)
        self.assertEqual(report["ledger_net_points"], 150)
        self.assertTrue(report["ledger_reconciled"])

    def test_reward_stock_purchase_and_approval_flow(self):
        db.add_points(91001, 200, "Fixture balance for reward order")
        reward_id = db.create_reward("Audit reward", "Isolated test item", 200, stock=1)
        order_id = db.create_reward_order(91001, reward_id)
        self.assertEqual(db.get_user(91001)["points"], 0)
        reviewed = db.review_reward_order(order_id, 1, True)
        self.assertIsNotNone(reviewed)
        reward = next(r for r in db.all_rewards() if r["id"] == reward_id)
        self.assertEqual(reward["stock"], 0)
        self.assertEqual(db.get_user(91001)["points"], 0)

    def test_referral_review_is_one_time_and_ledgered(self):
        db.register_user(91002, "referred", "Referred", referrer=91001, is_bot=True)
        with db.connect() as conn:
            row = conn.execute("SELECT id FROM referral_reviews WHERE referred_user_id=?", (91002,)).fetchone()
        first = db.review_referral(row["id"], 1, True, 125)
        second = db.review_referral(row["id"], 1, True, 125)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(db.get_user(91001)["points"], 125)
        report = db.financial_dashboard()
        self.assertEqual(report["ledger_difference"], 0)

    def test_task_submission_approval_is_archived_and_awarded(self):
        task_id = db.create_task("Bulk audit task", "Proof required", 90, True)
        submission_id = db.submit_task(task_id, 91001, "audit proof")
        first = db.review_task_submission(submission_id, 1, True)
        second = db.review_task_submission(submission_id, 1, True)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(db.get_user(91001)["points"], 90)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM weekly_earnings WHERE user_id=91001 AND source='task'").fetchone()[0], 1)

    def test_redeem_code_rejects_repeated_claim(self):
        code = db.create_redeem_code(80, 1, 1)
        result = db.redeem_code(code, 91001)
        self.assertEqual(result["points"], 80)
        with self.assertRaises(ValueError):
            db.redeem_code(code, 91001)
        self.assertEqual(db.get_user(91001)["points"], 80)


    def test_payout_cancel_refunds_once_and_pending_duplicate_is_blocked(self):
        db.add_points(91001, 20000, "Payout fixture")
        payout_id = db.create_payout_request(91001, 10000, "audit@example.com", "EMAIL", 10000)
        self.assertEqual(db.get_user(91001)["points"], 10000)
        with self.assertRaises(ValueError):
            db.create_payout_request(91001, 10000, "audit@example.com", "EMAIL", 10000)
        first = db.cancel_payout_request(91001, payout_id)
        second = db.cancel_payout_request(91001, payout_id)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(db.get_user(91001)["points"], 20000)

    def test_payout_invalid_amounts_do_not_mutate_balance(self):
        db.add_points(91001, 20000, "Payout validation fixture")
        invalid = [9999, 10001, 0, -100]
        for points in invalid:
            with self.assertRaises(ValueError):
                db.create_payout_request(91001, points, "audit@example.com", "EMAIL", 10000)
        self.assertEqual(db.get_user(91001)["points"], 20000)


    def test_rejected_reward_order_refunds_once_and_restores_stock(self):
        db.add_points(91001, 200, "Fixture balance")
        reward_id = db.create_reward("Rejected audit reward", "Fixture", 200, stock=1)
        order_id = db.create_reward_order(91001, reward_id)
        self.assertEqual(db.get_user(91001)["points"], 0)
        first = db.review_reward_order(order_id, 1, False)
        second = db.review_reward_order(order_id, 1, False)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(db.get_user(91001)["points"], 200)
        reward = next(r for r in db.all_rewards() if r["id"] == reward_id)
        self.assertEqual(reward["stock"], 1)

    def test_rejected_task_submission_never_credits_points(self):
        task_id = db.create_task("Rejected audit task", "Fixture", 120, True)
        submission_id = db.submit_task(task_id, 91001, "test evidence")
        first = db.review_task_submission(submission_id, 1, False)
        second = db.review_task_submission(submission_id, 1, False)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(db.get_user(91001)["points"], 0)
        with db.connect() as conn:
            rows = conn.execute("SELECT COUNT(*) FROM task_submission_history WHERE submission_id=?", (submission_id,)).fetchone()[0]
        self.assertEqual(rows, 1)


    def test_user_cancel_reward_order_refunds_and_restores_stock_once(self):
        db.add_points(91001, 200, "Fixture balance")
        reward_id = db.create_reward("Cancelable audit reward", "Fixture", 200, stock=1)
        order_id = db.create_reward_order(91001, reward_id)
        first = db.cancel_reward_order(91001, order_id)
        second = db.cancel_reward_order(91001, order_id)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(db.get_user(91001)["points"], 200)
        reward = next(r for r in db.all_rewards() if r["id"] == reward_id)
        self.assertEqual(reward["stock"], 1)

    def test_referral_rejection_does_not_credit_and_is_idempotent(self):
        db.register_user(91002, "referred_rejected", "Referred Rejected", referrer=91001, is_bot=True)
        with db.connect() as conn:
            row = conn.execute("SELECT id FROM referral_reviews WHERE referred_user_id=?", (91002,)).fetchone()
        first = db.review_referral(row["id"], 1, False, 125)
        second = db.review_referral(row["id"], 1, False, 125)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(db.get_user(91001)["points"], 0)
        self.assertEqual(db.financial_dashboard()["ledger_difference"], 0)

    def test_notifications_and_maintenance_state_persist(self):
        db.record_notification(91001, "audit", "Audit notification", "Fixture message")
        self.assertEqual(db.notification_count(91001), 1)
        db.set_notifications(91001, False)
        self.assertFalse(db.notifications_enabled(91001))
        db.set_maintenance_mode(True)
        self.assertTrue(db.maintenance_mode_enabled())
        db.set_maintenance_mode(False)
        self.assertFalse(db.maintenance_mode_enabled())


if __name__ == "__main__":
    unittest.main()
