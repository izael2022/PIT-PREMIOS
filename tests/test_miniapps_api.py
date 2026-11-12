import base64
import hashlib
import hmac
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ADMIN_IDS", "1")
os.environ.setdefault(
    "BACKUP_ENCRYPTION_KEY",
    base64.urlsafe_b64encode(b"pit-premios-test-key-32-bytes!!!").decode("ascii"),
)

import database as db
import main as app


class MiniAppApiIntegrationTests(unittest.TestCase):
    """Testa a API HTTP real com SQLite temporário e initData assinado de teste."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path_patch = patch.object(db, "DATABASE_PATH", Path(self.temp.name) / "api-test.db")
        self.db_path_patch.start()
        db.init_db()
        db.register_user(7001, "miniapp_user", "Usuário de teste")
        db.add_points(7001, 1000, "Saldo inicial de teste")
        db.register_user(1, "miniapp_admin", "Administrador de teste")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.MiniAppHandler)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=2)
        self.db_path_patch.stop()
        self.temp.cleanup()

    def signed_init_data(self, user_id=7001, auth_date=None, token=None):
        fields = {
            "auth_date": str(int(time.time()) if auth_date is None else int(auth_date)),
            "user": json.dumps({"id": user_id, "first_name": "Teste"}, separators=(",", ":")),
        }
        check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
        secret = hmac.new(
            b"WebAppData",
            (token or app.BOT_TOKEN).encode("utf-8"),
            hashlib.sha256,
        ).digest()
        fields["hash"] = hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        return urllib.parse.urlencode(fields)

    def post(self, path, payload=None, init_data=None, origin="https://izael2022.github.io"):
        body = json.dumps(payload or {}).encode("utf-8")
        headers = {"Origin": origin, "Content-Type": "application/json"}
        if init_data is not None:
            headers["Authorization"] = "tma " + init_data
        request = urllib.request.Request(
            self.base_url + path, data=body, headers=headers, method="POST"
        )
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        return response.code, json.loads(response.read().decode("utf-8"))

    def test_rejects_unapproved_origin(self):
        status, result = self.post(
            "/api/miniapps/me",
            init_data=self.signed_init_data(),
            origin="https://example.invalid",
        )
        self.assertEqual(status, 403)
        self.assertFalse(result["ok"])

    def test_rejects_missing_and_invalid_telegram_authentication(self):
        status, _ = self.post("/api/miniapps/me")
        self.assertEqual(status, 400)

        invalid = self.signed_init_data().replace("hash=", "hash=0")
        status, result = self.post("/api/miniapps/me", init_data=invalid)
        self.assertEqual(status, 400)
        self.assertFalse(result["ok"])

        signed = self.signed_init_data()
        duplicate_hash = signed + "&hash=" + urllib.parse.parse_qs(signed)["hash"][0]
        status, result = self.post("/api/miniapps/me", init_data=duplicate_hash)
        self.assertEqual(status, 400)
        self.assertFalse(result["ok"])

    def test_rejects_expired_telegram_session(self):
        expired = self.signed_init_data(auth_date=int(time.time()) - 86401)
        status, result = self.post("/api/miniapps/me", init_data=expired)
        self.assertEqual(status, 400)
        self.assertIn("expirada", result["error"].lower())

    def test_valid_user_can_read_balance(self):
        status, result = self.post(
            "/api/miniapps/me", init_data=self.signed_init_data()
        )
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])
        self.assertEqual(result["balance"], 1000)
        self.assertIn("next_daily_reward", result)

    def test_maintenance_blocks_users_but_allows_admin(self):
        db.set_maintenance_mode(True)
        status, _ = self.post(
            "/api/miniapps/me", init_data=self.signed_init_data(7001)
        )
        self.assertEqual(status, 503)

        status, result = self.post(
            "/api/miniapps/me", init_data=self.signed_init_data(1)
        )
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])

    def test_blocked_user_cannot_access_api(self):
        db.block_account(7001, 1, "Bloqueio de teste")
        status, result = self.post(
            "/api/miniapps/me", init_data=self.signed_init_data()
        )
        self.assertEqual(status, 403)
        self.assertIn("bloqueada", result["error"].lower())

    def test_daily_checkin_credits_once_through_http(self):
        path = "/api/miniapps/calendar/claim"
        auth = self.signed_init_data()
        status, result = self.post(path, init_data=auth)
        self.assertEqual(status, 200)
        self.assertEqual(result["points"], 3)
        self.assertEqual(result["balance"], 1003)

        status, result = self.post(path, init_data=auth)
        self.assertEqual(status, 409)
        self.assertFalse(result["ok"])
        self.assertEqual(db.get_user(7001)["points"], 1003)

    def test_surprise_game_cannot_be_played_twice_in_one_day(self):
        path = "/api/miniapps/surprise/open"
        auth = self.signed_init_data()
        status, first = self.post(path, {"chest": 1}, auth)
        self.assertEqual(status, 200)
        self.assertTrue(first["ok"])

        status, second = self.post(path, {"chest": 2}, auth)
        self.assertEqual(status, 400)
        self.assertFalse(second["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
