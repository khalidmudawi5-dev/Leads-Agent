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
- **Window-less reads:** after a signed-in RPC through the browser, the Odoo session cookies are saved to `data/odoo-session.json`. While the browser window is closed, RPC goes through a Playwright `APIRequestContext` with those cookies (no browser, no window); live-sync polling uses only that path. An expired saved session is deleted and the browser is used (sign-in). A relaunched browser receives the saved cookies if its profile has none. The window starts minimized and is shown only for user-visible actions.
- Structured reads use the logged-in session's generic web-client endpoint `/web/dataset/call_kw`. Available fields are discovered with `fields_get`, and for phone search `phone_mobile_search` is used when present. Every read also has a DOM fallback driven by `odoo_selectors.py`.
- **Calls:** the agent opens the lead, then clicks Odoo's own phone/Call link. Windows' `tel:` handler (Phone Link) does the rest. The optional `windows_handler` mode reads the same link from Odoo and hands it to Windows directly.
- **Log note:** by default the agent uses the UI Log note composer (never "Send message"). If that fails it falls back to `message_post(subtype_xmlid="mail.mt_note")`. Each note carries a `KLA-…` reference, checked before and after every attempt, so it is never posted twice.
- **New opportunity:** a customer missing from Odoo can be added from the dashboard (`POST /api/lead/{fp}/create-odoo`), only as an explicit user action. The workflow first re-runs matching with the entered name and number: a strong match (phone / exact company) is linked instead of creating a duplicate, and weak (partial name) matches need `force`. It then calls `crm.lead.create` (`name`, `partner_name`, `phone`, `contact_name`, `type` from `odoo_new_record_type`, the current user as `user_id`, and `source_id`/`medium_id` when a `utm.source`/`utm.medium` with the sheet source's name exists — a saved Source Mapping for that sheet value wins; nothing is created in UTM), links the new lead to the sheet row and writes an audit entry. Dry Run only previews. «Open in Odoo» and «Call» on an unlinked customer search first and offer this instead of opening the bare CRM page; `lead_cache.match_strategy` tells a real multiple match from similar names only.
- **Activity:** created with `activity_schedule`. A failure only produces a warning; the note and the sheet update still complete.
- There are screenshots on automation errors, limited retries, configurable timeouts, and one relaunch if the user closed the browser window.

### Customer report by status (read-only)
`CustomerReportService` filters the owner's fresh sheet rows by «حالة المتابعة», reads linked Odoo leads in one `crm.lead.read` batch (`adapter.read_leads`) and matches unlinked rows with the queue's matcher (capped at 150), then exports Excel (`utils.xlsx`), PDF (`adapter.render_pdf`: a separate headless Chromium/Chrome prints `report_customers_print.html`; the Odoo window is never used) or a printable HTML page. The last build is reused for exports for 5 minutes. Nothing is written anywhere.

### Sheet notes
`format_note_entry` writes the note on one line (lines joined with " - "); `note_stamp_format` is empty by default (no name / date). `merge_notes` appends after the old text with " | " (`sheet_note_single_line`). A one-time migration (`sheet_note_v23`) clears the old default stamp.

### WhatsApp → next
`POST /api/lead/{fp}/whatsapp` with auto-next (`whatsapp_auto_next`, or `next` in the body) skips the customer for today (reason «تم إرسال رسالة واتساب») and returns the next lead in `next`.

### Source = Odoo UTM Source
The sheet's «مصدر العميل» is derived from the lead's **UTM Source** only (`odoo_source_labels`). `find_utm_field()` picks the field once per Odoo `fields_get`: the `odoo_utm_source_field` setting, else a many2one/char/selection field labelled "UTM Source", else a name like `x_utm_source` / `x_studio_utm_source`, else the standard `source_id` (shown on the diagnostics page). Resolution stays deterministic: saved Source Mapping (UTM Source → sheet value) first, then a single identical sheet dropdown value. With `auto_write_source` the workflow writes that one cell as soon as a lead is matched (search, candidate choice, refresh, create, manual link, live-sync change) through the usual safe path (fresh read, row located by company + phone, owner re-check, sync log); Dry Run writes nothing and each (lead, value) is tried once per run.

### Chatter history & live sync
- `get_lead` also returns `chatter` (newest first, up to `chatter_history_limit`): notes, messages, emails and field tracking (`mail.tracking.value`, read best-effort because it is often admin-only), plus planned `activities`. Fields are requested only if `fields_get` reports them, so Odoo 17/18/19 all work. A DOM fallback reads `.o-mail-Message` items when JSON-RPC is unavailable.
- `lead_signature(lead_id)` is a cheap fingerprint: lead `write_date` + message count + latest message `write_date` + activity ids/`write_date`. It returns `None` when the browser has not been started, so polling never launches a browser.
- The dashboard polls `GET /api/lead/{fingerprint}/live?since=<sig>` (or `/api/manual/{id}/live`) every `live_sync_interval_seconds`, paused while the tab is hidden. When the signature changes the server re-reads the lead, updates `lead_cache`, and returns the refreshed payload. Polling errors are returned quietly (`login_required` / `error`) and are not stored in `error_logs`.

### UI
- Tajawal font bundled locally in `app/static/fonts` (SIL OFL), a light/dark theme (`Alt+D`, remembered per browser), and a layout-independent keyboard shortcut registry (`Shortcuts` in `app.js`, using `KeyboardEvent.code` so it also works on the Arabic keyboard layout).

### Remote access (optional, Tailscale + PIN)
`app/remote_access.py`, off unless `REMOTE_ACCESS=true` and `ACCESS_PIN` (6+ digits). `run.py` then listens on 0.0.0.0; the `remote_guard` middleware keeps the PC (loopback, local host names only) unchanged, refuses every non-Tailscale address (100.64.0.0/10, fd7a:115c:a1e0::/48), and requires an HMAC cookie issued after the PIN (rate-limited, 30 days, SameSite=Strict). Shutdown is PC-only. From a phone, calls use `client_dial` (the page opens `tel:` itself) and «Open in Odoo» opens the lead URL in the phone's browser.

### Dry Run & duplicates
- Dry Run is ON by default. It produces the same plan as a real save, including fresh sheet values and the appended notes, but writes nothing and records `dry_run` in the audit.
- Idempotency: the client sends an `idempotency_key` per result panel. Replaying the same key returns the first outcome. Saves are serialized per lead with an asyncio lock. The same lead + same result inside `duplicate_window_seconds` is not written again.

### Error handling
`AgentError(code, message_ar, actions)` is converted to JSON `{error: {code, message, actions}}`, and the UI shows the Arabic message with action buttons (retry / open Odoo / skip / login / settings). Unexpected exceptions return a generic Arabic message. The full stack trace goes to `logs/agent.log`, and the error is stored in `error_logs`.

### Extending
- **Odoo API adapter:** implement `OdooAdapter` in `api_adapter.py` and select it in `container.py`.
- **Voice (V2):** a voice pipeline only pre-fills `ResultIn` (`input_channel="voice"`), and the user confirms it. See the docstring of `call_result_service.py`.
- **DB migrations:** append `(table, column, DDL)` to `MIGRATIONS` in `app/db.py`.
