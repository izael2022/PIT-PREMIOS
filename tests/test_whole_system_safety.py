import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ADMIN_IDS", "1")

import database as db
import main


class WholeSystemSafetyRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db.DATABASE_PATH = Path(self.temp_dir.name) / "whole_system_safety.db"
        db.init_db()
        db.register_user(7001, "safety_user", "Safety User")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_pending_task_selection_survives_database_reopen(self):
        task_id = db.create_task("Tarefa persistente", "Enviar prova", 50, True)
        db.set_pending_task_proof(7001, task_id)
        self.assertEqual(db.get_pending_task_proof(7001), task_id)
        self.assertTrue(db.clear_pending_task_proof(7001))
        self.assertIsNone(db.get_pending_task_proof(7001))

    def test_blocked_user_cannot_trigger_callback_game(self):
        db.block_account(7001, 1, "Teste de bloqueio")
        with patch.object(main, "api", return_value=None) as api_mock, patch.object(main, "send") as send_mock:
            main.callback({
                "id": "callback-test",
                "data": "game:chest",
                "from": {"id": 7001},
                "message": {"chat": {"id": 7001}},
            })
        self.assertEqual(api_mock.call_count, 1)
        send_mock.assert_not_called()
        self.assertEqual(db.game_status(7001), {})

    def test_admin_panel_navigation_marks_previous_screen_for_deletion(self):
        self.assertTrue(main._should_delete_callback_message("admin:stats", 1))
        self.assertTrue(main._should_delete_callback_message("admin:back", 1))

    def test_non_admin_and_review_cards_are_not_marked_for_deletion(self):
        self.assertFalse(main._should_delete_callback_message("admin:stats", 7001))
        self.assertFalse(main._should_delete_callback_message("taskreview:12:yes", 1))
        self.assertFalse(main._should_delete_callback_message("rewardreview:8:no", 1))

    def test_pending_updates_can_be_recovered_in_multiple_batches(self):
        for update_id in range(1, 502):
            db.enqueue_update({"update_id": update_id, "message": {"text": "test"}})
        first = db.pending_updates(limit=500, after_update_id=0)
        second = db.pending_updates(limit=500, after_update_id=first[-1]["update_id"])
        self.assertEqual(len(first), 500)
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["update_id"], 501)


if __name__ == "__main__":
    unittest.main()
