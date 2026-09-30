"""Lead ordering, pending values and session resume."""
from app.config import EMPTY_TOKEN
from app.services.lead_queue_service import order_leads
from tests.conftest import make_container


def companies(leads):
    return [lead.company_name for lead in leads]


def test_default_queue_is_owner_pending_top_to_bottom(container):
    container.queue.refresh()
    assert companies(container.queue.queue()) == ["مؤسسة الاختبار الأولى", "شركة الأمل", "مكتب التقنية"]


def test_pending_values_are_configurable(container):
    container.settings.update({"pending_status_values": [EMPTY_TOKEN]})
    container.queue.refresh()
    assert companies(container.queue.queue()) == ["مؤسسة الاختبار الأولى"]
    container.settings.update({"pending_status_values": ["مهتم", "متابعة"]})
    assert companies(container.queue.queue()) == ["مصنع مكتمل", "مكتب التقنية"]


def test_ordering_modes(container):
    leads = container.sheets.owner_leads(container.sheets.load())
    assert companies(order_leads(leads, "sheet_reverse"))[0] == "مكتب التقنية"
    leads[0].lead_date, leads[1].lead_date = "05/09/2026", "01/09/2026"
    assert companies(order_leads(leads, "oldest_first"))[:2] == ["شركة الأمل", "مؤسسة الاختبار الأولى"]
    assert companies(order_leads(leads, "newest_first"))[0] == "مؤسسة الاختبار الأولى"


def test_skip_and_snooze_remove_from_queue(container):
    import asyncio

    wf = container.workflow
    first = asyncio.run(wf.current())["lead"]
    assert first["company_name"] == "مؤسسة الاختبار الأولى"
    nxt = asyncio.run(wf.skip(first["fingerprint"], "10m"))
    assert nxt["lead"]["company_name"] == "شركة الأمل"
    nxt = asyncio.run(wf.skip(nxt["lead"]["fingerprint"], "session"))
    assert nxt["lead"]["company_name"] == "مكتب التقنية"
    assert container.sessions.to_dict(container.sessions.active())["skipped_count"] == 1


def test_resume_session_after_restart(env, sheet, odoo):
    import asyncio

    c1 = make_container(env, sheet, odoo)
    lead = asyncio.run(c1.workflow.current())["lead"]
    c1.sessions.mark_completed(lead["fingerprint"])
    second = asyncio.run(c1.workflow.next())["lead"]
    asyncio.run(c1.workflow.skip(second["fingerprint"], "session"))
    third = asyncio.run(c1.workflow.current())["lead"]

    # "Restart": a brand new container on the same SQLite file.
    c2 = make_container(env, sheet, odoo)
    st = c2.sessions.status()
    assert st["needs_prompt"] is True
    assert st["session"]["completed"] == [lead["fingerprint"]]
    assert st["session"]["skipped"] == [second["fingerprint"]]
    c2.sessions.start(resume=True)
    resumed = asyncio.run(c2.workflow.current())["lead"]
    assert resumed["fingerprint"] == third["fingerprint"]
    assert c2.sessions.status()["needs_prompt"] is False

    # Resume works by fingerprint, not by row number: insert a row above.
    sheet.sheets["Leads"].insert(1, ["0", "سارة", "جديد", "", "0500000000", "", "", "", "", "", ""])
    c3 = make_container(env, sheet, odoo)
    c3.sessions.start(resume=True)
    again = asyncio.run(c3.workflow.current())["lead"]
    assert again["fingerprint"] == third["fingerprint"] and again["sheet_row"] == third["sheet_row"] + 1

    # New session: previous completed/skipped lists are cleared.
    c3.sessions.start(resume=False)
    assert asyncio.run(c3.workflow.current())["lead"]["company_name"] == "مؤسسة الاختبار الأولى"


def test_db_init_is_idempotent(container):
    container.db.init()
    container.db.init()
    container.settings.seed()
    assert len(container.mappings.statuses()) == 6
