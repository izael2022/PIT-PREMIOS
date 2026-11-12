import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ADMIN_IDS", "1")
os.environ.setdefault("BACKUP_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"pit-premios-test-key-32-bytes!!!").decode("ascii"))

import database as db


class AuditCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path_patch = patch.object(db, "DATABASE_PATH", Path(self.temp.name) / "audit.db")
        self.path_patch.start()
        self.key_patch = patch.dict(os.environ, {"BACKUP_ENCRYPTION_KEY": base64.urlsafe_b64encode(b"pit-premios-test-key-32-bytes!!!").decode("ascii")})
        self.key_patch.start()
        db.init_db()
        db.register_user(1, "referrer", "Referrer")

    def tearDown(self):
        self.key_patch.stop()
        self.path_patch.stop()
        self.temp.cleanup()

    def add_valid_referrals(self, count):
        with db.connect() as conn:
            for uid in range(100, 100 + count):
                conn.execute("INSERT INTO users(user_id,first_name,referred_by) VALUES(?,?,?)", (uid, f"User {uid}", 1))
            conn.commit()

    def test_referral_milestones_pay_cumulative_totals_only(self):
        self.add_valid_referrals(1)
        self.assertEqual(db.claim_referral_milestone(1, 1), 1000)
        self.assertEqual(db.get_user(1)["points"], 1000)
        self.add_valid_referrals(4)
        self.assertEqual(db.claim_referral_milestone(1, 5), 5500)
        self.assertEqual(db.get_user(1)["points"], 6500)
        self.add_valid_referrals(5)
        self.assertEqual(db.claim_referral_milestone(1, 10), 7500)
        self.assertEqual(db.get_user(1)["points"], 14000)

    def test_new_referral_registration_does_not_pay_per_friend(self):
        created, referrer, review_id = db.register_user(200, "newfriend", "New Friend", 1, referral_reward=1000)
        self.assertTrue(created)
        self.assertEqual(referrer, 1)
        self.assertIsNone(review_id)
        self.assertEqual(db.get_user(1)["points"], 0)
        self.assertEqual(db.referral_milestone_status(1)[0]["bonus"], 1000)

    def test_durable_updates_are_encrypted_and_readable(self):
        update = {"update_id": 991, "message": {"text": "minha chave Pix: private@example.com", "chat": {"id": 1}}}
        db.enqueue_update(update)
        with db.connect() as conn:
            stored = conn.execute("SELECT payload FROM durable_updates WHERE update_id=991").fetchone()["payload"]
        self.assertTrue(stored.startswith("enc:v1:"))
        self.assertNotIn("private@example.com", stored)
        self.assertEqual(db.pending_updates(limit=10), [update])

    def test_legacy_plaintext_pending_update_is_migrated_on_read(self):
        update = {"update_id": 992, "message": {"text": "legacy private@example.com"}}
        import json
        with db.connect() as conn:
            conn.execute("INSERT INTO durable_updates(update_id,payload) VALUES(?,?)", (992, json.dumps(update)))
            conn.commit()
        self.assertEqual(db.pending_updates(limit=10), [update])
        with db.connect() as conn:
            stored = conn.execute("SELECT payload FROM durable_updates WHERE update_id=992").fetchone()["payload"]
        self.assertTrue(stored.startswith("enc:v1:"))
        self.assertNotIn("private@example.com", stored)

    def test_admin_creation_actions_are_idempotent(self):
        task_a = db.create_task("Task", "Desc", 10, update_id=5001)
        task_b = db.create_task("Task", "Desc", 10, update_id=5001)
        self.assertEqual(task_a, task_b)
        reward_a = db.create_reward("Reward", "Desc", 20, 1, update_id=5002)
        reward_b = db.create_reward("Reward", "Desc", 20, 1, update_id=5002)
        self.assertEqual(reward_a, reward_b)
        code_a = db.create_redeem_code(50, 1, 1, update_id=5003)
        code_b = db.create_redeem_code(50, 1, 1, update_id=5003)
        self.assertEqual(code_a, code_b)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM rewards").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM redeem_codes").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
