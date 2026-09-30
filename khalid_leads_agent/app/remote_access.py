"""Optional access from the user's other devices (phone, laptop) over Tailscale, protected by a PIN.

Off by default. With ``REMOTE_ACCESS=true`` and an ``ACCESS_PIN`` (6+ digits) in ``.env``:

* the PC itself (127.0.0.1) works exactly as before, without a PIN;
* only Tailscale addresses (100.64.0.0/10, fd7a:115c:a1e0::/48) may connect, everything else
  (other Wi-Fi devices, the internet) is refused;
* a Tailscale device must enter the PIN once; it then gets a signed cookie (30 days);
* wrong PINs are rate-limited per device; shutdown stays PC-only.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import secrets
import time
from pathlib import Path

log = logging.getLogger(__name__)

COOKIE = "kla_auth"
COOKIE_MAX_AGE = 30 * 24 * 3600
MAX_FAILURES = 5
LOCK_SECONDS = 600
TAILSCALE_NETS = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48"))
PUBLIC_PATHS = ("/login", "/static/", "/favicon.ico")
LOCAL_ONLY_PATHS = ("/api/admin/shutdown",)


def tailscale_ips() -> list[str]:
    """This PC's Tailscale IPv4 addresses (what to open on the phone)."""
    import socket

    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    return sorted({i[4][0] for i in infos if is_tailscale(i[4][0])})


def valid_pin(pin: str) -> bool:
    return pin.isdigit() and len(pin) >= 6


def is_loopback(host: str | None) -> bool:
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


def is_tailscale(host: str | None) -> bool:
    try:
        ip = ipaddress.ip_address(host or "")
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return any(ip in net for net in TAILSCALE_NETS)


class RemoteAccess:
    def __init__(self, pin: str, secret_file: Path) -> None:
        self.pin = pin
        self._secret = self._load_secret(secret_file)
        self._failures: dict[str, list[float]] = {}

    @staticmethod
    def _load_secret(path: Path) -> bytes:
        try:
            data = path.read_bytes()
            if len(data) >= 32:
                return data
        except OSError:
            pass
        path.parent.mkdir(parents=True, exist_ok=True)
        data = secrets.token_bytes(32)
        path.write_bytes(data)
        return data

    def token(self) -> str:
        """Cookie value; changing the PIN signs everyone out."""
        return hmac.new(self._secret, b"kla-remote|" + self.pin.encode(), hashlib.sha256).hexdigest()

    def authenticated(self, cookie: str | None) -> bool:
        return bool(cookie) and hmac.compare_digest(cookie, self.token())

    def locked_for(self, client: str) -> int:
        """Seconds this device must wait before trying again (0 = may try)."""
        now = time.time()
        recent = [t for t in self._failures.get(client, []) if now - t < LOCK_SECONDS]
        self._failures[client] = recent
        if len(recent) >= MAX_FAILURES:
            return int(LOCK_SECONDS - (now - recent[0])) + 1
        return 0

    def check_pin(self, client: str, pin: str) -> bool:
        if hmac.compare_digest(pin.strip().encode(), self.pin.encode()):
            self._failures.pop(client, None)
            return True
        self._failures.setdefault(client, []).append(time.time())
        log.warning("Wrong access PIN from %s", client)
        return False
