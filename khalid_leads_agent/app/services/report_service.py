"""Performance report: calls, answer / interest rates, subscriptions, WhatsApp, per day and per source.

Only real saves count (Dry Run results are previews). Periods are local days (Saudi week starts Sunday).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select

from app.db import Database
from app.errors import AgentError
from app.models import CallResult, LeadCache, OutreachMessage
from app.services.mapping_service import MappingService
from app.utils.timeutils import fmt_local, localnow, to_local
from app.utils.xlsx import write_xlsx

NOT_ANSWERED = ("NO_ANSWER", "INVALID_NUMBER")
POSITIVE = ("INTERESTED", "SUBSCRIBED")
PERIODS = {"today": "اليوم", "week": "هذا الأسبوع", "month": "هذا الشهر", "custom": "فترة مخصصة"}


def _utc(d: date) -> datetime:
    return datetime.combine(d, time(0, 0)).astimezone(timezone.utc).replace(tzinfo=None)


def period_range(period: str, start: str = "", end: str = "") -> tuple[date, date]:
    """Inclusive local dates."""
    today = localnow().date()
    if period == "today":
        return today, today
    if period == "week":
        return today - timedelta(days=(today.weekday() + 1) % 7), today
    if period == "month":
        return today.replace(day=1), today
    if period == "custom":
        try:
            a = datetime.strptime(start, "%Y-%m-%d").date()
            b = datetime.strptime(end or start, "%Y-%m-%d").date()
        except ValueError as exc:
            raise AgentError("BAD_DATE", "حدد تاريخ البداية والنهاية.") from exc
        if b < a:
            a, b = b, a
        if (b - a).days > 366:
            raise AgentError("RANGE_TOO_LONG", "الفترة طويلة جدًا (سنة كحد أقصى).")
        return a, b
    raise AgentError("BAD_PERIOD", "فترة غير معروفة.")


def _rate(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


class ReportService:
    def __init__(self, db: Database, mappings: MappingService) -> None:
        self.db = db
        self.mappings = mappings

    def _rows(self, a: date, b: date):
        since, until = _utc(a), _utc(b + timedelta(days=1))
        with self.db.session() as s:
            results = list(s.scalars(select(CallResult).where(
                CallResult.dry_run.is_(False), CallResult.status != "failed",
                CallResult.created_at >= since, CallResult.created_at < until).order_by(CallResult.id)))
            fps = {r.fingerprint for r in results if r.fingerprint}
            caches = {c.fingerprint: c for c in s.scalars(select(LeadCache).where(LeadCache.fingerprint.in_(fps)))} if fps else {}
            messages = list(s.scalars(select(OutreachMessage).where(
                OutreachMessage.dry_run.is_(False), OutreachMessage.created_at >= since,
                OutreachMessage.created_at < until).order_by(OutreachMessage.id)))
            for obj in (*results, *caches.values(), *messages):
                s.expunge(obj)
        return results, caches, messages

    @staticmethod
    def _source(r: CallResult, cache: LeadCache | None) -> str:
        if r.source_value.strip():
            return r.source_value.strip()
        if cache is not None:
            if cache.sheet_source.strip():
                return cache.sheet_source.strip()
            odoo = cache.odoo_data or {}
            if (odoo.get("source") or "").strip():
                return odoo["source"].strip()
        return "غير محدد"

    def build(self, period: str = "week", start: str = "", end: str = "") -> dict:
        a, b = period_range(period, start, end)
        results, caches, messages = self._rows(a, b)
        codes = Counter(r.result_code for r in results)
        calls = len(results)
        answered = calls - sum(codes[c] for c in NOT_ANSWERED)
        positive = sum(codes[c] for c in POSITIVE)
        by_day: dict[date, int] = {a + timedelta(days=i): 0 for i in range((b - a).days + 1)}
        for r in results:
            d = to_local(r.created_at).date()
            if d in by_day:
                by_day[d] += 1
        per_source: dict[str, Counter] = defaultdict(Counter)
        for r in results:
            per_source[self._source(r, caches.get(r.fingerprint))][r.result_code] += 1
        sources = []
        for name, cnt in per_source.items():
            total = sum(cnt.values())
            ans = total - sum(cnt[c] for c in NOT_ANSWERED)
            pos = sum(cnt[c] for c in POSITIVE)
            sources.append({"source": name, "calls": total, "answered": ans, "interested": cnt["INTERESTED"],
                            "subscribed": cnt["SUBSCRIBED"], "follow_up": cnt["FOLLOW_UP"],
                            "not_interested": cnt["NOT_INTERESTED"], "answer_rate": _rate(ans, total),
                            "interest_rate": _rate(pos, ans)})
        sources.sort(key=lambda x: (-x["calls"], x["source"]))
        labels = {s["code"]: s["label"] for s in self.mappings.statuses()}
        return {
            "period": period, "period_label": PERIODS.get(period, period),
            "start": a.isoformat(), "end": b.isoformat(),
            "totals": {"calls": calls, "answered": answered, "answer_rate": _rate(answered, calls),
                       "interested": codes["INTERESTED"], "subscribed": codes["SUBSCRIBED"],
                       "interest_rate": _rate(positive, answered), "follow_up": codes["FOLLOW_UP"],
                       "no_answer": codes["NO_ANSWER"], "whatsapp": len(messages),
                       "customers": len({r.fingerprint or r.phone_norm for r in results})},
            "by_result": [{"code": c, "label": labels.get(c, c), "count": codes[c]} for c in labels],
            "by_day": [{"date": d.isoformat(), "calls": n} for d, n in by_day.items()],
            "by_source": sources,
            "_results": results, "_caches": caches, "_messages": messages, "_labels": labels,
        }

    def public(self, report: dict) -> dict:
        return {k: v for k, v in report.items() if not k.startswith("_")}

    def export_xlsx(self, period: str = "week", start: str = "", end: str = "") -> tuple[bytes, str]:
        rep = self.build(period, start, end)
        t, labels = rep["totals"], rep["_labels"]
        summary = [
            ["المؤشر", "القيمة"],
            ["الفترة", f"{rep['period_label']} ({rep['start']} → {rep['end']})"],
            ["عدد النتائج المسجلة (مكالمات)", t["calls"]], ["عدد العملاء", t["customers"]],
            ["تم الرد", t["answered"]], ["نسبة الرد %", t["answer_rate"]],
            ["مهتم", t["interested"]], ["تم الاشتراك", t["subscribed"]],
            ["نسبة الاهتمام من الردود %", t["interest_rate"]], ["متابعة لاحقة", t["follow_up"]],
            ["لم يتم الرد", t["no_answer"]], ["رسائل واتساب", t["whatsapp"]],
        ]
        summary += [[f"النتيجة: {r['label']}", r["count"]] for r in rep["by_result"]]
        per_day = [["اليوم", "عدد النتائج"]] + [[d["date"], d["calls"]] for d in rep["by_day"]]
        per_source = [["المصدر", "النتائج", "تم الرد", "نسبة الرد %", "مهتم", "تم الاشتراك", "متابعة", "غير مهتم",
                       "نسبة الاهتمام %"]]
        per_source += [[s["source"], s["calls"], s["answered"], s["answer_rate"], s["interested"], s["subscribed"],
                        s["follow_up"], s["not_interested"], s["interest_rate"]] for s in rep["by_source"]]
        details = [["التاريخ", "العميل", "الجوال", "النتيجة", "المصدر", "الملاحظة", "موعد المتابعة", "صف Sheet",
                    "Odoo Lead"]]
        for r in rep["_results"]:
            details.append([fmt_local(r.created_at), r.company_name, r.phone, labels.get(r.result_code, r.result_code),
                            self._source(r, rep["_caches"].get(r.fingerprint)), r.note, r.followup_at,
                            r.sheet_row or "", r.odoo_lead_id or ""])
        wa = [["التاريخ", "العميل", "الرقم", "القالب", "النص"]]
        wa += [[fmt_local(m.created_at), m.company_name, m.phone, m.template, m.text] for m in rep["_messages"]]
        data = write_xlsx([
            ("الملخص", summary, [34, 30]), ("حسب اليوم", per_day, [14, 14]),
            ("حسب المصدر", per_source, [24, 10, 10, 12, 10, 12, 10, 10, 16]),
            ("التفاصيل", details, [17, 30, 16, 16, 18, 50, 18, 10, 10]), ("واتساب", wa, [17, 30, 16, 18, 60]),
        ])
        return data, f"leads-report-{rep['start']}_{rep['end']}.xlsx"
