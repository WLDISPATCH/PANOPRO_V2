from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

SESSION_COOKIE_NAME = "panopro_session"
DEFAULT_SESSION_MAX_AGE_SECONDS = 43_200


@dataclass(frozen=True, slots=True)
class AuthGateSettings:
    """Environment-backed settings for the private login gate."""

    enabled: bool
    username: str
    password: str
    secret: str
    session_max_age_seconds: int = DEFAULT_SESSION_MAX_AGE_SECONDS

    @classmethod
    def from_env(cls) -> "AuthGateSettings":
        enabled = os.getenv("PANOPRO_AUTH_ENABLED", "").lower() == "true"
        max_age_raw = os.getenv("PANOPRO_SESSION_MAX_AGE_SECONDS", str(DEFAULT_SESSION_MAX_AGE_SECONDS))
        try:
            max_age = int(max_age_raw)
        except ValueError:
            max_age = DEFAULT_SESSION_MAX_AGE_SECONDS

        settings = cls(
            enabled=enabled,
            username=os.getenv("PANOPRO_AUTH_USERNAME", ""),
            password=os.getenv("PANOPRO_AUTH_PASSWORD", ""),
            secret=os.getenv("PANOPRO_AUTH_SECRET", ""),
            session_max_age_seconds=max_age,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.enabled:
            return
        missing = [
            name
            for name, value in (
                ("PANOPRO_AUTH_USERNAME", self.username),
                ("PANOPRO_AUTH_PASSWORD", self.password),
                ("PANOPRO_AUTH_SECRET", self.secret),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"Authentication is enabled but these environment variables are missing: {', '.join(missing)}")
        if self.session_max_age_seconds <= 0:
            raise RuntimeError("PANOPRO_SESSION_MAX_AGE_SECONDS must be greater than 0 when authentication is enabled.")


def install_auth_gate(app: FastAPI, settings: AuthGateSettings | None = None) -> None:
    """Install a small app-level login gate.

    This private-tool gate is intentionally simple: when enabled, every request
    is blocked by middleware unless a valid signed session cookie is present.
    Only /login and /logout are public so users can establish or clear a session.
    """

    auth_settings = settings or AuthGateSettings.from_env()
    app.state.auth_gate_settings = auth_settings

    @app.get("/login", include_in_schema=False)
    async def login_page(request: Request) -> HTMLResponse:
        return render_login_page(next_path=safe_next_path(request.query_params.get("next")), error=False)

    @app.post("/login", include_in_schema=False)
    async def login_submit(request: Request) -> Response:
        form = await request.form()
        username = str(form.get("username", ""))
        password = str(form.get("password", ""))
        next_path = safe_next_path(str(form.get("next", "")))

        if not credentials_match(username, password, auth_settings):
            return render_login_page(next_path=next_path, error=True, status_code=401)

        response = RedirectResponse(next_path, status_code=303)
        set_session_cookie(response, request, auth_settings)
        return response

    @app.get("/logout", include_in_schema=False)
    async def logout(request: Request) -> RedirectResponse:
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(
            SESSION_COOKIE_NAME,
            path="/",
            httponly=True,
            samesite="lax",
            secure=is_secure_request(request),
        )
        return response

    if auth_settings.enabled:
        app.add_middleware(AuthGateMiddleware, settings=auth_settings)


class AuthGateMiddleware(BaseHTTPMiddleware):
    """Middleware that protects all app routes by default.

    The middleware runs before route handling, including FastAPI's built-in docs
    and OpenAPI endpoints, so public/onlooker traffic is forced through /login.
    """

    def __init__(self, app: Any, settings: AuthGateSettings) -> None:
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        if request.url.path in {"/login", "/logout"}:
            return await call_next(request)

        if is_authenticated(request, self.settings):
            return await call_next(request)

        params = urlencode({"next": requested_path(request)})
        return RedirectResponse(f"/login?{params}", status_code=303)


def credentials_match(username: str, password: str, settings: AuthGateSettings) -> bool:
    if not settings.enabled:
        return True
    return secrets.compare_digest(username, settings.username) and secrets.compare_digest(password, settings.password)


def is_authenticated(request: Request, settings: AuthGateSettings) -> bool:
    if not settings.enabled:
        return True
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME, "")
    payload = verify_session_cookie(cookie_value, settings.secret)
    return bool(payload and payload.get("authenticated") is True and int(payload.get("exp", 0)) >= int(time.time()))


def set_session_cookie(response: Response, request: Request, settings: AuthGateSettings) -> None:
    now = int(time.time())
    value = sign_session_payload(
        {"authenticated": True, "iat": now, "exp": now + settings.session_max_age_seconds},
        settings.secret,
    )
    response.set_cookie(
        SESSION_COOKIE_NAME,
        value,
        max_age=settings.session_max_age_seconds,
        path="/",
        httponly=True,
        samesite="lax",
        secure=is_secure_request(request),
    )


def sign_session_payload(payload: dict[str, Any], secret: str) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).decode().rstrip("=")
    signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def verify_session_cookie(cookie_value: str, secret: str) -> dict[str, Any] | None:
    try:
        body, signature = cookie_value.rsplit(".", 1)
    except ValueError:
        return None

    expected_signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not secrets.compare_digest(signature, expected_signature):
        return None

    try:
        padded_body = body + "=" * (-len(body) % 4)
        decoded = base64.urlsafe_b64decode(padded_body.encode())
        payload = json.loads(decoded)
    except (ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def requested_path(request: Request) -> str:
    path = request.url.path or "/"
    if request.url.query:
        return f"{path}?{request.url.query}"
    return path


def safe_next_path(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


def is_secure_request(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    return request.url.scheme == "https" or forwarded_proto == "https"


def render_login_page(next_path: str, error: bool, status_code: int = 200) -> HTMLResponse:
    error_html = '<div class="error">Invalid username or password.</div>' if error else ""
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PanoPro Login</title>
  <style>
    :root {{ color-scheme: light dark; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ min-height: 100vh; margin: 0; display: grid; place-items: center; background: #0f172a; color: #0f172a; }}
    main {{ width: min(92vw, 380px); padding: 2rem; border-radius: 18px; background: #ffffff; box-shadow: 0 24px 80px rgba(15, 23, 42, 0.35); }}
    h1 {{ margin: 0 0 0.35rem; font-size: 1.6rem; }}
    p {{ margin: 0 0 1.5rem; color: #64748b; }}
    label {{ display: block; margin: 0.9rem 0 0.35rem; font-weight: 700; font-size: 0.92rem; }}
    input {{ width: 100%; box-sizing: border-box; border: 1px solid #cbd5e1; border-radius: 10px; padding: 0.75rem 0.85rem; font: inherit; }}
    button {{ width: 100%; margin-top: 1.25rem; border: 0; border-radius: 10px; padding: 0.8rem 1rem; font: inherit; font-weight: 800; color: white; background: #2563eb; cursor: pointer; }}
    button:hover {{ background: #1d4ed8; }}
    .error {{ margin-bottom: 1rem; border-radius: 10px; padding: 0.75rem; background: #fee2e2; color: #991b1b; font-weight: 700; }}
  </style>
</head>
<body>
  <main>
    <h1>PanoPro</h1>
    <p>Sign in to continue.</p>
    {error_html}
    <form method="post" action="/login">
      <input type="hidden" name="next" value="{html_escape(next_path)}">
      <label for="username">Username</label>
      <input id="username" name="username" autocomplete="username" autofocus required>
      <label for="password">Password</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required>
      <button type="submit">Sign in</button>
    </form>
  </main>
</body>
</html>"""
    return HTMLResponse(html, status_code=status_code)


def html_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
