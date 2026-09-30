"""External writes (Google Sheets / Odoo) with audit logging and dry-run support."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.db import Database
from app.errors import AgentError, OdooLoginRequired, OwnerChanged, RowNotFound
from app.repositories.log_repo import LogRepository
from app.services.google_sheets_service import LeadRef, SheetService, UpdatePlan
from app.services.odoo_service import OdooService

log = logging.getLogger(__name__)


@dataclass
class StepResult:
    status: str  # success | failed | blocked | dry_run | skipped | nochange
    message: str = ""
    plan: UpdatePlan | None = None
    warnings: list[str] = field(default_factory=list)


class SyncService:
    def __init__(self, db: Database, sheets: SheetService, odoo: OdooService) -> None:
        self.db = db
        self.sheets = sheets
        self.odoo = odoo

    def audit(self, **fields) -> None:
        with self.db.session() as s:
            LogRepository(s).add_audit(**fields)

    # ------------------------------------------------------------- sheet
    def plan_sheet(self, ref: LeadRef, changes: dict[str, str], note_entry: str) -> StepResult:
        try:
            plan = self.sheets.plan_update(ref, changes, note_entry)
            return StepResult("planned", plan=plan, warnings=list(plan.warnings))
        except (OwnerChanged, RowNotFound) as exc:
            return StepResult("blocked", exc.message_ar)
        except AgentError as exc:
            return StepResult("failed", exc.message_ar)

    def update_sheet(self, ref: LeadRef, changes: dict[str, str], note_entry: str, *, dry_run: bool,
                     action_id: str) -> StepResult:
        step = self.plan_sheet(ref, changes, note_entry)
        if step.status == "blocked":
            self.audit(action_id=action_id, system="GOOGLE_SHEETS", action="update_blocked",
                       record=f"row {ref.sheet_row} | {ref.company_name} | {ref.phone_norm}",
                       before=None, after=changes, success=False, dry_run=dry_run, error=step.message)
            return step
        if step.status == "failed" or step.plan is None:
            return step
        try:
            step.status = self.sheets.apply(step.plan, dry_run=dry_run, action_id=action_id)
        except AgentError as exc:
            step.status, step.message = "failed", exc.message_ar
        return step

    # -------------------------------------------------------------- odoo
    async def odoo_note(self, lead_id: int, body: str, ref: str, *, dry_run: bool, action_id: str) -> StepResult:
        record = f"crm.lead {lead_id}"
        if dry_run:
            self.audit(action_id=action_id, system="ODOO", action="log_note", record=record, before=None,
                       after={"body": body}, success=True, dry_run=True)
            return StepResult("dry_run")
        try:
            outcome = await self.odoo.adapter.post_log_note(lead_id, body, ref)
        except OdooLoginRequired as exc:
            self.odoo.mark_logged_out()
            outcome_msg = exc.message_ar
            self.audit(action_id=action_id, system="ODOO", action="log_note", record=record, before=None,
                       after={"body": body}, success=False, error=outcome_msg)
            return StepResult("failed", outcome_msg)
        except AgentError as exc:
            self.audit(action_id=action_id, system="ODOO", action="log_note", record=record, before=None,
                       after={"body": body}, success=False, error=exc.message_ar)
            return StepResult("failed", exc.message_ar)
        self.audit(action_id=action_id, system="ODOO", action="log_note", record=record, before=None,
                   after={"body": body, "method": outcome.method, "already_done": outcome.already_done},
                   success=outcome.success, error="" if outcome.success else outcome.message)
        if outcome.success:
            return StepResult("success")
        return StepResult("failed", "تعذر إضافة Log Note في Odoo.")

    async def odoo_activity(self, lead_id: int, date_deadline: str, summary: str, note: str, *, dry_run: bool,
                            action_id: str) -> StepResult:
        record = f"crm.lead {lead_id}"
        after = {"date_deadline": date_deadline, "summary": summary, "note": note}
        if dry_run:
            self.audit(action_id=action_id, system="ODOO", action="schedule_activity", record=record, before=None,
                       after=after, success=True, dry_run=True)
            return StepResult("dry_run")
        try:
            outcome = await self.odoo.adapter.schedule_activity(lead_id, date_deadline, summary, note)
        except AgentError as exc:
            outcome_msg = exc.message_ar
            self.audit(action_id=action_id, system="ODOO", action="schedule_activity", record=record, before=None,
                       after=after, success=False, error=outcome_msg)
            return StepResult("failed", "Activity creation failed")
        self.audit(action_id=action_id, system="ODOO", action="schedule_activity", record=record, before=None,
                   after=after, success=outcome.success, error="" if outcome.success else outcome.message)
        return StepResult("success") if outcome.success else StepResult("failed", "Activity creation failed")
