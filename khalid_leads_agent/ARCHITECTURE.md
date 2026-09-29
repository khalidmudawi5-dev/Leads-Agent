# Khalid Leads Agent — Architecture

## Overview

```
Browser UI (Jinja2 + vanilla JS, Arabic RTL)
        │  JSON API (X-KLA header, 127.0.0.1 only)
        ▼
FastAPI routers (app/api)  ──►  Services (app/services)  ──►  Repositories (app/repositories) ──► SQLite
                                     │
                                     ├── SheetsClient (app/adapters/google)  ──► Google Sheets Values API
                                     └── OdooAdapter  (app/adapters/odoo)    ──► Playwright persistent browser ──► Odoo
```

The workflow is deterministic end to end. No LLM decides customer identity, row matching, source mapping or result.

## Folders

| Path | Responsibility |
|---|---|
| `app/main.py` | App factory: security middleware (TrustedHost, CSRF header, same-origin), error handlers (Arabic messages; full traces only in logs), routers, static files |
| `app/config.py` | `EnvSettings` (.env bootstrap) + `AppSettings` (user settings stored in SQLite) |
| `app/db.py` | SQLAlchemy engine/session, `create_all` + additive column migrations (`MIGRATIONS`) |
| `app/container.py` | Dependency wiring; tests inject mock adapters here |
| `app/models/tables.py` | `settings, lead_sessions, lead_cache, call_results, sync_logs, audit_logs, error_logs, source_mappings, status_mappings, skipped_leads` |
| `app/repositories/*` | Data access only |
| `app/services/settings_service.py` | Merged settings, default status mappings |
| `app/services/google_auth_service.py` | OAuth Desktop flow (default) and Service Account; token stored in `data/credentials` |
| `app/services/google_sheets_service.py` | Header-based column resolution, sheet parsing, **safe update** (`locate` → `plan_update` → `apply`) |
| `app/services/lead_queue_service.py` | Owner filter, pending values, ordering, exclusion of completed/skipped/snoozed |
| `app/services/session_service.py` | Resumable session (current fingerprint, completed, skipped, errors) |
| `app/services/odoo_service.py` | Matching priority: phone → mobile → company exact → company partial (partial is never auto-opened) |
| `app/services/mapping_service.py` | Status mapping and Source mapping (normalized exact keys only) |
| `app/services/sync_service.py` | External writes with audit and dry run |
| `app/services/call_result_service.py` | Result saving: idempotency, duplicate window, dry-run preview, partial failures, retry. Has a V2 voice TODO |
| `app/services/lead_workflow_service.py` | Orchestration used by the dashboard (current/next/skip/search/select/open/call/refresh/manual mode) |
| `app/adapters/odoo/base.py` | `OdooAdapter` interface + `OdooLead`, `ActionOutcome`, `LoginStatus` |
| `app/adapters/odoo/browser_adapter.py` | `BrowserOdooAdapter` (V1) |
| `app/adapters/odoo/api_adapter.py` | `FutureApiOdooAdapter` placeholder (V2) |
| `app/adapters/odoo/odoo_selectors.py` | Every DOM selector, with ordered fallbacks |
| `app/adapters/odoo/browser_runtime.py` | Dedicated thread + event loop (Proactor on Windows) that serializes all browser actions |
| `app/adapters/odoo/mock_adapter.py` | In-memory adapter for tests / `USE_MOCKS` |
| `app/adapters/google/*` | `SheetsClient` interface, real API client, in-memory client, fictional demo data |
| `app/utils/phone.py` | `normalize_phone()`, which is Saudi aware (05…, 9665…, +966 5…, Arabic-Indic digits) |
| `app/utils/text.py` | Company/owner normalization, fingerprint |

## Key design decisions

### Lead identity (fingerprint)
`sha1(normalized company | normalized phone | normalized owner)`. The sheet row number is a performance hint only. Resuming a session and locating a row before an update both use the fingerprint and company + phone.

### Safe Google Sheet update
1. Re-read the whole tab and re-resolve columns from header text.
2. Locate the row. Try the hinted row first, but only if company and phone still match; otherwise search all rows. The owner must still equal the agent owner, else `OwnerChanged`. If there are 0 matches, or 2 or more rows owned by the owner match, the update is blocked (`RowNotFound`).
3. Compute the cells that actually change. Notes are appended, and a retry never re-appends the same entry. Values are validated against the column's Data Validation list.
4. Write through `spreadsheets.values.batchUpdate`, single cells only. RAW input is used, except dates, which use USER_ENTERED. There are no clear, format or full-row writes.
5. Record every cell in `sync_logs` (old/new value backup) and the action in `audit_logs`.

### Odoo without version lock-in
- A persistent Playwright profile (`data/browser-profile`) means the user logs in manually and no password is stored.
- Structured reads use the logged-in session's generic web-client endpoint `/web/dataset/call_kw`. Available fields are discovered with `fields_get`, and for phone search `phone_mobile_search` is used when present. Every read also has a DOM fallback driven by `odoo_selectors.py`.
- **Calls:** the agent opens the lead, then clicks Odoo's own phone/Call link. Windows' `tel:` handler (Phone Link) does the rest. The optional `windows_handler` mode reads the same link from Odoo and hands it to Windows directly.
- **Log note:** by default the agent uses the UI Log note composer (never "Send message"). If that fails it falls back to `message_post(subtype_xmlid="mail.mt_note")`. Each note carries a `KLA-…` reference, checked before and after every attempt, so it is never posted twice.
- **Activity:** created with `activity_schedule`. A failure only produces a warning; the note and the sheet update still complete.
- There are screenshots on automation errors, limited retries, configurable timeouts, and one relaunch if the user closed the browser window.

### Chatter history & live sync
- `get_lead` also returns `chatter` (newest first, up to `chatter_history_limit`): notes, messages, emails and field tracking (`mail.tracking.value`, read best-effort because it is often admin-only), plus planned `activities`. Fields are requested only if `fields_get` reports them, so Odoo 17/18/19 all work. A DOM fallback reads `.o-mail-Message` items when JSON-RPC is unavailable.
- `lead_signature(lead_id)` is a cheap fingerprint: lead `write_date` + message count + latest message `write_date` + activity ids/`write_date`. It returns `None` when the browser has not been started, so polling never launches a browser.
- The dashboard polls `GET /api/lead/{fingerprint}/live?since=<sig>` (or `/api/manual/{id}/live`) every `live_sync_interval_seconds`, paused while the tab is hidden. When the signature changes the server re-reads the lead, updates `lead_cache`, and returns the refreshed payload. Polling errors are returned quietly (`login_required` / `error`) and are not stored in `error_logs`.

### UI
- Tajawal font bundled locally in `app/static/fonts` (SIL OFL), a light/dark theme (`Alt+D`, remembered per browser), and a layout-independent keyboard shortcut registry (`Shortcuts` in `app.js`, using `KeyboardEvent.code` so it also works on the Arabic keyboard layout).

### Dry Run & duplicates
- Dry Run is ON by default. It produces the same plan as a real save, including fresh sheet values and the appended notes, but writes nothing and records `dry_run` in the audit.
- Idempotency: the client sends an `idempotency_key` per result panel. Replaying the same key returns the first outcome. Saves are serialized per lead with an asyncio lock. The same lead + same result inside `duplicate_window_seconds` is not written again.

### Error handling
`AgentError(code, message_ar, actions)` is converted to JSON `{error: {code, message, actions}}`, and the UI shows the Arabic message with action buttons (retry / open Odoo / skip / login / settings). Unexpected exceptions return a generic Arabic message. The full stack trace goes to `logs/agent.log`, and the error is stored in `error_logs`.

### Extending
- **Odoo API adapter:** implement `OdooAdapter` in `api_adapter.py` and select it in `container.py`.
- **Voice (V2):** a voice pipeline only pre-fills `ResultIn` (`input_channel="voice"`), and the user confirms it. See the docstring of `call_result_service.py`.
- **DB migrations:** append `(table, column, DDL)` to `MIGRATIONS` in `app/db.py`.
