"""Google Sheet reading and *safe* single-cell updates.

Safety rules implemented here (see README_AR.md):

* Columns are located by header text (Column Mapping), never by fixed letters.
* Before any write the sheet is re-read; the row is re-identified by
  company + phone (row number is only a hint) and the owner must still be the
  agent owner, otherwise nothing is written (:class:`OwnerChanged`).
* Only the changed cells are written, via the Values API (no clear, no
  formatting, no full-row replace). Each cell change is backed up in
  ``sync_logs`` and audited in ``audit_logs``.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from app.adapters.google.base import CellUpdate, SheetsClient
from app.config import COLUMN_LABELS_AR, REQUIRED_COLUMNS, AppSettings
from app.db import Database
from app.errors import AgentError, ConfigIncomplete, GoogleNotConnected, OwnerChanged, RowNotFound
from app.repositories.log_repo import LogRepository
from app.services.settings_service import SettingsService
from app.utils.a1 import cell_ref, quote_sheet
from app.utils.phone import extract_phones, phones_match
from app.utils.text import make_fingerprint, normalize_company, normalize_text, same_person

log = logging.getLogger(__name__)


@dataclass
class SheetLead:
    sheet_row: int  # 1-based row number in the sheet (performance hint only)
    company_name: str
    phone_raw: str
    phone_norm: str
    phones: list[str]
    owner: str
    followup_status: str
    source: str
    notes: str
    values: dict[str, str]
    fingerprint: str = ""
    lead_date: str = ""

    def to_dict(self) -> dict:
        return {
            "sheet_row": self.sheet_row, "company_name": self.company_name, "phone": self.phone_raw,
            "phone_norm": self.phone_norm, "owner": self.owner, "followup_status": self.followup_status,
            "source": self.source, "notes": self.notes, "values": self.values, "fingerprint": self.fingerprint,
        }


@dataclass
class SheetSnapshot:
    header: list[str]
    columns: dict[str, int]
    missing: list[str]
    leads: list[SheetLead]
    loaded_at: float = field(default_factory=time.time)


@dataclass
class LeadRef:
    """What we know about the target row before re-reading the sheet."""

    fingerprint: str
    sheet_row: int
    company_name: str
    phone_norm: str


@dataclass
class CellChange:
    key: str
    header: str
    col_index: int
    cell: str
    old: str
    new: str
    user_entered: bool = False

    def to_dict(self) -> dict:
        return {"key": self.key, "column": self.header, "cell": self.cell, "old": self.old, "new": self.new}


@dataclass
class UpdatePlan:
    lead: SheetLead
    changes: list[CellChange]
    warnings: list[str]

    def to_dict(self) -> dict:
        return {"sheet_row": self.lead.sheet_row, "changes": [c.to_dict() for c in self.changes],
                "warnings": self.warnings}


def format_note_entry(note: str, owner: str, when: datetime, stamp_format: str) -> str:
    stamp = stamp_format.format(date=when.strftime("%d/%m/%Y %H:%M"), owner=owner)
    return f"{stamp}\n{note.strip()}"


def merge_notes(old: str, entry: str, append: bool) -> str:
    """Append a note entry without deleting previous text (unless append is disabled)."""
    if not append or not (old or "").strip():
        return entry
    return old.rstrip() + "\n\n" + entry


class SheetService:
    def __init__(
        self,
        db: Database,
        settings: SettingsService,
        client_factory: Callable[[AppSettings], SheetsClient],
    ) -> None:
        self.db = db
        self.settings = settings
        self._client_factory = client_factory
        self._client: SheetsClient | None = None
        self._client_mode: str | None = None
        self._lock = threading.RLock()
        self._options_cache: dict[tuple[str, str, str], tuple[float, list[str]]] = {}
        self.last_snapshot: SheetSnapshot | None = None
        self.last_error: str = ""

    # ------------------------------------------------------------ client
    def client(self) -> SheetsClient:
        s = self.settings.get()
        with self._lock:
            if self._client is None or self._client_mode != s.google_auth_mode:
                self._client = self._client_factory(s)
                self._client_mode = s.google_auth_mode
            return self._client

    def reset_client(self) -> None:
        with self._lock:
            self._client = None
            self._options_cache.clear()

    def _call(self, fn: Callable, *args):
        """Run a Google call and translate errors to clear Arabic messages."""
        try:
            with self._lock:
                result = fn(*args)
            self.last_error = ""
            return result
        except AgentError as exc:
            self.last_error = exc.message_ar
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("Google Sheets call failed")
            status = getattr(getattr(exc, "resp", None), "status", None)
            text = str(exc)
            if status == 403:
                msg = "لا توجد صلاحية على ملف Google Sheet. تأكد من مشاركة الملف مع الحساب المستخدم."
            elif status == 404:
                msg = "لم يتم العثور على ملف Google Sheet. تحقق من Spreadsheet ID."
            elif status == 400 and "exceeds grid limits" in text.lower():
                msg = "تعذر قراءة نطاق الأعمدة المطلوب من Google Sheet."
            elif (status == 400 and "unable to parse range" in text.lower()) or isinstance(exc, KeyError):
                msg = "اسم الـTab غير صحيح أو غير موجود في الملف."
            elif status == 401 or "invalid_grant" in text:
                self.reset_client()
                self.last_error = "انتهت صلاحية ربط Google."
                raise GoogleNotConnected("انتهت صلاحية ربط Google. اضغط Connect Google مرة أخرى.") from exc
            elif status == 429:
                msg = "تم تجاوز حد طلبات Google مؤقتًا. انتظر دقيقة ثم أعد المحاولة."
            else:
                msg = "تعذر الاتصال بـGoogle Sheets. تحقق من الإنترنت ثم أعد المحاولة."
            self.last_error = msg
            raise AgentError("GOOGLE_ERROR", msg, actions=["retry"], status_code=502) from exc

    def _require_basics(self, s: AppSettings) -> None:
        if not s.spreadsheet_id.strip():
            raise ConfigIncomplete("أدخل Spreadsheet ID من الإعدادات.")
        if not s.sheet_name.strip():
            raise ConfigIncomplete("اختر اسم الـTab من الإعدادات.")

    # ------------------------------------------------------------ reading
    def spreadsheet_info(self, spreadsheet_id: str | None = None) -> dict:
        sid = spreadsheet_id or self.settings.get().spreadsheet_id
        if not sid:
            raise ConfigIncomplete("أدخل Spreadsheet ID من الإعدادات.")
        return self._call(self.client().spreadsheet_info, sid)

    def read_rows(self) -> list[list[str]]:
        s = self.settings.get()
        self._require_basics(s)
        # The bare tab name reads the whole used grid; a fixed range like A1:ZZ fails with
        # "exceeds grid limits" on tabs that have fewer columns.
        return self._call(self.client().get_values, s.spreadsheet_id, quote_sheet(s.sheet_name))

    def headers(self) -> list[str]:
        s = self.settings.get()
        rows = self.read_rows()
        idx = s.header_row - 1
        return [h.strip() for h in rows[idx]] if len(rows) > idx else []

    @staticmethod
    def resolve_columns(header: list[str], mapping: dict[str, str]) -> tuple[dict[str, int], list[str]]:
        """Locate mapped columns by header text (exact normalized, then unique 'contains')."""
        norm_header = [normalize_text(h) for h in header]
        columns: dict[str, int] = {}
        missing: list[str] = []
        for key, wanted in mapping.items():
            target = normalize_text(wanted)
            if not target:
                if key in REQUIRED_COLUMNS:
                    missing.append(key)
                continue
            if target in norm_header:
                columns[key] = norm_header.index(target)
                continue
            partial = [i for i, h in enumerate(norm_header) if h and (target in h or h in target)]
            if len(partial) == 1:
                columns[key] = partial[0]
            elif key in REQUIRED_COLUMNS or wanted:
                missing.append(key)
        return columns, missing

    def load(self) -> SheetSnapshot:
        """Read the whole tab and parse every data row (all owners)."""
        s = self.settings.get()
        rows = self.read_rows()
        hidx = s.header_row - 1
        header = [h.strip() for h in rows[hidx]] if len(rows) > hidx else []
        if not header:
            raise AgentError("SHEET_EMPTY", "لم يتم العثور على صف العناوين في الـTab المحدد.", actions=["open_settings"])
        columns, missing = self.resolve_columns(header, s.column_mapping)
        req_missing = [k for k in missing if k in REQUIRED_COLUMNS]
        if req_missing:
            names = "، ".join(COLUMN_LABELS_AR[k] for k in req_missing)
            raise ConfigIncomplete(f"لم يتم العثور على الأعمدة التالية في Google Sheet: {names}. عدّل Column Mapping.")
        leads: list[SheetLead] = []
        seen: dict[str, int] = {}
        for offset, row in enumerate(rows[hidx + 1:]):
            row_number = s.header_row + 1 + offset
            values = {key: (row[i].strip() if i < len(row) else "") for key, i in columns.items()}
            if not any(values.get(k) for k in ("company_name", "phone")):
                continue
            phones = extract_phones(values.get("phone", ""))
            lead = SheetLead(
                sheet_row=row_number,
                company_name=values.get("company_name", ""),
                phone_raw=values.get("phone", ""),
                phone_norm=phones[0] if phones else "",
                phones=phones,
                owner=values.get("owner", ""),
                followup_status=values.get("followup_status", ""),
                source=values.get("source", ""),
                notes=values.get("notes", ""),
                values=values,
                lead_date=values.get("lead_date", ""),
            )
            fp = make_fingerprint(lead.company_name, lead.phone_norm, lead.owner)
            seen[fp] = seen.get(fp, 0) + 1
            lead.fingerprint = fp if seen[fp] == 1 else f"{fp[:16]}-{seen[fp]}"
            leads.append(lead)
        snap = SheetSnapshot(header=header, columns=columns, missing=missing, leads=leads)
        self.last_snapshot = snap
        return snap

    def owner_leads(self, snap: SheetSnapshot) -> list[SheetLead]:
        owner = self.settings.get().agent_owner
        return [lead for lead in snap.leads if same_person(lead.owner, owner)]

    def dropdown_options(self, key: str) -> list[str]:
        """Allowed values for a mapped column: Data Validation first, else existing distinct values."""
        s = self.settings.get()
        cache_key = (s.spreadsheet_id, s.sheet_name, key)
        cached = self._options_cache.get(cache_key)
        if cached and time.time() - cached[0] < 300:
            return cached[1]
        snap = self.last_snapshot or self.load()
        col = snap.columns.get(key)
        if col is None:
            return []
        options: list[str] = []
        try:
            options = self._call(self.client().dropdown_options, s.spreadsheet_id, s.sheet_name, col, s.header_row)
        except AgentError:
            log.warning("Could not read data validation for %s", key)
        if not options:
            for lead in snap.leads:
                v = lead.values.get(key, "").strip()
                if v and v not in options:
                    options.append(v)
            options.sort()
        self._options_cache[cache_key] = (time.time(), options)
        return options

    def test_connection(self) -> dict:
        s = self.settings.get()
        info = self.spreadsheet_info()
        result: dict = {"ok": True, "title": info["title"], "tabs": info["sheets"], "header": [], "columns": {},
                        "missing": [], "owner_rows": 0, "total_rows": 0}
        if s.sheet_name and s.sheet_name in info["sheets"]:
            header = self.headers()
            columns, missing = self.resolve_columns(header, s.column_mapping)
            result.update({"header": header, "columns": {k: header[i] for k, i in columns.items()}, "missing": missing})
            if not [k for k in missing if k in REQUIRED_COLUMNS]:
                snap = self.load()
                result["total_rows"] = len(snap.leads)
                result["owner_rows"] = len(self.owner_leads(snap))
        elif s.sheet_name:
            result["ok"] = False
            result["message"] = "اسم الـTab غير موجود في الملف."
        return result

    # ------------------------------------------------------------ safe update
    def locate(self, snap: SheetSnapshot, ref: LeadRef) -> SheetLead:
        """Re-identify the lead row in a *fresh* snapshot and enforce the owner rule."""
        owner = self.settings.get().agent_owner
        company = normalize_company(ref.company_name)

        def same_record(lead: SheetLead) -> bool:
            company_ok = normalize_company(lead.company_name) == company
            phone_ok = (not ref.phone_norm and not lead.phone_norm) or any(
                phones_match(p, ref.phone_norm) for p in lead.phones
            )
            return company_ok and phone_ok

        hinted = next((lead for lead in snap.leads if lead.sheet_row == ref.sheet_row), None)
        if hinted is not None and same_record(hinted):
            if not same_person(hinted.owner, owner):
                raise OwnerChanged()
            return hinted
        matches = [lead for lead in snap.leads if same_record(lead)]
        if not matches:
            raise RowNotFound()
        mine = [lead for lead in matches if same_person(lead.owner, owner)]
        if not mine:
            raise OwnerChanged()
        if len(mine) > 1:
            raise RowNotFound("يوجد أكثر من صف مطابق لنفس العميل في Google Sheet؛ لن يتم التحديث تلقائيًا.")
        return mine[0]

    def plan_update(self, ref: LeadRef, changes: dict[str, str], note_entry: str = "",
                    user_entered_keys: tuple[str, ...] = ("subscription_expiry",)) -> UpdatePlan:
        """Fresh read → locate row → compute only the cells that really change."""
        s = self.settings.get()
        snap = self.load()
        lead = self.locate(snap, ref)
        plan = UpdatePlan(lead=lead, changes=[], warnings=[])
        wanted = dict(changes)
        if note_entry:
            old_notes = lead.values.get("notes", "")
            if note_entry.strip() and note_entry.strip() in old_notes:
                pass  # already written (retry after partial failure)
            else:
                wanted["notes"] = merge_notes(old_notes, note_entry, s.append_notes)
        for key, new in wanted.items():
            if new is None:
                continue
            col = snap.columns.get(key)
            if col is None:
                plan.warnings.append(f"عمود «{COLUMN_LABELS_AR.get(key, key)}» غير موجود في Sheet؛ لم يتم تحديثه.")
                continue
            old = lead.values.get(key, "")
            if old == new:
                continue
            if s.validate_dropdown_values and key in ("followup_status", "source") and new:
                options = self.dropdown_options(key)
                if options and new not in options:
                    raise AgentError(
                        "VALUE_NOT_IN_DROPDOWN",
                        f"القيمة «{new}» غير موجودة في قائمة «{COLUMN_LABELS_AR.get(key, key)}» في Google Sheet. "
                        "عدّل الربط من الإعدادات.",
                        actions=["open_settings"],
                    )
            plan.changes.append(CellChange(
                key=key, header=snap.header[col], col_index=col, cell=cell_ref(s.sheet_name, lead.sheet_row, col),
                old=old, new=new, user_entered=key in user_entered_keys,
            ))
        return plan

    def apply(self, plan: UpdatePlan, *, dry_run: bool, action_id: str | None = None) -> str:
        """Write the plan (or only log it in dry run). Returns 'success' | 'dry_run' | 'nochange'."""
        s = self.settings.get()
        action_id = action_id or uuid.uuid4().hex
        lead = plan.lead
        if not plan.changes:
            return "nochange"
        status = "dry_run" if dry_run else "success"
        error = ""
        if not dry_run:
            try:
                self._call(self.client().update_cells, s.spreadsheet_id,
                           [CellUpdate(c.cell, c.new, c.user_entered) for c in plan.changes])
            except AgentError as exc:
                status, error = "failed", exc.message_ar
        with self.db.session() as db:
            logs = LogRepository(db)
            for c in plan.changes:
                logs.add_sync(action_id=action_id, sheet_row=lead.sheet_row, company_name=lead.company_name,
                              phone=lead.phone_raw, column=c.header, cell=c.cell, old_value=c.old,
                              new_value=c.new, status=status)
            logs.add_audit(
                action_id=action_id, system="GOOGLE_SHEETS", action="update_cells",
                record=f"row {lead.sheet_row} | {lead.company_name} | {lead.phone_raw}",
                before={c.header: c.old for c in plan.changes}, after={c.header: c.new for c in plan.changes},
                success=status != "failed", dry_run=dry_run, error=error,
            )
        if status == "failed":
            raise AgentError("SHEET_UPDATE_FAILED", f"تعذر تحديث Google Sheet: {error}", actions=["retry"], status_code=502)
        return status
