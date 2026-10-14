"""Optional sign-in (username + password) on the PC and from the phone."""
import json

import pytest
from fastapi.testclient import TestClient

from app.config import EnvSettings
from app.login_service import COOKIE, LoginService, login_configured
from app.main import create_app
from tests.conftest import make_container

H = {"X-KLA": "1"}
PC = ("127.0.0.1", 50000)
PHONE = ("100.101.102.103", 50001)
PASSWORD = "Strong-Pass-2026"


def _pc(env, sheet, odoo):
    c = make_container(env, sheet, odoo)
    return TestClient(create_app(c, allowed_hosts=["127.0.0.1"]), client=PC, base_url="http://127.0.0.1:8765")


def _enable(tc, username="khalid", password=PASSWORD):
    r = tc.post("/api/auth/password", json={"username": username, "password": password}, headers=H)
    assert r.status_code == 200, r.text
    return r


def _login(tc, username="khalid", password=PASSWORD, remember=False):
    data = {"username": username, "password": password, "next": "/settings"}
    if remember:
        data["remember"] = "1"
    return tc.post("/login", data=data, follow_redirects=False)


def test_off_by_default_pc_is_open(env, sheet, odoo):
    with _pc(env, sheet, odoo) as tc:
        assert tc.get("/api/status").status_code == 200
        assert tc.get("/api/auth/status").json()["enabled"] is False
        assert tc.get("/login", follow_redirects=False).status_code == 303  # nothing to sign in to


def test_enable_then_everything_needs_sign_in(env, sheet, odoo):
    with _pc(env, sheet, odoo) as tc:
        _enable(tc)
        assert tc.get("/api/status").status_code == 200  # this browser stays signed in
        stored = json.loads((env.data_path / "login.json").read_text(encoding="utf-8"))
        assert PASSWORD not in json.dumps(stored) and stored["username"] == "khalid" and len(stored["hash"]) == 64
        assert login_configured(env.data_path)
    with _pc(env, sheet, odoo) as other:  # another browser on the PC: no cookie
        r = other.get("/api/status")
        assert r.status_code == 401 and r.json()["error"]["code"] == "LOGIN_REQUIRED"
        page = other.get("/settings", follow_redirects=False)
        assert page.status_code == 303 and page.headers["location"] == "/login?next=/settings"
        assert other.get("/api/version").json()["version"]  # run.py / .bat helpers stay open on the PC
        assert other.get("/static/css/app.css").status_code == 200
        assert "اسم المستخدم" in other.get("/login").text
        bad = _login(other, password="wrong-password")
        assert bad.headers["location"].startswith("/login?error=wrong") and COOKIE not in bad.cookies
        ok = _login(other, username="KHALID")  # the username is not case-sensitive
        assert ok.status_code == 303 and ok.headers["location"] == "/settings"
        assert "max-age" not in ok.headers["set-cookie"].lower()  # session cookie unless «تذكرني»
        assert other.get("/api/status").status_code == 200
        other.post("/logout", follow_redirects=False)
        assert other.get("/api/status").status_code == 401


def test_remember_me_and_open_redirect_guard(env, sheet, odoo):
    with _pc(env, sheet, odoo) as tc:
        _enable(tc)
    with _pc(env, sheet, odoo) as tc:
        r = tc.post("/login", data={"username": "khalid", "password": PASSWORD, "remember": "1",
                                    "next": "//evil.example/x"}, follow_redirects=False)
        assert r.headers["location"] == "/" and "max-age=2592000" in r.headers["set-cookie"].lower()


def test_wrong_passwords_are_rate_limited(env, sheet, odoo):
    with _pc(env, sheet, odoo) as tc:
        _enable(tc)
    with _pc(env, sheet, odoo) as tc:
        for _ in range(5):
            _login(tc, password="nope-nope")
        r = _login(tc)  # even the right password waits now
        assert r.headers["location"].startswith("/login?error=locked")


def test_change_and_disable_need_the_current_password(env, sheet, odoo):
    with _pc(env, sheet, odoo) as tc:
        _enable(tc)
        r = tc.post("/api/auth/password", json={"username": "khalid", "password": "Another-Pass-1"}, headers=H)
        assert r.json()["error"]["code"] == "WRONG_PASSWORD"
        r = tc.post("/api/auth/password", json={"username": "khalid", "password": "Another-Pass-1",
                                                "current_password": PASSWORD}, headers=H)
        assert r.status_code == 200 and tc.get("/api/status").status_code == 200
        assert tc.post("/api/auth/disable", json={"current_password": PASSWORD}, headers=H).json()["error"]["code"] == "WRONG_PASSWORD"
        assert tc.post("/api/auth/disable", json={"current_password": "Another-Pass-1"}, headers=H).json()["enabled"] is False
    with _pc(env, sheet, odoo) as other:
        assert other.get("/api/status").status_code == 200  # open again


def test_password_change_and_sign_out_all_invalidate_other_cookies(env, sheet, odoo):
    with _pc(env, sheet, odoo) as a:
        _enable(a)
        with _pc(env, sheet, odoo) as b:
            _login(b)
            assert b.get("/api/status").status_code == 200
            a.post("/api/auth/sign-out-all", headers=H)
            assert a.get("/api/status").status_code == 200  # the browser that asked stays in
            assert b.get("/api/status").status_code == 401


def test_weak_passwords_are_refused(env, sheet, odoo):
    with _pc(env, sheet, odoo) as tc:
        for pw, code in (("short", "PASSWORD_WEAK"), ("11111111", "PASSWORD_WEAK")):
            r = tc.post("/api/auth/password", json={"username": "khalid", "password": pw}, headers=H)
            assert r.json()["error"]["code"] == code
        assert tc.post("/api/auth/password", json={"username": "k", "password": PASSWORD}, headers=H).json()["error"]["code"] == "USERNAME_INVALID"


def test_reset_file_turns_sign_in_off(env, sheet, odoo):
    with _pc(env, sheet, odoo) as tc:
        _enable(tc)
        (env.data_path / "login.json").unlink()  # what 06_reset_login.bat does
        with _pc(env, sheet, odoo) as other:
            assert other.get("/api/status").status_code == 200


@pytest.fixture
def remote_env(tmp_path):
    return EnvSettings(_env_file=None, data_dir=str(tmp_path / "data"), logs_dir=str(tmp_path / "logs"),
                       use_mocks=False, open_browser_on_start=False, remote_access=True, access_pin="")


def test_phone_uses_the_password_and_works_without_a_pin(remote_env, sheet, odoo):
    LoginService(remote_env.data_path).set_password("pc", "khalid", PASSWORD)
    c = make_container(remote_env, sheet, odoo)
    app = create_app(c)
    assert app.state.remote is not None  # remote access on: a password is enough, no PIN needed
    with TestClient(app, client=PHONE, base_url="http://100.101.102.200:8765") as tc:
        assert tc.get("/api/status").status_code == 401
        assert tc.get("/api/version").status_code == 401  # PC-only helper
        assert tc.post("/login", data={"pin": ""}, follow_redirects=False).headers["location"].startswith("/login?error=wrong")
        assert _login(tc).status_code == 303
        assert tc.get("/api/status").status_code == 200
        assert tc.post("/api/admin/shutdown", headers=H).status_code == 403  # still PC-only


def test_empty_pin_never_signs_in(remote_env, sheet, odoo):
    LoginService(remote_env.data_path).set_password("pc", "khalid", PASSWORD)
    c = make_container(remote_env, sheet, odoo)
    app = create_app(c)
    app.state.login.disable("pc", PASSWORD)  # turned off while running: the phone must not fall open
    with TestClient(app, client=PHONE, base_url="http://100.101.102.200:8765") as tc:
        tc.post("/login", data={"pin": ""}, follow_redirects=False)
        assert tc.get("/api/status").status_code == 401


# ------------------------------------------------------------------ idle sign-out
def _age_session(app, seconds):
    login = app.state.login
    for k in list(login._seen):
        login._seen[k] -= seconds


def test_idle_sign_out_after_10_minutes(env, sheet, odoo):
    c = make_container(env, sheet, odoo)
    app = create_app(c, allowed_hosts=["127.0.0.1"])
    with TestClient(app, client=PC, base_url="http://127.0.0.1:8765") as tc:
        _enable(tc)
        assert tc.get("/api/auth/status").json()["idle_minutes"] == 10  # the default
        assert 'data-idle="10"' in tc.get("/settings").text
        _age_session(app, 9 * 60)
        assert tc.get("/api/status").status_code == 200  # background checks still work...
        _age_session(app, 3 * 60)  # ...but do not count: 12 minutes idle now (10 + about a minute of grace)
        r = tc.get("/api/status")
        assert r.status_code == 401 and r.json()["error"]["details"]["reason"] == "idle"
        page = tc.get("/", follow_redirects=False)
        assert page.headers["location"].startswith("/login?error=idle")
        assert "بدون نشاط" in tc.get("/login?error=idle").text
        assert "تذكرني" not in tc.get("/login").text  # «remember me» makes no sense with idle sign-out
        assert _login(tc).status_code == 303 and tc.get("/api/status").status_code == 200  # sign in again


def test_real_activity_keeps_the_session(env, sheet, odoo):
    c = make_container(env, sheet, odoo)
    app = create_app(c, allowed_hosts=["127.0.0.1"])
    with TestClient(app, client=PC, base_url="http://127.0.0.1:8765") as tc:
        _enable(tc)
        for _ in range(3):  # 3 × 8 minutes, each time with a click in between
            _age_session(app, 8 * 60)
            assert tc.post("/api/auth/activity", headers=H).status_code == 200
        assert tc.get("/api/status").status_code == 200
        _age_session(app, 8 * 60)
        tc.get("/history")  # opening a page counts too
        _age_session(app, 8 * 60)
        assert tc.get("/api/status").status_code == 200


def test_idle_limit_can_be_changed_or_turned_off(env, sheet, odoo):
    c = make_container(env, sheet, odoo)
    app = create_app(c, allowed_hosts=["127.0.0.1"])
    with TestClient(app, client=PC, base_url="http://127.0.0.1:8765") as tc:
        _enable(tc)
        assert tc.post("/api/auth/idle", json={"minutes": 0}, headers=H).json()["idle_minutes"] == 0
        _age_session(app, 5 * 3600)
        assert tc.get("/api/status").status_code == 200
        assert tc.post("/api/auth/idle", json={"minutes": 999}, headers=H).status_code == 422
        tc.post("/api/auth/idle", json={"minutes": 30}, headers=H)
        # Changing the password keeps the chosen limit.
        tc.post("/api/auth/password", json={"username": "khalid", "password": "Another-Pass-1",
                                            "current_password": PASSWORD}, headers=H)
        assert tc.get("/api/auth/status").json()["idle_minutes"] == 30


def test_restart_signs_everyone_out_while_idle_is_on(env, sheet, odoo):
    with _pc(env, sheet, odoo) as tc:
        _enable(tc)
        cookie = tc.cookies.get(COOKIE)
    with _pc(env, sheet, odoo) as fresh:  # a new agent process: no activity record for that cookie
        fresh.cookies.set(COOKIE, cookie)
        assert fresh.get("/api/status").status_code == 401
