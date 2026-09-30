"""A tiny fake Odoo (17/18-like DOM + /web/dataset/call_kw) used only by browser tests.

It lets the real Playwright adapter be exercised end-to-end without touching a real Odoo.
"""
from __future__ import annotations

import html
import json
import socket
import threading
import time
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

SESSION = "fake-session-123"


class FakeOdooState:
    def __init__(self) -> None:
        self.leads: dict[int, dict[str, Any]] = {
            7: {"id": 7, "name": "فرصة - مؤسسة الاختبار", "partner_name": "مؤسسة الاختبار", "contact_name": "سعد",
                "phone": "+966 56 123 4567", "mobile": "", "email_from": "test@example.com", "user_id": [2, "خالد"],
                "stage_id": [1, "جديد"], "source_id": [3, "Meta"], "medium_id": [4, "Leads"],
                "campaign_id": [5, "حملة سبتمبر"], "type": "lead", "active": True, "x_service_type": "رصد التواجد",
                "write_date": "2026-09-28 10:00:00"},
            8: {"id": 8, "name": "شركة بلا زر", "partner_name": "شركة بلا زر", "contact_name": "", "phone": "",
                "mobile": "", "email_from": "", "user_id": False, "stage_id": [1, "جديد"], "source_id": False,
                "medium_id": False, "campaign_id": False, "type": "lead", "active": True, "x_service_type": False,
                "write_date": "2026-09-28 10:00:00"},
        }
        # Pre-existing chatter history on lead 7 (written by people, before the agent).
        self.messages: list[dict[str, Any]] = [
            {"id": 1, "model": "crm.lead", "res_id": 7, "body": "<p>Lead created from Meta</p>", "is_html": True,
             "message_type": "notification", "subtype": "crm.mt_lead_create", "subtype_id": [9, "Lead Created"],
             "author_id": [1, "OdooBot"], "date": "2026-09-20 08:00:00", "tracking_value_ids": []},
            {"id": 2, "model": "crm.lead", "res_id": 7, "body": "", "is_html": True, "message_type": "notification",
             "subtype": "crm.mt_lead_stage", "subtype_id": [10, "Stage Changed"], "author_id": [3, "سارة"],
             "date": "2026-09-21 09:30:00", "tracking_value_ids": [1]},
            {"id": 3, "model": "crm.lead", "res_id": 7, "body": "<p>العميل طلب عرض سعر<br>ويريد التواصل مساءً</p>", "is_html": True,
             "message_type": "comment", "subtype": "mail.mt_note", "subtype_id": [2, "Note"],
             "author_id": [3, "سارة"], "date": "2026-09-22 14:10:00", "tracking_value_ids": []},
        ]
        self.tracking: dict[int, dict[str, Any]] = {
            1: {"id": 1, "field_desc": "Stage", "old_value_char": "جديد", "new_value_char": "مؤهل"},
        }
        self.activities: list[dict[str, Any]] = []
        self.clock = 0
        self.calls_clicked: list[str] = []
        self.rpc_log_notes = 0
        self.created: list[dict[str, Any]] = []
        self.utm: dict[str, dict[int, str]] = {"utm.source": {3: "Meta", 6: "Google"}, "utm.medium": {4: "Leads"}}

    def now(self) -> str:
        """Monotonic fake timestamps so every write gets a new write_date."""
        self.clock += 1
        return f"2026-09-29 10:{self.clock // 60:02d}:{self.clock % 60:02d}"

    def edit_lead(self, lead_id: int, **values: Any) -> None:
        """Simulate the user editing the lead directly in Odoo."""
        self.leads[lead_id].update(values, write_date=self.now())

    def add_message(self, lead_id: int, body: str, message_type: str = "comment", subtype: str = "mail.mt_note",
                    author: str = "خالد") -> None:
        ts = self.now()
        self.messages.append({"id": len(self.messages) + 1, "model": "crm.lead", "res_id": lead_id, "body": body,
                              "message_type": message_type, "subtype": subtype,
                              "subtype_id": [2, "Note"] if subtype == "mail.mt_note" else [1, "Discussions"],
                              "author_id": [2, author], "date": ts, "write_date": ts, "tracking_value_ids": []})


FIELDS = {
    "name": {"string": "Opportunity", "type": "char"}, "partner_name": {"string": "Company Name", "type": "char"},
    "contact_name": {"string": "Contact Name", "type": "char"}, "phone": {"string": "Phone", "type": "char"},
    "mobile": {"string": "Mobile", "type": "char"}, "email_from": {"string": "Email", "type": "char"},
    "user_id": {"string": "Salesperson", "type": "many2one"}, "stage_id": {"string": "Stage", "type": "many2one"},
    "source_id": {"string": "Source", "type": "many2one"}, "medium_id": {"string": "Medium", "type": "many2one"},
    "campaign_id": {"string": "Campaign", "type": "many2one"}, "type": {"string": "Type", "type": "selection"},
    "active": {"string": "Active", "type": "boolean"},
    "x_service_type": {"string": "Service Type", "type": "char"},
    "write_date": {"string": "Last Updated on", "type": "datetime"},
}
MESSAGE_FIELDS = {f: {"string": f, "type": "char"} for f in (
    "body", "date", "author_id", "message_type", "subtype_id", "tracking_value_ids", "write_date")}


def _match(rec: dict, term: list) -> bool:
    field, op, value = term
    if op == "=":
        return rec.get(field) == value
    if op == "=ilike":
        return str(rec.get(field) or "").lower() == str(value).lower()
    if op == "ilike":
        v = rec.get(field)
        if isinstance(v, list):
            v = v[1]
        return bool(v) and str(value).lower() in str(v).lower()
    return False


def eval_domain(rec: dict, domain: list) -> bool:
    """Supports prefix '|' chains and implicit AND of terms (enough for the adapter)."""
    stack: list[bool] = []
    for item in reversed(domain):
        if item == "|":
            a, b = stack.pop(), stack.pop()
            stack.append(a or b)
        elif item == "&":
            a, b = stack.pop(), stack.pop()
            stack.append(a and b)
        else:
            stack.append(_match(rec, item))
    return all(stack)


def _m2o(v):
    return v[1] if isinstance(v, list) else (v or "")


def make_app(state: FakeOdooState) -> FastAPI:
    app = FastAPI()

    def logged(request: Request) -> bool:
        return request.cookies.get("session_id") == SESSION

    @app.get("/web/login", response_class=HTMLResponse)
    def login_page():
        return """<html><body><form class="oe_login_form" method="post" action="/web/login">
          <input type="text" name="login"><input type="password" name="password"><button type="submit">Log in</button>
          </form></body></html>"""

    @app.post("/web/login")
    def do_login():
        resp = RedirectResponse("/odoo", status_code=303)
        resp.set_cookie("session_id", SESSION)
        return resp

    @app.get("/odoo", response_class=HTMLResponse)
    def home(request: Request):
        if not logged(request):
            return RedirectResponse("/web/login", status_code=303)
        return "<html><body><div class='o_web_client'>Home</div></body></html>"

    @app.post("/web/session/get_session_info")
    async def session_info(request: Request):
        if not logged(request):
            return JSONResponse({"jsonrpc": "2.0", "id": 1, "error": {"code": 100, "message": "Odoo Session Expired",
                                                                     "data": {"name": "odoo.http.SessionExpiredException"}}})
        return {"jsonrpc": "2.0", "id": 1, "result": {"uid": 2, "name": "Khalid Test"}}

    @app.post("/web/dataset/call_kw/{model}/{method}")
    async def call_kw(model: str, method: str, request: Request):
        if not logged(request):
            return JSONResponse({"jsonrpc": "2.0", "id": 1, "error": {"code": 100, "message": "Session expired",
                                                                     "data": {"name": "odoo.http.SessionExpiredException"}}})
        params = (await request.json())["params"]
        args, kwargs = params.get("args", []), params.get("kwargs", {})
        result: Any = None
        if model == "crm.lead" and method == "fields_get":
            result = FIELDS
        elif model == "crm.lead" and method == "search_read":
            fields = kwargs.get("fields") or list(FIELDS)
            result = [{"id": r["id"], **{f: r.get(f, False) for f in fields}}
                      for r in state.leads.values() if eval_domain(r, kwargs.get("domain", []))]
        elif model == "crm.lead" and method == "read":
            fields = kwargs.get("fields") or list(FIELDS)
            result = [{"id": state.leads[i]["id"], **{f: state.leads[i].get(f, False) for f in fields}}
                      for i in args[0] if i in state.leads]
        elif model in ("utm.source", "utm.medium") and method == "search_read":
            table = state.utm[model]
            result = [{"id": i, "name": n} for i, n in table.items() if eval_domain({"name": n}, kwargs.get("domain", []))]
        elif model == "crm.lead" and method == "create":
            vals = args[0]
            new_id = max(state.leads, default=0) + 1
            rec = {f: False for f in FIELDS}
            rec.update({"id": new_id, "active": True, "stage_id": [1, "جديد"], "write_date": state.now()})
            rec.update({k: v for k, v in vals.items() if k not in ("user_id", "source_id", "medium_id")})
            for fname, model_name in (("source_id", "utm.source"), ("medium_id", "utm.medium")):
                if vals.get(fname):
                    rec[fname] = [vals[fname], state.utm[model_name][vals[fname]]]
            if vals.get("user_id"):
                rec["user_id"] = [vals["user_id"], "Khalid Test"]
            state.leads[new_id] = rec
            state.created.append(dict(vals))
            result = new_id
        elif model == "crm.lead" and method == "message_post":
            state.rpc_log_notes += 1
            for lead_id in args[0]:
                state.add_message(lead_id, kwargs["body"], kwargs.get("message_type") or "comment",
                                  kwargs.get("subtype_xmlid") or "mail.mt_note")
            result = len(state.messages)
        elif model == "crm.lead" and method == "activity_schedule":
            for lead_id in args[0]:
                state.activities.append({"id": len(state.activities) + 1, "res_model": "crm.lead", "res_id": lead_id,
                                         "write_date": state.now(), **kwargs})
            result = True
        elif model == "mail.message" and method == "fields_get":
            result = MESSAGE_FIELDS
        elif model == "mail.message" and method in ("search_read", "search_count"):
            domain = kwargs.get("domain") if method == "search_read" else args[0]
            rows = [m for m in state.messages if eval_domain(m, domain)]
            if method == "search_count":
                result = len(rows)
            else:
                fields = kwargs.get("fields") or list(MESSAGE_FIELDS)
                rows = sorted(rows, key=lambda m: (m.get("write_date") or m["date"], m["id"]), reverse=True)
                rows = rows[: kwargs.get("limit") or len(rows)]
                result = [{"id": m["id"], **{f: (m["body"] if m.get("is_html") else html.escape(m["body"])) if f == "body" else
                                             m.get(f, m["date"] if f == "write_date" else False) for f in fields}}
                          for m in rows]
        elif model == "mail.tracking.value" and method == "read":
            result = [state.tracking[i] for i in args[0] if i in state.tracking]
        elif model == "mail.activity" and method == "search_read":
            rows = [a for a in state.activities if eval_domain(a, kwargs.get("domain", []))]
            result = [{"id": a["id"], "date_deadline": a.get("date_deadline", False), "summary": a.get("summary", False),
                       "write_date": a["write_date"]} for a in rows]
        else:
            return {"jsonrpc": "2.0", "id": 1, "error": {"code": 200, "message": "Odoo Server Error",
                                                         "data": {"name": "builtins.AttributeError",
                                                                  "message": f"unknown {model}.{method}"}}}
        return {"jsonrpc": "2.0", "id": 1, "result": result}

    @app.post("/test/called")
    async def called(request: Request):
        state.calls_clicked.append((await request.json())["href"])
        return {"ok": True}

    @app.get("/odoo/crm.lead/{lead_id}", response_class=HTMLResponse)
    def form(lead_id: int, request: Request):
        if not logged(request):
            return RedirectResponse("/web/login", status_code=303)
        r = state.leads[lead_id]
        msgs = "".join(f"<div class='o-mail-Message'><span class='o-mail-Message-author'>{html.escape(_m2o(m.get('author_id')))}</span>"
                       f"<span class='o-mail-Message-date' title='{m['date']}'>now</span>"
                       f"<div class='o-mail-Message-body'>{m['body'] if m.get('is_html') else html.escape(m['body'])}</div></div>"
                       for m in reversed(state.messages) if m["res_id"] == lead_id)

        def field(name: str, label: str, value: str, extra: str = "") -> str:
            return (f"<div class='o_wrap_field'><div class='o_cell o_wrap_label'><label class='o_form_label' for='{name}_0'>{label}</label></div>"
                    f"<div class='o_cell'><div name='{name}' class='o_field_widget o_field_char'>"
                    f"<input id='{name}_0' class='o_input' value='{html.escape(value)}'>{extra}</div></div></div>")

        phone = r["phone"]
        call_link = (f"<a class='ms-3 d-inline-flex align-items-center o_phone_form_link' href='tel:{html.escape(phone)}'>"
                     f"<i class='fa fa-phone'></i><small class='fw-bold ms-1'>Call</small></a>") if phone else ""
        return f"""<html><body><div class="o_action_manager"><div class="o_form_view o_lead_opportunity_form">
        <div class="o_form_view_container"><div class="o_statusbar_status">
          <button class="btn o_arrow_button_current" aria-checked="true">{_m2o(r['stage_id'])}</button></div>
        <div class="o_form_sheet">
          {field('name', 'Opportunity', r['name'])}
          {field('partner_name', 'Company Name', r['partner_name'])}
          {field('contact_name', 'Contact Name', r['contact_name'])}
          {field('phone', 'Phone', phone, call_link)}
          {field('email_from', 'Email', r['email_from'])}
          {field('user_id', 'Salesperson', _m2o(r['user_id']))}
          {field('source_id', 'Source', _m2o(r['source_id']))}
          {field('medium_id', 'Medium', _m2o(r['medium_id']))}
          {field('campaign_id', 'Campaign', _m2o(r['campaign_id']))}
          <div class="o_wrap_field"><div class="o_cell"><label class="o_form_label">Service Type</label></div>
            <div class="o_cell"><span>{html.escape(r['x_service_type'] or '')}</span></div></div>
        </div></div>
        <div class="o-mail-Chatter">
          <button class="btn o-mail-Chatter-sendMessage">Send message</button>
          <button class="btn o-mail-Chatter-logNote">Log note</button>
          <button class="btn o-mail-Chatter-activity">Activities</button>
          <div id="composer"></div><div class="o-mail-Thread">{msgs}</div>
        </div></div></div>
        <script>
          document.querySelectorAll("a[href^='tel:']").forEach(a => a.addEventListener('click', ev => {{
            ev.preventDefault();
            fetch('/test/called', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{href: a.getAttribute('href')}})}});
          }}));
          document.querySelector('.o-mail-Chatter-logNote').onclick = () => {{
            document.getElementById('composer').innerHTML = `<div class="o-mail-Composer"><textarea class="o-mail-Composer-input"></textarea>
              <button class="o-mail-Composer-send btn btn-primary">Log</button></div>`;
            document.querySelector('.o-mail-Composer-send').onclick = async () => {{
              const body = document.querySelector('.o-mail-Composer-input').value;
              await fetch('/web/dataset/call_kw/crm.lead/message_post', {{method: 'POST', headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{params: {{args: [[{lead_id}]], kwargs: {{body, message_type: 'comment', subtype_xmlid: 'mail.mt_note'}}}}}})}});
              const div = document.createElement('div'); div.className = 'o-mail-Message';
              div.innerHTML = '<div class="o-mail-Message-body"></div>'; div.firstChild.textContent = body;
              document.querySelector('.o-mail-Thread').prepend(div);
              document.getElementById('composer').innerHTML = '';
            }};
          }};
        </script></body></html>"""

    return app


class FakeOdooServer:
    """Runs the fake Odoo in a background thread on a free local port."""

    def __init__(self) -> None:
        self.state = FakeOdooState()
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.server = uvicorn.Server(uvicorn.Config(make_app(self.state), host="127.0.0.1", port=self.port,
                                                    log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> FakeOdooServer:
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                break
            time.sleep(0.05)
        return self

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        self.thread.join(5)


if __name__ == "__main__":  # manual debugging
    with FakeOdooServer() as srv:
        print(srv.url, json.dumps({"lead": 7}))
        time.sleep(3600)
