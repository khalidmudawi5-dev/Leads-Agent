"""End-of-day summary: today's numbers, interested customers, open follow-ups and who needs WhatsApp.

Read-only (nothing is written to Odoo or the sheet). Only real saves count, as in the reports.
A plain-text version is included so it can be copied or sent (e.g. to the manager on WhatsApp).
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.models import OutreachMessage
from app.services.report_service import POSITIVE, ReportService
from app.services.settings_service import SettingsService
from app.utils.phone import format_phone
from app.utils.timeutils import localnow, to_local, utcnow


class SummaryService:
    def __init__(self, workflow, reports: ReportService, settings: SettingsService) -> None:
        self.workflow = workflow
        self.reports = reports
        self.settings = settings

    def _whatsapp_since(self, days: int = 30) -> dict[str, object]:
        """Latest real WhatsApp message per customer (UTC)."""
        with self.workflow.db.session() as s:
            rows = s.execute(select(OutreachMessage.fingerprint, OutreachMessage.created_at)
                             .where(OutreachMessage.dry_run.is_(False),
                                    OutreachMessage.created_at >= utcnow() - timedelta(days=days))).all()
        last: dict[str, object] = {}
        for fp, at in rows:
            if fp and (fp not in last or at > last[fp]):
                last[fp] = at
        return last

    async def today(self) -> dict:
        wf = self.workflow
        if not wf.queue.loaded:
            await wf._refresh(strict=False)
        s = self.settings.get()
        rep = self.reports.build("today")
        t = rep["totals"]
        results = rep["_results"]
        labels = rep["_labels"]
        now = localnow()
        tomorrow = (now.date() + timedelta(days=1)).isoformat()

        times = [to_local(r.created_at) for r in results]
        hot = [{"company": r.company_name, "phone": format_phone(r.phone), "code": r.result_code,
                "label": labels.get(r.result_code, r.result_code), "note": r.note, "fingerprint": r.fingerprint}
               for r in results if r.result_code in POSITIVE]

        items = wf.followup_items()
        fu_tomorrow = [i for i in items if i["state"] == "upcoming" and i["followup_at"][:10] == tomorrow]
        fu_open = [i for i in items if i["state"] in ("overdue", "due")]

        # No answer several times in a row and no WhatsApp since the last try.
        limit = s.no_answer_max_attempts or 2
        outcomes = wf.queue.followups.outcomes() if wf.queue.followups else {}
        wa_last = self._whatsapp_since()
        need_wa = []
        for lead in wf.queue.owner_leads:
            o = outcomes.get(lead.fingerprint)
            if not o or o.last_code != "NO_ANSWER":
                continue
            streak, _ = wf.no_answer_streak(lead.fingerprint, lead.notes, o.no_answer_streak)
            if streak < limit:
                continue
            sent = wa_last.get(lead.fingerprint)
            if sent is not None and sent >= o.last_at:
                continue
            need_wa.append({"fingerprint": lead.fingerprint, "company": lead.company_name,
                            "phone": format_phone(lead.phone_raw), "attempts": streak})
        need_wa.sort(key=lambda x: -x["attempts"])

        goal = s.daily_call_goal
        pending = len(wf.queue.queue())
        data = {
            "date": now.date().isoformat(), "owner": s.agent_owner,
            "totals": t, "goal": goal, "goal_pct": min(100, round(100 * t["calls"] / goal)) if goal else 0,
            "pending": pending,
            "first_at": min(times).strftime("%H:%M") if times else "",
            "last_at": max(times).strftime("%H:%M") if times else "",
            "by_result": [r for r in rep["by_result"] if r["count"]],
            "hot": hot, "followups_tomorrow": fu_tomorrow, "followups_open": fu_open,
            "need_whatsapp": need_wa, "attempts_limit": limit,
        }
        data["text"] = self._text(data)
        return data

    @staticmethod
    def _text(d: dict) -> str:
        t = d["totals"]
        lines = [f"ملخص اليوم {d['date']} — {d['owner']}", ""]
        goal = f" من هدف {d['goal']} ({d['goal_pct']}%)" if d["goal"] else ""
        lines.append(f"📞 النتائج المسجلة: {t['calls']}{goal}")
        if d["first_at"]:
            lines.append(f"🕘 من {d['first_at']} إلى {d['last_at']}")
        lines.append(f"✅ تم الرد: {t['answered']} ({t['answer_rate']}%) · لم يتم الرد: {t['no_answer']}")
        lines.append(f"⭐ مهتم: {t['interested']} · تم الاشتراك: {t['subscribed']} · متابعة لاحقة: {t['follow_up']}")
        lines.append(f"💬 رسائل واتساب: {t['whatsapp']} · بانتظار التواصل: {d['pending']}")
        if d["hot"]:
            lines += ["", "العملاء المهتمون اليوم:"]
            lines += [f"• {h['company']} ({h['label']})" + (f" — {h['note']}" if h["note"] else "") for h in d["hot"]]
        if d["followups_tomorrow"]:
            lines += ["", f"متابعات بكرة ({len(d['followups_tomorrow'])}):"]
            lines += [f"• {i['company']} {i['followup_at'][11:16]}".rstrip() for i in d["followups_tomorrow"]]
        if d["followups_open"]:
            lines += ["", f"متابعات مفتوحة لم تُنجز ({len(d['followups_open'])}):"]
            lines += [f"• {i['company']} ({i['followup_at'][:10]})" for i in d["followups_open"]]
        if d["need_whatsapp"]:
            lines += ["", f"يحتاجون واتساب (لم يردوا {d['attempts_limit']}+ مرات):"]
            lines += [f"• {w['company']} {w['phone']}" for w in d["need_whatsapp"]]
        return "\n".join(lines).strip()
