"""Google credentials: OAuth Desktop App (default) or Service Account.

Files live in ``data/credentials`` (git-ignored):

* ``client_secret.json`` – OAuth Desktop client downloaded from Google Cloud Console
* ``token.json``          – OAuth token saved after the consent screen
* ``service_account.json`` – optional service account key
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from app.errors import AgentError, GoogleNotConnected

log = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class GoogleAuthService:
    def __init__(self, credentials_dir: Path) -> None:
        self.dir = credentials_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self._flow_thread: threading.Thread | None = None
        self.flow_state: dict = {"running": False, "error": "", "done": False}

    @property
    def client_secret_path(self) -> Path:
        return self.dir / "client_secret.json"

    @property
    def token_path(self) -> Path:
        return self.dir / "token.json"

    @property
    def service_account_path(self) -> Path:
        return self.dir / "service_account.json"

    # ------------------------------------------------------------------ files
    def save_credentials_file(self, kind: str, content: bytes) -> str:
        """Validate and store an uploaded JSON credentials file. Returns a short description."""
        try:
            data = json.loads(content.decode("utf-8-sig"))
        except Exception as exc:  # noqa: BLE001
            raise AgentError("BAD_CREDENTIALS_FILE", "الملف ليس JSON صالحًا.") from exc
        if kind == "oauth":
            if "installed" not in data:
                raise AgentError(
                    "BAD_CREDENTIALS_FILE",
                    "هذا ليس ملف OAuth من نوع Desktop App. أنشئ OAuth Client ID من نوع Desktop app وحمّل ملف JSON.",
                )
            self.client_secret_path.write_text(json.dumps(data), encoding="utf-8")
            return data["installed"].get("client_id", "")
        if kind == "service_account":
            if data.get("type") != "service_account":
                raise AgentError("BAD_CREDENTIALS_FILE", "هذا ليس ملف Service Account صالحًا.")
            self.service_account_path.write_text(json.dumps(data), encoding="utf-8")
            return data.get("client_email", "")
        raise AgentError("BAD_CREDENTIALS_KIND", "نوع ملف غير معروف.")

    def service_account_email(self) -> str:
        try:
            return json.loads(self.service_account_path.read_text(encoding="utf-8")).get("client_email", "")
        except Exception:  # noqa: BLE001
            return ""

    # ------------------------------------------------------------ credentials
    def status(self, mode: str) -> dict:
        """Connection status without network calls."""
        if mode == "service_account":
            ok = self.service_account_path.exists()
            return {"mode": mode, "configured": ok, "has_client_secret": False, "has_token": False,
                    "service_account_email": self.service_account_email() if ok else ""}
        has_token = self.token_path.exists()
        return {"mode": mode, "configured": has_token, "has_client_secret": self.client_secret_path.exists(),
                "has_token": has_token, "service_account_email": "", "flow": dict(self.flow_state)}

    def get_credentials(self, mode: str):
        """Return valid google-auth credentials or raise :class:`GoogleNotConnected`."""
        if mode == "service_account":
            if not self.service_account_path.exists():
                raise GoogleNotConnected("لم يتم رفع ملف Service Account بعد.")
            from google.oauth2 import service_account

            return service_account.Credentials.from_service_account_file(str(self.service_account_path), scopes=SCOPES)
        if not self.token_path.exists():
            raise GoogleNotConnected()
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
        if creds.valid:
            return creds
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as exc:  # noqa: BLE001
                log.warning("Google token refresh failed", exc_info=True)
                raise GoogleNotConnected("انتهت صلاحية ربط Google. اضغط Connect Google مرة أخرى.") from exc
            self.token_path.write_text(creds.to_json(), encoding="utf-8")
            return creds
        raise GoogleNotConnected()

    def start_oauth_flow(self) -> None:
        """Run the Desktop OAuth consent in a background thread (opens the system browser)."""
        if not self.client_secret_path.exists():
            raise AgentError(
                "NO_CLIENT_SECRET",
                "ارفع ملف OAuth client (Desktop app) أولًا من صفحة الإعدادات.",
                actions=["open_settings"],
            )
        if self._flow_thread and self._flow_thread.is_alive():
            return
        self.flow_state = {"running": True, "error": "", "done": False}

        def _run() -> None:
            try:
                from google_auth_oauthlib.flow import InstalledAppFlow

                flow = InstalledAppFlow.from_client_secrets_file(str(self.client_secret_path), SCOPES)
                creds = flow.run_local_server(
                    host="localhost", port=0, open_browser=True, timeout_seconds=300,
                    success_message="تم ربط Google بنجاح. يمكنك إغلاق هذه الصفحة والعودة إلى Khalid Leads Agent.",
                )
                self.token_path.write_text(creds.to_json(), encoding="utf-8")
                self.flow_state = {"running": False, "error": "", "done": True}
            except Exception as exc:  # noqa: BLE001
                log.exception("Google OAuth flow failed")
                self.flow_state = {"running": False, "error": f"فشل ربط Google: {exc}", "done": False}

        self._flow_thread = threading.Thread(target=_run, name="google-oauth", daemon=True)
        self._flow_thread.start()

    def disconnect(self) -> None:
        if self.token_path.exists():
            self.token_path.unlink()
