"""Optional sign-in (username + password) for the whole agent: on this PC and from the phone.

Off until a password is set in Settings › الأمان. Then every page and API call needs a signed
session cookie; only the login page, static files and two PC-only endpoints (stop, version, used by
the .bat files) stay open.

* The password is never stored: only a scrypt hash with a random salt, in ``data/login.json``.
* The cookie is signed with a secret in ``data/login-secret.bin`` and expires (12 hours, or 30 days
  with «تذكرني»). Changing the password or «تسجيل الخروج من كل الأجهزة» invalidates every cookie.
* Wrong passwords are rate-limited per device (5 tries, then 10 minutes).
* Forgotten password: on the PC run ``06_reset_login.bat`` (deletes ``data/login.json``).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from pathlib import Path

from app.errors import AgentError

log = logging.getLogger(__name__)

COOKIE = "kla_login"
SESSION_SECONDS = 12 * 3600
REMEMBER_SECONDS = 30 * 24 * 3600
MAX_FAILURES = 5
LOCK_SECONDS = 600
MIN_PASSWORD = 8
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def _hash(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT).hex()


def login_configured(data_path: Path) -> bool:
    """Whether a sign-in password is set (read by run.py before the app starts)."""
    try:
        return bool(json.loads((data_path / "login.json").read_text(encoding="utf-8")).get("hash"))
    except (OSError, ValueError):
        return False


class LoginService:
    def __init__(self, data_path: Path) -> None:
        self.file = data_path / "login.json"
        self._secret_file = data_path / "login-secret.bin"
        self._secret: bytes | None = None
        self._cache: tuple[float, dict] = (-1.0, {})
        self._failures: dict[str, list[float]] = {}

    # ------------------------------------------------------------------ storage
    def _data(self) -> dict:
        """The stored login (re-read when the file changes, e.g. after 06_reset_login.bat)."""
        try:
            mtime = self.file.stat().st_mtime
        except OSError:
            self._cache = (-1.0, {})
            return {}
        if mtime != self._cache[0]:
            try:
                self._cache = (mtime, json.loads(self.file.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                log.error("data/login.json is unreadable; sign-in stays required until it is fixed or reset")
                self._cache = (mtime, {"hash": "!", "username": "", "salt": "", "nonce": ""})
        return self._cache[1]

    def _write(self, data: dict) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.file)
        self._cache = (-1.0, {})

    def _key(self) -> bytes:
        if self._secret is None:
            try:
                data = self._secret_file.read_bytes()
            except OSError:
                data = b""
            if len(data) < 32:
                data = secrets.token_bytes(32)
                self._secret_file.parent.mkdir(parents=True, exist_ok=True)
                self._secret_file.write_bytes(data)
            self._secret = data
        return self._secret

    # ------------------------------------------------------------------ state
    @property
    def enabled(self) -> bool:
        return bool(self._data().get("hash"))

    @property
    def username(self) -> str:
        return self._data().get("username", "")

    def status(self) -> dict:
        return {"enabled": self.enabled, "username": self.username}

    # ------------------------------------------------------------------ passwords
    def _password_ok(self, password: str) -> bool:
        d = self._data()
        try:
            salt = bytes.fromhex(d.get("salt", ""))
        except ValueError:
            return False
        return bool(salt) and hmac.compare_digest(_hash(password, salt), d.get("hash", ""))

    def locked_for(self, client: str) -> int:
        now = time.time()
        recent = [t for t in self._failures.get(client, []) if now - t < LOCK_SECONDS]
        self._failures[client] = recent
        return int(LOCK_SECONDS - (now - recent[0])) + 1 if len(recent) >= MAX_FAILURES else 0

    def check(self, client: str, username: str, password: str) -> bool:
        ok = (self.enabled and hmac.compare_digest(username.strip().casefold().encode(), self.username.casefold().encode())
              and self._password_ok(password))
        if ok:
            self._failures.pop(client, None)
        else:
            self._failures.setdefault(client, []).append(time.time())
            log.warning("Wrong sign-in from %s", client)
        return ok

    def _require_current(self, client: str, current_password: str) -> None:
        if not self.enabled:
            return
        wait = self.locked_for(client)
        if wait:
            raise AgentError("LOGIN_LOCKED", f"محاولات كثيرة خاطئة. حاول بعد {wait // 60 + 1} دقيقة.", status_code=429)
        if not self._password_ok(current_password):
            self._failures.setdefault(client, []).append(time.time())
            raise AgentError("WRONG_PASSWORD", "كلمة المرور الحالية غير صحيحة.")
        self._failures.pop(client, None)

    def set_password(self, client: str, username: str, password: str, current_password: str = "") -> None:
        username = username.strip()
        if not 2 <= len(username) <= 40:
            raise AgentError("USERNAME_INVALID", "اكتب اسم مستخدم (من 2 إلى 40 حرفًا).")
        if len(password) < MIN_PASSWORD:
            raise AgentError("PASSWORD_WEAK", f"كلمة المرور قصيرة: {MIN_PASSWORD} أحرف على الأقل.")
        if password.isdigit() and len(set(password)) <= 2:
            raise AgentError("PASSWORD_WEAK", "كلمة المرور سهلة جدًا. استخدم حروفًا وأرقامًا.")
        self._require_current(client, current_password)
        salt = secrets.token_bytes(16)
        self._write({"username": username, "salt": salt.hex(), "hash": _hash(password, salt),
                     "nonce": secrets.token_hex(8), "updated": int(time.time())})
        log.info("Sign-in password set for %r", username)

    def disable(self, client: str, current_password: str) -> None:
        self._require_current(client, current_password)
        try:
            self.file.unlink()
        except OSError:
            pass
        self._cache = (-1.0, {})
        log.info("Sign-in turned off")

    def sign_out_everywhere(self) -> None:
        d = dict(self._data())
        if d:
            d["nonce"] = secrets.token_hex(8)
            self._write(d)

    # ------------------------------------------------------------------ cookies
    def _sign(self, expires: int) -> str:
        d = self._data()
        msg = f"{expires}|{d.get('username', '')}|{d.get('hash', '')}|{d.get('nonce', '')}".encode()
        return hmac.new(self._key(), msg, hashlib.sha256).hexdigest()

    def token(self, remember: bool) -> tuple[str, int]:
        ttl = REMEMBER_SECONDS if remember else SESSION_SECONDS
        expires = int(time.time()) + ttl
        return f"{expires}.{self._sign(expires)}", ttl

    def authenticated(self, cookie: str | None) -> bool:
        if not cookie or "." not in cookie:
            return False
        exp, _, sig = cookie.partition(".")
        if not exp.isdigit() or int(exp) < time.time():
            return False
        return hmac.compare_digest(sig, self._sign(int(exp)))
