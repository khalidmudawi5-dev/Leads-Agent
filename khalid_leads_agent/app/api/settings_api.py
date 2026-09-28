"""Settings, mappings, Google connection, Odoo login and setup wizard API."""
from __future__ import annotations

import asyncio
import os
import signal

from fastapi import APIRouter, Depends, File, Request, UploadFile

from app.api.deps import container
from app.config import COLUMN_LABELS_AR, EMPTY_TOKEN, REQUIRED_COLUMNS
from app.container import AppContainer
from app.errors import AgentError
from app.schemas.api import SearchIn, SourceMappingIn, StatusMappingIn

router = APIRouter(prefix="/api")


@router.get("/settings")
def get_settings(c: AppContainer = Depends(container)) -> dict:
    s = c.settings.get()
    return {
        "settings": s.model_dump(),
        "column_labels": COLUMN_LABELS_AR,
        "required_columns": list(REQUIRED_COLUMNS),
        "empty_token": EMPTY_TOKEN,
        "google": c.auth.status(s.google_auth_mode),
        "paths": {"data": str(c.env.data_path), "logs": str(c.env.logs_path),
                  "browser_profile": s.browser_profile_path or str(c.env.data_path / "browser-profile")},
    }


@router.put("/settings")
def put_settings(body: dict, c: AppContainer = Depends(container)) -> dict:
    before = c.settings.get()
    try:
        s = c.settings.update(body)
    except ValueError as exc:
        raise AgentError("BAD_SETTINGS", "قيمة غير صالحة في الإعدادات.", details={"error": str(exc)[:500]}) from exc
    if (s.google_auth_mode, s.spreadsheet_id, s.sheet_name, s.column_mapping, s.header_row) != (
            before.google_auth_mode, before.spreadsheet_id, before.sheet_name, before.column_mapping, before.header_row):
        c.sheets.reset_client()
        c.queue.loaded = False
    return {"settings": s.model_dump()}


@router.get("/settings/status-mapping")
def get_status_mapping(c: AppContainer = Depends(container)) -> dict:
    return {"items": c.mappings.statuses()}


@router.put("/settings/status-mapping")
def put_status_mapping(body: StatusMappingIn, c: AppContainer = Depends(container)) -> dict:
    c.mappings.save_statuses([i.model_dump() for i in body.items])
    return {"items": c.mappings.statuses()}


@router.get("/settings/source-mapping")
def get_source_mapping(c: AppContainer = Depends(container)) -> dict:
    return {"items": c.mappings.sources()}


@router.post("/settings/source-mapping")
def add_source_mapping(body: SourceMappingIn, c: AppContainer = Depends(container)) -> dict:
    return {"item": c.mappings.save_source(body.odoo_value, body.sheet_value), "items": c.mappings.sources()}


@router.delete("/settings/source-mapping/{mapping_id}")
def delete_source_mapping(mapping_id: int, c: AppContainer = Depends(container)) -> dict:
    c.mappings.delete_source(mapping_id)
    return {"items": c.mappings.sources()}


# ---------------------------------------------------------------- sheet
@router.get("/sheet/tabs")
async def sheet_tabs(c: AppContainer = Depends(container)) -> dict:
    return await asyncio.to_thread(c.sheets.spreadsheet_info)


@router.get("/sheet/headers")
async def sheet_headers(c: AppContainer = Depends(container)) -> dict:
    header = await asyncio.to_thread(c.sheets.headers)
    s = c.settings.get()
    columns, missing = c.sheets.resolve_columns(header, s.column_mapping)
    return {"header": header, "columns": {k: header[i] for k, i in columns.items()}, "missing": missing}


@router.get("/sheet/options/{key}")
async def sheet_options(key: str, c: AppContainer = Depends(container)) -> dict:
    if key not in COLUMN_LABELS_AR:
        raise AgentError("BAD_COLUMN", "عمود غير معروف.")
    return {"key": key, "options": await asyncio.to_thread(c.sheets.dropdown_options, key)}


# --------------------------------------------------------------- google
@router.post("/google/upload/{kind}")
async def google_upload(kind: str, file: UploadFile = File(...), c: AppContainer = Depends(container)) -> dict:
    content = await file.read()
    if len(content) > 200_000:
        raise AgentError("FILE_TOO_LARGE", "الملف كبير جدًا.")
    info = c.auth.save_credentials_file(kind, content)
    if kind == "service_account":
        c.settings.update({"google_auth_mode": "service_account"})
    c.sheets.reset_client()
    return {"ok": True, "info": info, "google": c.auth.status(c.settings.get().google_auth_mode)}


@router.post("/google/connect")
def google_connect(c: AppContainer = Depends(container)) -> dict:
    c.auth.start_oauth_flow()
    c.sheets.reset_client()
    return {"ok": True, "flow": c.auth.flow_state}


@router.get("/google/connect-status")
def google_connect_status(c: AppContainer = Depends(container)) -> dict:
    if c.auth.flow_state.get("done"):
        c.sheets.reset_client()
    return {"flow": c.auth.flow_state, "google": c.auth.status(c.settings.get().google_auth_mode)}


@router.post("/google/disconnect")
def google_disconnect(c: AppContainer = Depends(container)) -> dict:
    c.auth.disconnect()
    c.sheets.reset_client()
    return {"ok": True}


@router.post("/google/test")
async def google_test(c: AppContainer = Depends(container)) -> dict:
    result = await asyncio.to_thread(c.sheets.test_connection)
    c.queue.loaded = False
    return result


# ----------------------------------------------------------------- odoo
@router.post("/odoo/open-login")
async def odoo_open_login(c: AppContainer = Depends(container)) -> dict:
    await c.odoo.adapter.open_login()
    return {"ok": True}


@router.post("/odoo/check-login")
async def odoo_check_login(c: AppContainer = Depends(container)) -> dict:
    st = await c.odoo.check_login()
    return {"logged_in": st.logged_in, "user": st.user_name, "message": st.message, "url": st.url}


@router.post("/odoo/test-search")
async def odoo_test_search(body: SearchIn, c: AppContainer = Depends(container)) -> dict:
    return await c.workflow.manual_search(body.query)


# ---------------------------------------------------------------- setup
@router.post("/setup/complete")
def setup_complete(c: AppContainer = Depends(container)) -> dict:
    s = c.settings.get()
    missing = s.missing_basics()
    if missing:
        raise AgentError("CONFIG_INCOMPLETE", "الإعداد غير مكتمل: " + "، ".join(missing), actions=["open_settings"])
    c.settings.update({"setup_completed": True})
    return {"ok": True}


@router.post("/admin/shutdown")
async def shutdown(request: Request, c: AppContainer = Depends(container)) -> dict:
    """Graceful stop used by 03_stop_agent.bat (closes the Odoo browser first)."""
    server = getattr(request.app.state, "server", None)

    async def _later() -> None:
        await asyncio.sleep(0.3)
        try:
            await c.odoo.adapter.close()
        finally:
            if server is not None:
                server.should_exit = True
            else:
                os.kill(os.getpid(), signal.SIGINT)

    request.app.state.shutdown_task = asyncio.get_running_loop().create_task(_later())
    return {"ok": True}
