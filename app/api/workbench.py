from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/api/v1", tags=["workbench"])


@router.get("/workbench")
async def workbench_page(token: str | None = None, file: str | None = None, rule_set_id: str | None = None, source: str | None = None) -> RedirectResponse:
    frontend_url = "http://localhost:5173"
    query_parts = []
    if token:
        query_parts.append(f"token={token}")
    if file:
        query_parts.append(f"file={file}")
    if rule_set_id:
        query_parts.append(f"rule_set_id={rule_set_id}")
    if source:
        query_parts.append(f"source={source}")
    suffix = f"?{'&'.join(query_parts)}" if query_parts else ''
    return RedirectResponse(url=f"{frontend_url}/{suffix}", status_code=307)
