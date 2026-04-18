from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import urlencode

from app.models.schemas import BotCardResponse, BotUploadEvent


@dataclass
class WebhookService:
    def _build_token(self, event: BotUploadEvent) -> str:
        seed = f"{event.platform}:{event.filename}:{event.file_url}:{event.rule_set_id}"
        return sha256(seed.encode("utf-8")).hexdigest()[:24]

    def handle_upload_event(self, event: BotUploadEvent) -> BotCardResponse:
        base_url = event.workbench_url or "http://localhost:5173"
        token = self._build_token(event)
        query = urlencode({"file": event.filename, "rule_set_id": event.rule_set_id, "token": token, "source": "im"})
        detail_url = f"{base_url}/?{query}"
        return BotCardResponse(
            title="极速风险体检卡片",
            summary=f"已收到 {event.filename}，点击卡片即可打开 Web 端审查结果。",
            severity="中",
            detail_url=detail_url,
            status="success",
        )
