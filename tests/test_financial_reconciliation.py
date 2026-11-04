import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ADMIN_IDS", "1")

import database as db


class FinancialReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        db.DATABASE_PATH = Path(self.folder.name) / "audit.db"
        db.init_db()
        db.register_user(8801, "audit", "Audit")

    def tearDown(self):
        self.folder.cleanup()

    def test_wallet_and_ledger_reconcile_after_credit(self):
        db.add_points(8801, 250, "Crédito de teste")
        report = db.financial_dashboard()
        self.assertEqual(report["wallet_balance_points"], 250)
        self.assertEqual(report["ledger_net_points"], 250)
        self.assertEqual(report["ledger_difference"], 0)
        self.assertTrue(report["ledger_reconciled"])

    def test_legacy_difference_is_flagged_without_auto_adjustment(self):
        db.add_points(8801, 250, "Crédito de teste")
        with db.connect() as conn:
            conn.execute("UPDATE users SET points=points+25 WHERE user_id=?", (8801,))
            conn.commit()
        report = db.financial_dashboard()
        self.assertEqual(report["ledger_difference"], 25)
        self.assertFalse(report["ledger_reconciled"])
        self.assertEqual(db.get_user(8801)["points"], 275)

    def test_schema_initialization_preserves_existing_balance(self):
        db.add_points(8801, 100, "Saldo preservado")
        db.init_db()
        self.assertEqual(db.get_user(8801)["points"], 100)
        with db.connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='account_blocks'").fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
