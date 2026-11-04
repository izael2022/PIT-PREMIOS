import os
import unittest
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ADMIN_IDS", "1")

import main as bot


class RuntimeMetricsTests(unittest.TestCase):
    def test_snapshot_separates_in_flight_and_waiting_updates(self):
        with patch.object(bot, "UPDATE_IN_FLIGHT", 2), patch.object(bot, "UPDATE_COMPLETED_TOTAL", 17), patch.object(bot, "UPDATE_FAILED_TOTAL", 3), patch.object(bot, "USER_QUEUES", {8801: [1, 2, 3]}), patch.object(bot, "ACTIVE_USERS", {8801}):
            snapshot = bot.update_runtime_snapshot()
        self.assertEqual(snapshot["in_flight"], 2)
        self.assertEqual(snapshot["queued"], 3)
        self.assertEqual(snapshot["active_users"], 1)
        self.assertEqual(snapshot["completed"], 17)
        self.assertEqual(snapshot["failed"], 3)


if __name__ == "__main__":
    unittest.main()
