"""Access from the user's phone over Tailscale: PC unchanged, Tailscale + PIN only, nobody else."""
import pytest
from fastapi.testclient import TestClient

from app.config import EnvSettings
from app.main import create_app
from app.remote_access import is_tailscale, valid_pin
from tests.conftest import make_container

H = {"X-KLA": "1"}
PC = ("127.0.0.1", 50000)
PHONE = ("100.101.102.103", 50001)  # a Tailscale address
LAN = ("192.168.1.20", 50002)  # same Wi-Fi, not Tailscale
PIN = "482913"


@pytest.fixture
def remote_env(tmp_path):
    return EnvSettings(_env_file=None, data_dir=str(tmp_path / "data"), logs_dir=str(tmp_path / "logs"),
                       use_mocks=False, open_browser_on_start=False, remote_access=True, access_pin=PIN)


def _client(env, sheet, odoo, who):
    c = make_container(env, sheet, odoo)
    return TestClient(create_app(c), client=who, base_url="http://100.101.102.200:8765")


def test_helpers():
    assert valid_pin("123456") and not valid_pin("12345") and not valid_pin("12ab56") and not valid_pin("")
    assert is_tailscale("100.64.0.1") and is_tailscale("100.127.255.254") and is_tailscale("fd7a:115c:a1e0::1")
    assert not is_tailscale("100.128.0.1") and not is_tailscale("192.168.1.2") and not is_tailscale("8.8.8.8")


def test_pc_works_without_pin(remote_env, sheet, odoo):
    c = make_container(remote_env, sheet, odoo)
    with TestClient(create_app(c), client=PC, base_url="http://evil.example:8765") as tc:  # DNS rebinding
        assert tc.get("/api/status").status_code == 403
    with TestClient(create_app(c), client=PC, base_url="http://127.0.0.1:8765") as tc:
        st = tc.get("/api/status").json()
        assert st["remote"] is False
        assert tc.get("/").status_code == 200


def test_other_networks_are_refused(remote_env, sheet, odoo):
    with _client(remote_env, sheet, odoo, LAN) as tc:
        assert tc.get("/").status_code == 403
        assert tc.get("/login").status_code == 403
        assert tc.post("/login", data={"pin": PIN}).status_code == 403


def test_phone_needs_pin_then_works(remote_env, sheet, odoo):
    with _client(remote_env, sheet, odoo, PHONE) as tc:
        r = tc.get("/", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"
        assert tc.get("/api/status").status_code == 401
        assert tc.get("/static/css/app.css").status_code == 200
        wrong = tc.post("/login", data={"pin": "000000"}, follow_redirects=False)
        assert wrong.headers["location"] == "/login?error=wrong" and "kla_auth" not in tc.cookies
        ok = tc.post("/login", data={"pin": PIN}, follow_redirects=False)
        assert ok.status_code == 303 and "kla_auth" in tc.cookies
        st = tc.get("/api/status").json()
        assert st["remote"] is True
        assert tc.get("/").status_code == 200
        # Shutdown stays PC-only even when signed in.
        assert tc.post("/api/admin/shutdown", headers=H).status_code == 403


def test_wrong_pins_lock_the_device(remote_env, sheet, odoo):
    with _client(remote_env, sheet, odoo, PHONE) as tc:
        for _ in range(5):
            tc.post("/login", data={"pin": "111111"}, follow_redirects=False)
        r = tc.post("/login", data={"pin": PIN}, follow_redirects=False)
        assert r.headers["location"].startswith("/login?error=locked") and "kla_auth" not in tc.cookies


def test_forged_cookie_rejected(remote_env, sheet, odoo):
    with _client(remote_env, sheet, odoo, PHONE) as tc:
        tc.cookies.set("kla_auth", "0" * 64)
        assert tc.get("/api/status").status_code == 401


def test_short_pin_keeps_agent_local(tmp_path, sheet, odoo):
    env = EnvSettings(_env_file=None, data_dir=str(tmp_path / "data"), logs_dir=str(tmp_path / "logs"),
                      use_mocks=False, open_browser_on_start=False, remote_access=True, access_pin="123")
    c = make_container(env, sheet, odoo)
    with TestClient(create_app(c), client=PHONE, base_url="http://100.101.102.200:8765") as tc:
        assert tc.get("/api/status").status_code == 400  # host not allowed: remote mode is off


def test_phone_call_dials_on_the_phone(remote_env, sheet, odoo):
    with _client(remote_env, sheet, odoo, PHONE) as tc:
        tc.post("/login", data={"pin": PIN})
        tc.post("/api/session/start", json={"resume": True}, headers=H)
        fp = tc.get("/api/lead/current").json()["lead"]["fingerprint"]
        tc.post(f"/api/lead/{fp}/search", json={"query": ""}, headers=H)
        r = tc.post(f"/api/lead/{fp}/call", json={"client_dial": True}, headers=H).json()
        assert r["method"] == "client_tel" and r["tel"] == "+966561234567"
        assert odoo.calls == []  # nothing launched on the PC
