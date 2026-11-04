import os
import unittest

os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ADMIN_IDS", "1")

import main as bot


class TelegramReconnectTests(unittest.TestCase):
    def test_backoff_grows_after_consecutive_failures(self):
        self.assertEqual(bot.telegram_reconnect_delay(1), 5)
        self.assertEqual(bot.telegram_reconnect_delay(2), 10)
        self.assertEqual(bot.telegram_reconnect_delay(3), 20)
        self.assertEqual(bot.telegram_reconnect_delay(4), 40)

    def test_backoff_is_capped_at_one_minute(self):
        self.assertEqual(bot.telegram_reconnect_delay(5), 60)
        self.assertEqual(bot.telegram_reconnect_delay(20), 60)

    def test_backoff_handles_zero_or_negative_failure_count(self):
        self.assertEqual(bot.telegram_reconnect_delay(0), 5)
        self.assertEqual(bot.telegram_reconnect_delay(-3), 5)


if __name__ == "__main__":
    unittest.main()
