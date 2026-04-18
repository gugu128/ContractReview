from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.models.schemas import AuditResult


@dataclass
class AuditHistoryService:
    storage_path: Path = Path("data/audit_history.jsonl")

    def save(self, filename: str, results: list[AuditResult]) -> str:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        record_id = str(uuid4())
        payload = {
            "record_id": record_id,
            "filename": filename,
            "results": [item.model_dump() for item in results],
        }
        with self.storage_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return record_id

    def list_recent(self, limit: int = 20) -> list[dict]:
        if not self.storage_path.exists():
            return []
        lines = self.storage_path.read_text(encoding="utf-8").splitlines()
        records = [json.loads(line) for line in lines if line.strip()]
        return records[-limit:]
