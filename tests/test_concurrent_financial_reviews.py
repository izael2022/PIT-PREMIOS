import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ADMIN_IDS", "1")

import database as db


class ConcurrentFinancialReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db.DATABASE_PATH = Path(self.temp_dir.name) / "concurrent_reviews.db"
        db.init_db()
        db.register_user(7001, "review_test", "Review Test")
        db.add_points(7001, 10000, "Saldo de teste")

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_twice(self, callback):
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(lambda _: callback(), range(2)))

    def balance(self):
        return db.get_user(7001)["points"]

    def test_concurrent_payout_rejection_refunds_once(self):
        payout = db.create_payout_request(7001, 1000, "test@example.com", "EMAIL", 1000)
        results = self.run_twice(lambda: db.review_payout(payout, 1, False))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(self.balance(), 10000)

    def test_concurrent_redemption_rejection_refunds_once(self):
        redemption = db.create_redemption(7001, 1200, "Prêmio concorrente")
        results = self.run_twice(lambda: db.review_redemption(redemption, 1, False))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(self.balance(), 10000)

    def test_concurrent_reward_order_rejection_refunds_and_restocks_once(self):
        reward = db.create_reward("Prêmio unitário", "Teste concorrente", 1500, stock=1)
        order = db.create_reward_order(7001, reward)
        results = self.run_twice(lambda: db.review_reward_order(order, 1, False))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(self.balance(), 10000)
        stored = next(item for item in db.all_rewards() if item["id"] == reward)
        self.assertEqual(stored["stock"], 1)

    def test_concurrent_task_approval_credits_once(self):
        task = db.create_task("Tarefa concorrente", "Prova", 300, True)
        submission = db.submit_task(task, 7001, "comprovante")
        results = self.run_twice(lambda: db.review_task_submission(submission, 1, True))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(self.balance(), 10300)

    def test_concurrent_referral_approval_credits_once(self):
        db.register_user(7002, "referred", "Referred", referrer=7001, is_bot=True)
        with db.connect() as conn:
            review = conn.execute(
                "SELECT id FROM referral_reviews WHERE referred_user_id=?", (7002,)
            ).fetchone()
        results = self.run_twice(lambda: db.review_referral(review["id"], 1, True, 100))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(self.balance(), 10100)


if __name__ == "__main__":
    unittest.main()
