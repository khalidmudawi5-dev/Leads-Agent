"""Reports: JSON for the page and an Excel export."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from app.api.deps import container
from app.container import AppContainer

router = APIRouter(prefix="/api/reports")


@router.get("")
def report(period: str = "week", start: str = "", end: str = "", c: AppContainer = Depends(container)) -> dict:
    return c.reports.public(c.reports.build(period, start, end))


class CustomerReportIn(BaseModel):
    statuses: list[str] = Field(default_factory=list, max_length=40)
    odoo: bool = True
    search_unlinked: bool = True


def _attachment(data: bytes, name: str, media: str) -> Response:
    return Response(data, media_type=media, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@router.get("/customers/options")
async def customer_report_options(c: AppContainer = Depends(container)) -> dict:
    """Follow-up statuses (sheet dropdown + values in the owner's rows) with how many rows have each."""
    return await c.workflow.status_filter()


@router.post("/customers")
async def customer_report(body: CustomerReportIn, c: AppContainer = Depends(container)) -> dict:
    return await c.customer_report.build(body.statuses, body.odoo, body.search_unlinked)


@router.get("/customers/export")
async def customer_report_export(fmt: str = "xlsx", statuses: list[str] = Query(default=[]), odoo: bool = True,
                                 search_unlinked: bool = True, c: AppContainer = Depends(container)) -> Response:
    """Excel / PDF / printable HTML of the report (reuses the report just shown when it is recent)."""
    rep = await c.customer_report.build(statuses, odoo, search_unlinked, fresh=False)
    if fmt == "pdf":
        return _attachment(await c.customer_report.to_pdf(rep), c.customer_report.filename(rep, "pdf"), "application/pdf")
    if fmt == "print":
        return HTMLResponse(c.customer_report.to_html(rep, auto_print=True))
    return _attachment(c.customer_report.to_xlsx(rep), c.customer_report.filename(rep, "xlsx"),
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/export")
def export(period: str = "week", start: str = "", end: str = "", c: AppContainer = Depends(container)) -> Response:
    data, name = c.reports.export_xlsx(period, start, end)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})
