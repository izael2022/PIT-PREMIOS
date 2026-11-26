"""Regression tests for surprise campaign scheduling and redemption windows.

Run with: python -m unittest discover -s tests
Uses temporary SQLite databases only; never touches production data.
"""
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import systems_extra


class SurpriseCampaignWindowTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        systems_extra.initialize(self.path)
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE users(user_id INTEGER PRIMARY KEY, points INTEGER NOT NULL DEFAULT 0)")
            conn.execute("CREATE TABLE point_history(user_id INTEGER NOT NULL, amount INTEGER NOT NULL, reason TEXT NOT NULL)")
            conn.execute("INSERT INTO users(user_id,points) VALUES(123,0)")
        self.now = datetime.now(timezone.utc)

    def tearDown(self):
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def create(self, start, end):
        return systems_extra.create_campaign(
            self.path, "surprise", "Teste janela", "", start.isoformat(),
            end.isoformat(), 100, 0, 1
        )

    def test_claim_rejected_before_window(self):
        cid = self.create(self.now + timedelta(hours=1), self.now + timedelta(hours=2))
        with self.assertRaisesRegex(ValueError, "fora do período"):
            systems_extra.claim_campaign(self.path, cid, 123)

    def test_claim_rejected_after_window(self):
        cid = self.create(self.now - timedelta(hours=2), self.now - timedelta(hours=1))
        with self.assertRaisesRegex(ValueError, "fora do período"):
            systems_extra.claim_campaign(self.path, cid, 123)

    def test_claim_allowed_inside_window_and_reward_credited_once(self):
        cid = self.create(self.now - timedelta(minutes=1), self.now + timedelta(minutes=10))
        self.assertEqual(systems_extra.claim_campaign(self.path, cid, 123), 100)
        with self.assertRaisesRegex(ValueError, "já resgatada"):
            systems_extra.claim_campaign(self.path, cid, 123)
        with sqlite3.connect(self.path) as conn:
            points = conn.execute("SELECT points FROM users WHERE user_id=123").fetchone()[0]
            history = conn.execute("SELECT COUNT(*) FROM point_history WHERE user_id=123").fetchone()[0]
        self.assertEqual(points, 100)
        self.assertEqual(history, 1)


if __name__ == "__main__":
    unittest.main()
