# Test Report — Khalid Leads Agent 1.0.0

**Date:** 2026-09-28
**Result:** ✅ **81 passed, 0 failed**. The run used a clean virtual environment installed only from `requirements.txt`.

## Environment

| Item | Value |
|---|---|
| Python | 3.12.3 |
| FastAPI / Uvicorn | 0.141.1 / 0.54.0 |
| SQLAlchemy | 2.1.1 |
| Playwright | 1.63.0, with headless Chromium for the browser tests |
| Google libs | google-api-python-client 2.200.0, google-auth 2.58.1, google-auth-oauthlib 1.4.1 |
| pytest | 9.1.1 |
| Lint | `ruff check` (E, F, W, B, UP): all checks passed |

The tests use **only mocks and fictional data**:
- `InMemorySheetsClient` stands in for Google Sheets. It records every write, so tests can assert that no other cell changed.
- `MockOdooAdapter` stands in for Odoo.
- A local **fake Odoo server** (`tests/fake_odoo/server.py`) serves Odoo 17/18-like pages and `/web/dataset/call_kw`. The real Playwright adapter is exercised against it.

No production Google Sheet or Odoo data is used.

## Results by area

| File | Tests | Requirement covered |
|---|---|---|
| `test_phone.py` | 15 | Phone normalization: `0561234567`, `966561234567`, `+966561234567`, `+966 56 123 4567`, `05 6123 4567`, `00966…`, Arabic-Indic digits, multiple numbers in one cell |
| `test_mappings.py` | 6 | Status mapping (defaults, update, unmapped blocked); source mapping (normalized keys, specific-first priority, no guessing) |
| `test_notes.py` | 3 | Notes append format `[dd/mm/yyyy HH:MM - خالد]`; old text preserved; Append Notes option |
| `test_sheet_safety.py` | 13 | **Safe row update**: columns located by header text; only changed cells written; formulas and other rows untouched; row moved is re-found by company + phone; **owner changed → STOP**, also after the row moved; ambiguous or deleted row blocked; dry run writes nothing but is logged; dropdown validation; unchanged values not rewritten; write failure logged |
| `test_queue_and_session.py` | 6 | **Lead ordering** (sheet order, reverse, oldest/newest by date column); configurable Pending Status Values including `(فارغ)`; skip/snooze; **resume session** after restart, by fingerprint (not row number); new session; idempotent DB init |
| `test_matching.py` | 5 | Match priority phone → mobile → company exact → partial; multiple → user choice; partial never auto-opened; never creates leads |
| `test_results.py` | 17 | Real save (Odoo note + sheet + next lead); **Dry Run** preview with no writes; Dry Run ON by default; **duplicate protection** (same key, same lead + result within window, parallel double click); follow-up Activity success and failure (warning, save continues); owner changed → sheet blocked but Odoo note kept; **retry** of failed steps only, with no duplicate notes; manual mode never updates the sheet; manual link only on an unambiguous phone; source mapping saved from the result panel; value outside the dropdown blocked; preview writes nothing |
| `test_api.py` | 9 | FastAPI startup, all HTML routes and static files, setup-wizard redirect, CSRF header / same-origin guard, trusted host, full dry-run flow over HTTP, audit log systems, Arabic errors without stack traces, call-button-missing error actions, settings/mappings API |
| `test_browser_adapter.py` | 6 | **Real Playwright adapter** against the fake Odoo: login required detection + manual login; search by phone and name; open lead; DOM extraction (labels / field names); click Odoo's own `tel:` Call link; **Log note via the UI** (subtype `mail.mt_note`, never Send message) with idempotent re-post; RPC-first note; Activity; diagnostics; DOM snapshot; screenshot `odoo-call-button-not-found-*.png`; relaunch after the user closes the browser; Windows handler call mode |
| `test_e2e_browser.py` | 1 | Complete workflow over HTTP with the real browser adapter: login required, then login, match, Source/Medium read, call, FOLLOW_UP save (note + activity + sheet update with appended notes, formula intact, other user's row untouched), next lead and stats |

## Final validation checklist

| Check | Status |
|---|---|
| Python imports / `compileall` | ✅ |
| FastAPI startup (`run.py`, real mode, first run without credentials: redirect to `/setup`, Arabic messages, no crash) | ✅ |
| SQLite init and migrations (run twice, idempotent) | ✅ |
| HTML routes (`/`, `/setup`, `/settings`, `/history`, `/skipped`, `/errors`, `/diagnostics`) | ✅ |
| Static files (CSS / JS / favicon) | ✅ |
| Dry Run (default ON, preview, no external writes) | ✅ |
| Mocks (Google + Odoo + fake Odoo server) | ✅ |
| Graceful stop endpoint used by `03_stop_agent.bat` (PID file removed) | ✅ |
| UI in headless Chromium at 1920×1080, driven through the dashboard flow (match, call timer, result panel, Dry Run preview, countdown, next lead, multiple-candidates dialog, not-found panel, manual search) and the 9-step setup wizard: **0 JavaScript errors** | ✅ |

## Issues found and fixed during testing

1. The Phone/Mobile columns in the candidates table were misaligned, because `.ltr { display:inline-block }` was applied to `<td>`. Fixed with `td.ltr { display: table-cell }`.
2. There was a missing favicon (404 in the console). Added `/static/favicon.svg`.
3. Previews (the wizard Dry Run Test and the "معاينة" button) were written to the audit log. Now only real Dry Run saves are audited.
4. Two test scenarios had wrong expectations (row index after insertion; ambiguous duplicate setup). The tests were corrected; the product code was already right.
5. A test helper called Playwright from the wrong event loop. Browser calls now always go through the adapter's dedicated browser thread, as in production.

## Not testable in this environment (requires your machine)

- Real Google OAuth consent and a real Google Sheet: the API calls use the official client, and the logic is covered by mocks.
- A real Odoo 18/19 instance: the selectors follow Odoo 17/18 DOM conventions, with fallbacks. If any differ, use the Diagnostics page and `odoo_selectors.py`.
- Microsoft Phone Link / the Windows `tel:` handler, and running the `.bat` files themselves (written for Windows with CRLF line endings).
