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


    def test_payout_request_reserves_points_and_encrypts_pix(self):
        import base64
        os.environ["BACKUP_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(b"x" * 32).decode()
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            conn.execute("INSERT INTO users(user_id,first_name,points) VALUES(30,'Payout test',20000)")
        payout_id = database.create_payout_request(30, 10000, "test@example.com", "EMAIL", update_id=12345)
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            balance = conn.execute("SELECT points FROM users WHERE user_id=30").fetchone()[0]
            raw_key = conn.execute("SELECT pix_key FROM payout_requests WHERE id=?", (payout_id,)).fetchone()[0]
        self.assertEqual(balance, 10000)
        self.assertTrue(raw_key.startswith("enc:v1:"))
        self.assertNotIn("test@example.com", raw_key)

    def test_rejected_payout_refunds_once(self):
        import base64
        os.environ["BACKUP_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(b"x" * 32).decode()
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            conn.execute("INSERT INTO users(user_id,first_name,points) VALUES(31,'Refund test',20000)")
        payout_id = database.create_payout_request(31, 10000, "test@example.com", "EMAIL")
        first = database.review_payout(payout_id, 999, False)
        second = database.review_payout(payout_id, 999, False)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            balance = conn.execute("SELECT points FROM users WHERE user_id=31").fetchone()[0]
            refunds = conn.execute("SELECT COUNT(*) FROM point_history WHERE user_id=31 AND amount=10000").fetchone()[0]
        self.assertEqual(balance, 20000)
        self.assertEqual(refunds, 1)

    def test_payout_cancel_refunds_once(self):
        import base64
        os.environ["BACKUP_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(b"x" * 32).decode()
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            conn.execute("INSERT INTO users(user_id,first_name,points) VALUES(32,'Cancel test',20000)")
        payout_id = database.create_payout_request(32, 10000, "test@example.com", "EMAIL")
        first = database.cancel_payout_request(32, payout_id)
        second = database.cancel_payout_request(32, payout_id)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            balance = conn.execute("SELECT points FROM users WHERE user_id=32").fetchone()[0]
        self.assertEqual(balance, 20000)


    def test_referral_approval_awards_once(self):
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            conn.execute("INSERT INTO users(user_id,first_name,points) VALUES(40,'Referrer',0)")
            conn.execute("INSERT INTO users(user_id,first_name,points,referred_by) VALUES(41,'Referred',0,40)")
            conn.execute("INSERT INTO referral_reviews(referrer_id,referred_user_id,risk_level,status) VALUES(40,41,'normal','pending')")
        first = database.review_referral(1, 999, True, 1000)
        second = database.review_referral(1, 999, True, 1000)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            self.assertEqual(conn.execute("SELECT points FROM users WHERE user_id=40").fetchone()[0], 1000)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM point_history WHERE user_id=40").fetchone()[0], 1)

    def test_blocked_referrer_cannot_claim_referral_reward(self):
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            conn.execute("INSERT INTO users(user_id,first_name,points) VALUES(50,'Blocked referrer',0)")
            conn.execute("INSERT INTO users(user_id,first_name,points,referred_by) VALUES(51,'Referral user',0,50)")
            conn.execute("INSERT INTO referral_reviews(referrer_id,referred_user_id,risk_level,status) VALUES(50,51,'normal','pending')")
        database.block_account(50, 999, "Teste isolado")
        result = database.review_referral(1, 999, True, 500)
        self.assertTrue(result.get("blocked_referrer"))
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            self.assertEqual(conn.execute("SELECT points FROM users WHERE user_id=50").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT status FROM referral_reviews WHERE id=1").fetchone()[0], "pending")

    def test_manual_referral_hold_can_be_set_and_removed(self):
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            conn.execute("INSERT INTO users(user_id,first_name,points) VALUES(60,'Hold test',0)")
        self.assertTrue(database.set_referral_manual_hold(60, True, 999, "Test hold"))
        self.assertEqual(database.get_referral_manual_hold(60)["reason"], "Test hold")
        self.assertTrue(database.set_referral_manual_hold(60, False, 999))
        self.assertIsNone(database.get_referral_manual_hold(60))

    def test_user_points_constraint(self):
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            conn.execute("INSERT INTO users(user_id,first_name,points) VALUES(1,'Test',0)")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE users SET points=-1 WHERE user_id=1")

    def test_task_approval_awards_points_once(self):
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            conn.execute("INSERT INTO users(user_id,first_name,points) VALUES(70,'Task test',0)")
            conn.execute("INSERT INTO tasks(title,description,reward_points,requires_proof) VALUES('Test task','',250,1)")
            conn.execute("INSERT INTO task_submissions(task_id,user_id,proof,status) VALUES(1,70,'proof text','pending')")
        first = database.review_task_submission(1, 999, True)
        second = database.review_task_submission(1, 999, True)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            self.assertEqual(conn.execute("SELECT points FROM users WHERE user_id=70").fetchone()[0], 250)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM point_history WHERE user_id=70").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM weekly_earnings WHERE user_id=70 AND source='task'").fetchone()[0], 1)

    def test_rejected_task_proof_is_archived_and_can_be_resubmitted(self):
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            conn.execute("INSERT INTO users(user_id,first_name,points) VALUES(71,'Retry task test',0)")
            conn.execute("INSERT INTO tasks(title,description,reward_points,requires_proof) VALUES('Retry task','',150,1)")
            conn.execute("INSERT INTO task_submissions(task_id,user_id,proof,status) VALUES(1,71,'first proof','pending')")
        rejected = database.review_task_submission(1, 999, False)
        self.assertIsNotNone(rejected)
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            self.assertEqual(conn.execute("SELECT status FROM task_submissions WHERE id=1").fetchone()[0], "rejected")
            self.assertEqual(conn.execute("SELECT status FROM task_submission_history WHERE submission_id=1").fetchone()[0], "rejected")
        renewed_id = database.submit_task(1,71,"corrected proof")
        self.assertEqual(renewed_id, 1)
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            self.assertEqual(conn.execute("SELECT status FROM task_submissions WHERE id=1").fetchone()[0], "pending")
            self.assertEqual(conn.execute("SELECT proof FROM task_submissions WHERE id=1").fetchone()[0], "corrected proof")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM task_submission_history WHERE submission_id=1"), 1)

    def test_approved_task_cannot_be_resubmitted(self):
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            conn.execute("INSERT INTO users(user_id,first_name,points) VALUES(72,'No repeat task',0)")
            conn.execute("INSERT INTO tasks(title,description,reward_points,requires_proof) VALUES('Once task','',100,1)")
            conn.execute("INSERT INTO task_submissions(task_id,user_id,proof,status) VALUES(1,72,'proof','approved')")
        with self.assertRaises(ValueError):
            database.submit_task(1,72,"another proof")

    def test_redeem_code_credits_once_and_tracks_usage(self):
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            conn.execute("INSERT INTO users(user_id,first_name,points) VALUES(80,'Code user',0)")
        code = database.create_redeem_code(500,1,999)
        result = database.redeem_code(code,80)
        self.assertEqual(result["points"],500)
        with self.assertRaises(ValueError):
            database.redeem_code(code,80)
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            self.assertEqual(conn.execute("SELECT points FROM users WHERE user_id=80").fetchone()[0],500)
            self.assertEqual(conn.execute("SELECT uses,active FROM redeem_codes WHERE code=?",(code,)).fetchone(),(1,0))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM redeem_code_uses WHERE code=?",(code,)).fetchone()[0],1)

    def test_code_usage_limit_is_enforced_across_users(self):
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            conn.execute("INSERT INTO users(user_id,first_name,points) VALUES(81,'Code user A',0)")
            conn.execute("INSERT INTO users(user_id,first_name,points) VALUES(82,'Code user B',0)")
        code = database.create_redeem_code(300,1,999)
        database.redeem_code(code,81)
        with self.assertRaises(ValueError):
            database.redeem_code(code,82)
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            self.assertEqual(conn.execute("SELECT points FROM users WHERE user_id=82").fetchone()[0],0)

    def test_code_redemption_concurrency_respects_max_uses(self):
        import threading
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            conn.execute("INSERT INTO users(user_id,first_name,points) VALUES(83,'Concurrent A',0)")
            conn.execute("INSERT INTO users(user_id,first_name,points) VALUES(84,'Concurrent B',0)")
        code = database.create_redeem_code(250,1,999)
        barrier=threading.Barrier(2)
        outcomes=[]
        def redeem(uid):
            barrier.wait()
            try:
                outcomes.append(("ok",database.redeem_code(code,uid)))
            except ValueError as exc:
                outcomes.append(("blocked",str(exc)))
        threads=[threading.Thread(target=redeem,args=(uid,)) for uid in (83,84)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=10)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(sum(kind=="ok" for kind,_ in outcomes),1)
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            self.assertEqual(conn.execute("SELECT uses FROM redeem_codes WHERE code=?",(code,)).fetchone()[0],1)
            self.assertEqual(conn.execute("SELECT SUM(points) FROM users WHERE user_id IN (83,84)").fetchone()[0],250)

    def test_code_redemption_requires_registered_user(self):
        code=database.create_redeem_code(200,2,999)
        with self.assertRaises(ValueError):
            database.redeem_code(code,99999)
        with sqlite3.connect(database.DATABASE_PATH) as conn:
            self.assertEqual(conn.execute("SELECT uses FROM redeem_codes WHERE code=?",(code,)).fetchone()[0],0)


if __name__ == "__main__":
    unittest.main()
