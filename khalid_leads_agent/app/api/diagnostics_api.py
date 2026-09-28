"""Selector diagnostics for adjusting ``odoo_selectors.py`` when Odoo's UI changes."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import container
from app.container import AppContainer

router = APIRouter(prefix="/api/diagnostics")


@router.get("")
async def run(c: AppContainer = Depends(container)) -> dict:
    return await c.odoo.adapter.diagnostics()


@router.post("/screenshot")
async def screenshot(c: AppContainer = Depends(container)) -> dict:
    return {"path": await c.odoo.adapter.capture_screenshot("diagnostics")}


@router.post("/dom")
async def dom(c: AppContainer = Depends(container)) -> dict:
    return {"path": await c.odoo.adapter.capture_dom("odoo-dom")}
