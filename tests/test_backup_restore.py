import os
import sqlite3
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from backup_utils import (
    create_backup_archive, decrypt_backup_archive, encrypt_backup_archive,
    restore_backup_archive, validate_backup_archive,
)


class BackupRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source = self.root / "source.db"
        self.key = os.urandom(32)
        connection = sqlite3.connect(self.source)
        connection.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE users(user_id INTEGER PRIMARY KEY, points INTEGER NOT NULL);
            CREATE TABLE referrals(id INTEGER PRIMARY KEY, referrer_id INTEGER NOT NULL REFERENCES users(user_id));
            CREATE TABLE point_history(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(user_id), amount INTEGER NOT NULL);
            CREATE TABLE payouts(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(user_id), status TEXT NOT NULL);
            INSERT INTO users VALUES(101, 4321);
            INSERT INTO users VALUES(202, 987);
            INSERT INTO referrals VALUES(1, 101);
            INSERT INTO point_history VALUES(1, 101, 4321);
            INSERT INTO payouts VALUES(1, 101, 'pending');
        """)
        connection.commit()
        connection.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_backup_is_encrypted_and_valid_sqlite_snapshot(self):
        payload = create_backup_archive(self.source, self.key)
        self.assertTrue(payload.startswith(b"PITBKP1"))
        self.assertNotIn(b"SQLite format 3", payload)
        self.assertTrue(validate_backup_archive(payload, self.key).startswith(b"SQLite format 3"))

    def test_restore_preserves_users_balances_referrals_history_and_payouts(self):
        destination = restore_backup_archive(create_backup_archive(self.source, self.key), self.root / "restored.db", self.key)
        connection = sqlite3.connect(destination)
        try:
            self.assertEqual(connection.execute("SELECT user_id,points FROM users ORDER BY user_id").fetchall(), [(101,4321),(202,987)])
            self.assertEqual(connection.execute("SELECT referrer_id FROM referrals").fetchone(), (101,))
            self.assertEqual(connection.execute("SELECT user_id,amount FROM point_history").fetchone(), (101,4321))
            self.assertEqual(connection.execute("SELECT user_id,status FROM payouts").fetchone(), (101,"pending"))
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            connection.close()

    def test_restore_never_overwrites_existing_file(self):
        destination = self.root / "existing.db"
        destination.write_bytes(b"preserve me")
        with self.assertRaises(FileExistsError):
            restore_backup_archive(create_backup_archive(self.source, self.key), destination, self.key)
        self.assertEqual(destination.read_bytes(), b"preserve me")

    def test_rejects_corrupt_ciphertext(self):
        payload = bytearray(create_backup_archive(self.source, self.key))
        payload[-1] ^= 1
        with self.assertRaises(ValueError):
            validate_backup_archive(bytes(payload), self.key)

    def test_rejects_wrong_key(self):
        with self.assertRaises(ValueError):
            validate_backup_archive(create_backup_archive(self.source, self.key), os.urandom(32))

    def test_rejects_missing_key(self):
        with self.assertRaises(ValueError):
            validate_backup_archive(create_backup_archive(self.source, self.key), b"")

    def test_rejects_plaintext_legacy_zip(self):
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("pit_premios.db", b"not sqlite")
        with self.assertRaises(ValueError):
            validate_backup_archive(buffer.getvalue(), self.key)

    def test_rejects_unexpected_zip_member_after_decryption(self):
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("../unsafe.db", b"invalid")
        encrypted = encrypt_backup_archive(buffer.getvalue(), self.key)
        with self.assertRaises(ValueError):
            validate_backup_archive(encrypted, self.key)

    def test_rejects_invalid_sqlite_payload_after_decryption(self):
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("pit_premios.db", b"not sqlite")
        with self.assertRaises((ValueError, sqlite3.DatabaseError)):
            validate_backup_archive(encrypt_backup_archive(buffer.getvalue(), self.key), self.key)

    def test_backup_does_not_modify_source(self):
        before = self.source.read_bytes()
        create_backup_archive(self.source, self.key)
        self.assertEqual(self.source.read_bytes(), before)

    def test_decrypt_rejects_unrecognized_envelope(self):
        with self.assertRaises(ValueError):
            decrypt_backup_archive(b"not encrypted", self.key)


if __name__ == "__main__":
    unittest.main()
