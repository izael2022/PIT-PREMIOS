import os
import unittest
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ADMIN_IDS", "1")

import main as bot


class PrivacyAndResilienceTests(unittest.TestCase):
    def test_pix_key_validation(self):
        self.assertTrue(bot._valid_pix_key("CPF", "529.982.247-25"))
        self.assertFalse(bot._valid_pix_key("CPF", "111.111.111-11"))
        self.assertFalse(bot._valid_pix_key("CPF", "123"))
        self.assertTrue(bot._valid_pix_key("EMAIL", "cliente@example.com"))
        self.assertFalse(bot._valid_pix_key("EMAIL", "cliente@"))
        self.assertTrue(bot._valid_pix_key("TELEFONE", "+5511999999999"))
        self.assertFalse(bot._valid_pix_key("TELEFONE", "abc"))
        self.assertTrue(bot._valid_pix_key("ALEATORIA", "123e4567-e89b-12d3-a456-426614174000"))
        self.assertFalse(bot._valid_pix_key("ALEATORIA", "not-a-uuid"))

    def test_commands_in_groups_do_not_open_user_data(self):
        message = {
            "text": "/saldo",
            "chat": {"id": -100123, "type": "supergroup"},
            "from": {"id": 42},
        }
        with patch.object(bot, "send") as send, patch.object(bot, "balance") as balance:
            bot.command(message)
        balance.assert_not_called()
        self.assertIn("privada", send.call_args.args[1].lower())

    def test_start_in_groups_only_shows_private_bot_link(self):
        message = {
            "text": "/start",
            "chat": {"id": -100123, "type": "group"},
            "from": {"id": 42},
        }
        with patch.object(bot, "send") as send, patch.object(bot, "start") as start:
            bot.command(message)
        start.assert_not_called()
        self.assertIn("https://t.me/", send.call_args.args[1])

    def test_group_callback_is_rejected_before_dispatch(self):
        callback = {
            "id": "callback-1",
            "data": "wallet",
            "from": {"id": 42},
            "message": {"chat": {"id": -100123, "type": "group"}},
        }
        with patch.object(bot, "api") as api, patch.object(bot, "balance") as balance:
            bot.callback(callback)
        api.assert_called_once()
        balance.assert_not_called()
        self.assertTrue(api.call_args.args[1]["show_alert"])

    def test_failed_update_is_not_marked_completed(self):
        update = {
            "update_id": 123,
            "message": {
                "text": "/saldo",
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42},
            },
        }
        with patch.object(bot.db, "update_was_processed", return_value=False), \
             patch.object(bot, "command", side_effect=RuntimeError("temporary failure")), \
             patch.object(bot.db, "mark_update_processed") as mark:
            with self.assertRaises(RuntimeError):
                bot.process_update(update)
        mark.assert_not_called()

    def test_backup_retry_schedule_is_bounded(self):
        self.assertEqual(bot.backup_retry_delay(1), 300)
        self.assertEqual(bot.backup_retry_delay(2), 900)
        self.assertEqual(bot.backup_retry_delay(3), 3600)
        self.assertEqual(bot.backup_retry_delay(4), 21600)
        self.assertEqual(bot.backup_retry_delay(20), 21600)

    def test_telegram_startup_retry_uses_progressive_backoff(self):
        self.assertEqual(bot.telegram_reconnect_delay(1), 5)
        self.assertEqual(bot.telegram_reconnect_delay(2), 10)
        self.assertEqual(bot.telegram_reconnect_delay(5), 60)

    def test_startup_authentication_retries_after_temporary_failure(self):
        with patch.object(bot, "api", side_effect=[RuntimeError("offline"), {"username": "pit_test"}]) as api_mock, patch.object(bot.time, "sleep") as sleep, patch.object(bot, "report_health_issue") as alert:
            result = bot.telegram_get_me_with_retry()
        self.assertEqual(result["username"], "pit_test")
        self.assertEqual(api_mock.call_count, 2)
        sleep.assert_called_once_with(5)
        alert.assert_called_once()


if __name__ == "__main__":
    unittest.main()
