from __future__ import annotations

import asyncio
import shutil
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4
from unittest.mock import patch

from pano_namer.config import AppConfig
from pano_namer.main import create_app


TEST_TMP_ROOT = Path(".test_tmp")


async def asgi_request(app, method: str, path: str, *, scheme: str = "http", body: bytes = b"", headers: dict[str, str] | None = None):
    query_string = b""
    request_path = path
    if "?" in path:
        request_path, query = path.split("?", 1)
        query_string = query.encode()

    raw_headers = [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": scheme,
        "path": request_path,
        "raw_path": request_path.encode(),
        "query_string": query_string,
        "headers": raw_headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 443 if scheme == "https" else 80),
        "root_path": "",
    }
    messages = []
    sent_body = False

    async def receive():
        nonlocal sent_body
        if sent_body:
            return {"type": "http.disconnect"}
        sent_body = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    start = next(message for message in messages if message["type"] == "http.response.start")
    response_body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    response_headers = {}
    for key, value in start["headers"]:
        response_headers.setdefault(key.decode(), []).append(value.decode())
    return start["status"], response_headers, response_body


class AuthGateTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        self.base_dir = (TEST_TMP_ROOT / f"auth_{uuid4().hex}").resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.base_dir, ignore_errors=True)

    def create_test_app(self, auth_enabled: str = "true"):
        env = {
            "PANOPRO_AUTH_ENABLED": auth_enabled,
            "PANOPRO_AUTH_USERNAME": "owner",
            "PANOPRO_AUTH_PASSWORD": "secret-password",
            "PANOPRO_AUTH_SECRET": "test-signing-secret",
        }
        with patch.dict("os.environ", env, clear=False):
            return create_app(AppConfig.load(self.base_dir))

    def request(self, app, method: str, path: str, **kwargs):
        return asyncio.run(asgi_request(app, method, path, **kwargs))

    def test_auth_enabled_redirects_protected_paths_to_login_with_next(self) -> None:
        app = self.create_test_app()

        status, headers, _ = self.request(app, "GET", "/docs")

        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], ["/login?next=%2Fdocs"])

    def test_login_sets_signed_cookie_and_redirects_to_requested_path(self) -> None:
        app = self.create_test_app()
        body = urlencode({"username": "owner", "password": "secret-password", "next": "/docs"}).encode()

        status, headers, _ = self.request(
            app,
            "POST",
            "/login",
            scheme="https",
            body=body,
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], ["/docs"])
        set_cookie = headers["set-cookie"][0]
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=lax", set_cookie)
        self.assertIn("Secure", set_cookie)

        cookie = SimpleCookie(set_cookie)
        session_value = cookie["panopro_session"].value
        status, headers, _ = self.request(app, "GET", "/docs", headers={"cookie": f"panopro_session={session_value}"})
        self.assertEqual(status, 200)

    def test_wrong_login_shows_generic_error(self) -> None:
        app = self.create_test_app()
        body = urlencode({"username": "owner", "password": "wrong", "next": "/docs"}).encode()

        status, _, response_body = self.request(
            app,
            "POST",
            "/login",
            body=body,
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

        self.assertEqual(status, 401)
        self.assertIn(b"Invalid username or password.", response_body)

    def test_logout_clears_session_cookie(self) -> None:
        app = self.create_test_app()

        status, headers, _ = self.request(app, "GET", "/logout")

        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], ["/login"])
        self.assertIn("Max-Age=0", headers["set-cookie"][0])

    def test_admin_redirects_to_login_when_auth_enabled_and_logged_out(self) -> None:
        app = self.create_test_app()

        status, headers, _ = self.request(app, "GET", "/admin")

        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], ["/login?next=%2Fadmin"])

    def test_admin_returns_non_redirect_when_authenticated(self) -> None:
        app = self.create_test_app()
        body = urlencode({"username": "owner", "password": "secret-password", "next": "/admin"}).encode()
        _, login_headers, _ = self.request(
            app,
            "POST",
            "/login",
            body=body,
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        cookie = SimpleCookie(login_headers["set-cookie"][0])
        session_value = cookie["panopro_session"].value

        status, headers, _ = self.request(app, "GET", "/admin", headers={"cookie": f"panopro_session={session_value}"})

        self.assertNotIn(status, {301, 302, 303, 307, 308})
        self.assertNotIn("location", headers)

    def test_auth_disabled_preserves_open_routes(self) -> None:
        app = self.create_test_app(auth_enabled="false")

        status, headers, _ = self.request(app, "GET", "/docs")

        self.assertEqual(status, 200)
        self.assertNotIn("location", headers)


if __name__ == "__main__":
    unittest.main()
