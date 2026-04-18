from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl

from app.services.webhook_service import WebhookService

router = APIRouter(prefix="/api/v1", tags=["webhook"])
service = WebhookService()


class BotUploadEvent(BaseModel):
    platform: str = "wechat"
    filename: str
    file_url: str
    rule_set_id: str = "default"
    workbench_url: str | None = None


class BotCardResponse(BaseModel):
    title: str
    summary: str
    severity: str
    detail_url: str
    status: str


@router.post("/webhook/bot/upload", response_model=BotCardResponse)
async def bot_upload(event: BotUploadEvent) -> BotCardResponse:
    try:
        return service.handle_upload_event(event)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
