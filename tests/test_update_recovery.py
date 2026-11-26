import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
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

    def test_concurrent_duplicate_delivery_is_persisted_only_once(self):
        update = {\"update_id\": 88005, \"message\": {\"message_id\": 7, \"text\": \"/start\"}}
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: db.enqueue_update(update), range(8)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(db.pending_updates(), [update])

    def test_pending_updates_respect_batch_limit_and_cursor(self):
        updates = [{\"update_id\": 88010+i, \"message\": {\"message_id\": i, \"text\": \"/start\"}} for i in range(4)]
        for update in updates:
            db.enqueue_update(update)
        self.assertEqual(db.pending_updates(limit=2), updates[:2])
        self.assertEqual(db.pending_updates(limit=2, after_update_id=88011), updates[2:])

    def test_failed_or_unfinished_update_remains_pending(self):
        update = {"update_id": 88004, "message": {"message_id": 6, "text": "/saque"}}
        db.enqueue_update(update)
        # Simula encerramento inesperado antes de marcar como concluído.
        self.assertEqual(db.pending_updates(), [update])


if __name__ == "__main__":
    unittest.main()
