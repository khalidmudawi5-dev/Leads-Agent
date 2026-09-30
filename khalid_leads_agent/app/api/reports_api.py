"""Reports: JSON for the page and an Excel export."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.api.deps import container
from app.container import AppContainer

router = APIRouter(prefix="/api/reports")


@router.get("")
def report(period: str = "week", start: str = "", end: str = "", c: AppContainer = Depends(container)) -> dict:
    return c.reports.public(c.reports.build(period, start, end))


@router.get("/export")
def export(period: str = "week", start: str = "", end: str = "", c: AppContainer = Depends(container)) -> Response:
    data, name = c.reports.export_xlsx(period, start, end)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})
