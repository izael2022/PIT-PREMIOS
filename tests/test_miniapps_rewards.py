import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ADMIN_IDS", "1")
os.environ.setdefault(
    "BACKUP_ENCRYPTION_KEY",
    base64.urlsafe_b64encode(b"pit-premios-test-key-32-bytes!!!").decode("ascii"),
)

import database as db


class MiniAppRewardIsolationTests(unittest.TestCase):
    """Exercita as mesmas rotinas SQLite usadas pelas Mini Apps, em DB temporário."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path_patch = patch.object(db, "DATABASE_PATH", Path(self.temp.name) / "miniapps-test.db")
        self.db_path_patch.start()
        self.key_patch = patch.dict(
            os.environ,
            {"BACKUP_ENCRYPTION_KEY": base64.urlsafe_b64encode(b"pit-premios-test-key-32-bytes!!!").decode("ascii")},
        )
        self.key_patch.start()
        db.init_db()
        db.register_user(7001, "miniapp_test", "Mini App Test")
        db.add_points(7001, 1000, "Saldo inicial de teste")

    def tearDown(self):
        self.key_patch.stop()
        self.db_path_patch.stop()
        self.temp.cleanup()

    def balance(self):
        return int(db.get_user(7001)["points"])

    def test_daily_checkin_credits_expected_reward_once(self):
        claimed, streak, points = db.daily_claim(7001, [3, 4, 5, 6, 7, 8, 10])
        self.assertTrue(claimed)
        self.assertEqual((streak, points), (1, 3))
        self.assertEqual(self.balance(), 1003)
        again = db.daily_claim(7001, [3, 4, 5, 6, 7, 8, 10])
        self.assertEqual(again, (False, 1, 0))
        self.assertEqual(self.balance(), 1003)

    def test_chest_daily_limit_and_independent_roulette_limit(self):
        self.assertEqual(db.play_daily_game(7001, "chest", 15), 15)
        with self.assertRaisesRegex(ValueError, "tentativa deste jogo hoje"):
            db.play_daily_game(7001, "chest", 30)
        self.assertEqual(db.play_daily_game(7001, "roulette", 20), 20)
        self.assertEqual(db.game_status(7001), {"chest": 15, "roulette": 20})
        self.assertEqual(self.balance(), 1035)

    def test_zero_prize_still_consumes_daily_game_attempt(self):
        self.assertEqual(db.play_daily_game(7001, "chest", 0), 0)
        with self.assertRaisesRegex(ValueError, "tentativa deste jogo hoje"):
            db.play_daily_game(7001, "chest", 10)
        self.assertEqual(self.balance(), 1000)

    def test_game_prize_is_clamped_to_server_limit(self):
        self.assertEqual(db.play_daily_game(7001, "roulette", 999), 100)
        self.assertEqual(self.balance(), 1100)

    def test_maintenance_setting_persists_in_isolated_database(self):
        self.assertFalse(db.get_maintenance_mode())
        self.assertTrue(db.set_maintenance_mode(True))
        self.assertTrue(db.get_maintenance_mode())
        self.assertFalse(db.set_maintenance_mode(False))
        self.assertFalse(db.get_maintenance_mode())

    def test_blocked_account_state_can_be_set_and_removed(self):
        self.assertTrue(db.block_account(7001, 1, "Bloqueio de teste"))
        self.assertEqual(db.get_account_block(7001)["reason"], "Bloqueio de teste")
        self.assertTrue(db.unblock_account(7001, 1))
        self.assertIsNone(db.get_account_block(7001))

    def test_daily_game_rejects_unknown_game(self):
        with self.assertRaisesRegex(ValueError, "Jogo inválido"):
            db.play_daily_game(7001, "unknown", 10)
        self.assertEqual(self.balance(), 1000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
