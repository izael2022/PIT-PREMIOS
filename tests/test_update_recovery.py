import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ADMIN_IDS", "1")

import database as db


class DurableUpdateQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db.DATABASE_PATH = Path(self.temp_dir.name) / "updates_test.db"
        db.init_db()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_received_update_is_durable_and_recoverable(self):
        update = {"update_id": 88001, "message": {"message_id": 4, "text": "/start"}}
        self.assertTrue(db.enqueue_update(update))
        self.assertEqual(db.pending_updates(), [update])

    def test_duplicate_delivery_does_not_duplicate_inbox_record(self):
        update = {"update_id": 88002, "callback_query": {"id": "cb-1"}}
        self.assertTrue(db.enqueue_update(update))
        self.assertFalse(db.enqueue_update(update))
        self.assertEqual(db.pending_updates(), [update])

    def test_completed_update_is_not_replayed(self):
        update = {"update_id": 88003, "message": {"message_id": 5, "text": "/saldo"}}
        db.enqueue_update(update)
        db.mark_update_processed(update["update_id"])
        self.assertTrue(db.update_was_processed(update["update_id"]))
        self.assertEqual(db.pending_updates(), [])

    def test_cleanup_keeps_idempotency_for_old_pending_updates(self):
        update = {"update_id": 88005, "message": {"from": {"id": 9}, "chat": {"id": 9}, "text": "/saldo"}}
        db.enqueue_update(update)
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO idempotency_keys(update_id,action,result,created_at) VALUES(?,?,?,datetime('now','-31 days'))",
                (88005, "payout.create", "123"),
            )
            conn.commit()
        db.cleanup_processed_updates()
        with db.connect() as conn:
            row = conn.execute("SELECT update_id FROM idempotency_keys WHERE update_id=88005").fetchone()
        self.assertIsNotNone(row)

    def test_failed_or_unfinished_update_remains_pending(self):
        update = {"update_id": 88004, "message": {"message_id": 6, "text": "/saque"}}
        db.enqueue_update(update)
        # Simula encerramento inesperado antes de marcar como concluído.
        self.assertEqual(db.pending_updates(), [update])


if __name__ == "__main__":
    unittest.main()
