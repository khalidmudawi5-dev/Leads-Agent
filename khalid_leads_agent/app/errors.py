"""User-facing errors: Arabic message + suggested actions. Stack traces stay in logs."""
from __future__ import annotations

from typing import Any

# Action identifiers understood by the frontend.
RETRY = "retry"
OPEN_ODOO = "open_odoo"
SKIP = "skip"
OPEN_LOGIN = "open_login"
OPEN_SETTINGS = "open_settings"
OPEN_CRM = "open_crm"


class AgentError(Exception):
    """Base error with a clear Arabic message for the end user."""

    status_code = 400

    def __init__(
        self,
        code: str,
        message_ar: str,
        *,
        actions: list[str] | None = None,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(f"{code}: {message_ar}")
        self.code = code
        self.message_ar = message_ar
        self.actions = actions or []
        self.details = details or {}
        if status_code is not None:
            self.status_code = status_code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message_ar, "actions": self.actions, "details": self.details}


class GoogleNotConnected(AgentError):
    def __init__(self, message_ar: str = "Google غير متصل. افتح الإعدادات واضغط Connect Google.") -> None:
        super().__init__("GOOGLE_NOT_CONNECTED", message_ar, actions=[OPEN_SETTINGS], status_code=409)


class ConfigIncomplete(AgentError):
    def __init__(self, message_ar: str) -> None:
        super().__init__("CONFIG_INCOMPLETE", message_ar, actions=[OPEN_SETTINGS], status_code=409)


class OdooLoginRequired(AgentError):
    def __init__(self) -> None:
        super().__init__(
            "ODOO_LOGIN_REQUIRED", "تسجيل الدخول إلى Odoo مطلوب", actions=[OPEN_LOGIN], status_code=401
        )


class OwnerChanged(AgentError):
    def __init__(self) -> None:
        super().__init__(
            "OWNER_CHANGED", "تم تحويل العميل إلى موظف آخر؛ لن يتم تحديث الصف.", actions=[SKIP], status_code=409
        )


class RowNotFound(AgentError):
    def __init__(self, message_ar: str = "لم يعد صف العميل موجودًا في Google Sheet بنفس البيانات؛ لن يتم التحديث.") -> None:
        super().__init__("ROW_NOT_FOUND", message_ar, actions=[RETRY, SKIP], status_code=409)


class AutomationError(AgentError):
    """Browser automation failure (selector not found, timeout...)."""

    def __init__(self, code: str, message_ar: str, screenshot: str | None = None) -> None:
        super().__init__(
            code, message_ar, actions=[RETRY, OPEN_ODOO, SKIP], details={"screenshot": screenshot} if screenshot else {}
        )
