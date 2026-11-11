"""Testes isolados de segurança Pix, ciclo de saques e recuperação de backup.

Todos os testes usam SQLite temporário. Nenhum pagamento Pix real é iniciado.
"""
import base64
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database as db
from backup_utils import (
    create_backup_archive,
    decrypt_backup_archive,
    restore_backup_archive,
    validate_backup_archive,
)


TEST_KEY = base64.urlsafe_b64encode(b"pit-premios-test-key-32-bytes!!").decode("ascii")


class IsolatedDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pit-pix-tests-")
        self.db_path = Path(self.temp.name) / "test.db"
        self.path_patch = patch.object(db, "DATABASE_PATH", self.db_path)
        self.path_patch.start()
        self.key_patch = patch.dict(os.environ, {"BACKUP_ENCRYPTION_KEY": TEST_KEY})
        self.key_patch.start()
        db.init_db()
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO users(user_id,first_name,points) VALUES(?,?,?)",
                (101, "Teste", 5000),
            )
            conn.commit()

    def tearDown(self):
        self.key_patch.stop()
        self.path_patch.stop()
        self.temp.cleanup()

    def raw_payout_key(self, payout_id):
        with db.connect() as conn:
            return conn.execute(
                "SELECT pix_key FROM payout_requests WHERE id=?", (payout_id,)
            ).fetchone()["pix_key"]

    def test_pix_profile_and_setup_are_encrypted_and_round_trip(self):
        secret = "teste.pix+seguro@example.com"
        db.set_pix_setup_step(101, "owner", "EMAIL", secret)
        setup = db.get_pix_setup_step(101)
        self.assertEqual(setup["pix_key"], secret)
        with db.connect() as conn:
            stored_setup = conn.execute(
                "SELECT pix_key_encrypted FROM pix_setup_state WHERE user_id=101"
            ).fetchone()["pix_key_encrypted"]
        self.assertNotIn(secret, stored_setup)

        db.save_pix_profile(101, "EMAIL", secret, "Titular de Teste")
        profile = db.get_pix_profile(101)
        self.assertEqual(profile["pix_key"], secret)
        self.assertEqual(profile["status"], "pending")
        with db.connect() as conn:
            stored = conn.execute(
                "SELECT pix_key_encrypted FROM pix_profiles WHERE user_id=101"
            ).fetchone()["pix_key_encrypted"]
        self.assertNotIn(secret, stored)
        self.assertNotEqual(stored, secret)

    def test_pix_ciphertext_authentication_rejects_tampering(self):
        db.save_pix_profile(101, "EMAIL", "chave.teste@example.com", "Titular")
        with db.connect() as conn:
            stored = conn.execute(
                "SELECT pix_key_encrypted FROM pix_profiles WHERE user_id=101"
            ).fetchone()["pix_key_encrypted"]
        raw = bytearray(base64.urlsafe_b64decode(stored.encode("ascii")))
        raw[-1] ^= 1
        corrupted = base64.urlsafe_b64encode(raw).decode("ascii")
        with patch.object(db, "_decrypt_pix_value", wraps=db._decrypt_pix_value):
            with self.assertRaises(Exception):
                db._decrypt_pix_value(corrupted)

    def test_legacy_plaintext_payout_key_is_migrated_without_data_loss(self):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO payout_requests(user_id,points,amount_cents,pix_key,pix_key_type) "
                "VALUES(101,1000,1000,?,'EMAIL')",
                ("legacy@example.com",),
            )
            conn.commit()
        rows = db.pending_payouts()
        self.assertEqual(rows[0]["pix_key"], "legacy@example.com")
        stored = self.raw_payout_key(rows[0]["id"])
        self.assertTrue(stored.startswith("enc:v1:"))
        self.assertNotIn("legacy@example.com", stored)
        # Segunda leitura é idempotente e preserva o mesmo valor cifrado.
        self.assertEqual(db.pending_payouts()[0]["pix_key"], "legacy@example.com")
        self.assertEqual(self.raw_payout_key(rows[0]["id"]), stored)

    def test_payout_create_cancel_restores_points_exactly_once(self):
        before = db.get_user(101)["points"]
        payout_id = db.create_payout_request(
            101, 1000, "teste@example.com", "EMAIL", min_points=1000, update_id=7001
        )
        self.assertEqual(db.get_user(101)["points"], before - 1000)
        self.assertTrue(self.raw_payout_key(payout_id).startswith("enc:v1:"))
        cancelled = db.cancel_payout_request(101, payout_id)
        self.assertIsNotNone(cancelled)
        self.assertEqual(db.get_user(101)["points"], before)
        self.assertIsNone(db.cancel_payout_request(101, payout_id))
        self.assertEqual(db.get_user(101)["points"], before)

    def test_payout_rejection_refunds_and_duplicate_review_is_noop(self):
        before = db.get_user(101)["points"]
        payout_id = db.create_payout_request(
            101, 1200, "teste@example.com", "EMAIL", min_points=1000
        )
        reviewed = db.review_payout(payout_id, 9001, False)
        self.assertEqual(reviewed["pix_key"], "teste@example.com")
        self.assertEqual(db.get_user(101)["points"], before)
        self.assertIsNone(db.review_payout(payout_id, 9001, False))
        self.assertEqual(db.get_user(101)["points"], before)

    def test_payout_confirmation_records_without_external_payment_or_balance_change(self):
        before = db.get_user(101)["points"]
        payout_id = db.create_payout_request(
            101, 1500, "teste@example.com", "EMAIL", min_points=1000
        )
        after_reservation = db.get_user(101)["points"]
        reviewed = db.review_payout(payout_id, 9001, True)
        self.assertEqual(reviewed["pix_key"], "teste@example.com")
        self.assertEqual(db.get_user(101)["points"], after_reservation)
        self.assertEqual(after_reservation, before - 1500)
        self.assertIsNone(db.review_payout(payout_id, 9001, True))
        # O teste só confirma o estado no SQLite; não chama API bancária/Pix.
        with db.connect() as conn:
            reason = conn.execute(
                "SELECT reason FROM point_history WHERE user_id=101 ORDER BY id DESC LIMIT 1"
            ).fetchone()["reason"]
        self.assertIn("Pagamento Pix confirmado", reason)

    def test_real_backup_restores_into_separate_database_with_same_records(self):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO point_history(user_id,amount,reason) VALUES(101,25,'registro de teste')"
            )
            conn.commit()
        encrypted = create_backup_archive(self.db_path, TEST_KEY)
        self.assertTrue(encrypted.startswith(b"PITBKP1"))
        self.assertTrue(validate_backup_archive(encrypted, TEST_KEY))
        self.assertNotIn(b"registro de teste", encrypted)
        with self.assertRaises(ValueError):
            decrypt_backup_archive(encrypted, base64.urlsafe_b64encode(b"wrong-key-32-bytes-for-test!!!").decode("ascii"))
        restored = Path(self.temp.name) / "recovery" / "restored.db"
        restore_backup_archive(encrypted, restored, TEST_KEY)
        with sqlite3.connect(restored) as conn:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(
                conn.execute("SELECT points FROM users WHERE user_id=101").fetchone()[0],
                5000,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM point_history WHERE reason='registro de teste'").fetchone()[0],
                1,
            )
        with self.assertRaises(FileExistsError):
            restore_backup_archive(encrypted, restored, TEST_KEY)
        # Banco original segue presente e inalterado.
        self.assertTrue(self.db_path.is_file())
        self.assertEqual(db.get_user(101)["points"], 5000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
