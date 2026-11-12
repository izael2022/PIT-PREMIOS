import os
import threading
import unittest
from collections import deque
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ADMIN_IDS", "1")

import main


class UpdateQueueSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.original_queues = main.USER_QUEUES
        self.original_active = main.ACTIVE_USERS
        self.original_ids = main.SCHEDULED_UPDATE_IDS
        self.original_capacity = main.UPDATE_CAPACITY
        main.USER_QUEUES = {}
        main.ACTIVE_USERS = set()
        main.SCHEDULED_UPDATE_IDS = set()
        main.UPDATE_CAPACITY = threading.BoundedSemaphore(0)

    def tearDown(self):
        main.USER_QUEUES = self.original_queues
        main.ACTIVE_USERS = self.original_active
        main.SCHEDULED_UPDATE_IDS = self.original_ids
        main.UPDATE_CAPACITY = self.original_capacity

    def test_recovery_scheduling_does_not_block_when_capacity_is_full(self):
        update = {"update_id": 99001, "message": {"from": {"id": 42}, "chat": {"id": 42}, "text": "/saldo"}}
        self.assertFalse(main.schedule_update(update, wait_for_capacity=False))
        self.assertEqual(main.USER_QUEUES, {})
        self.assertNotIn(99001, main.SCHEDULED_UPDATE_IDS)

    def test_duplicate_scheduled_update_is_detected_before_capacity_wait(self):
        update = {"update_id": 99002, "message": {"from": {"id": 42}, "chat": {"id": 42}, "text": "/saldo"}}
        main.SCHEDULED_UPDATE_IDS.add(99002)
        main.USER_QUEUES[42] = deque([update])
        main.ACTIVE_USERS.add(42)
        # Semaphore is empty. Duplicate must return without attempting to acquire it.
        self.assertTrue(main.schedule_update(update, wait_for_capacity=False))
        self.assertEqual(len(main.USER_QUEUES[42]), 1)


if __name__ == "__main__":
    unittest.main()
