from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.models.schemas import AuditResult
from app.services.audit_service import AuditService

router = APIRouter(tags=["audit"])
audit_service = AuditService()


@router.get("/audit/health")
async def audit_health() -> dict[str, str]:
    return {"module": "audit", "status": "ready"}


@router.post("/audit/upload", response_model=list[AuditResult])
async def upload_audit(file: UploadFile = File(...), rule_set_id: str = Form(default="default")) -> list[AuditResult]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    suffix = file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else ""
    if suffix not in {"pdf", "docx", "doc", "txt"}:
        raise HTTPException(status_code=400, detail="仅支持 PDF、Word 和文本文件")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="上传文件为空")

    temp_dir = Path("data/uploads")
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"{uuid4().hex}_{file.filename}"
    temp_path.write_bytes(data)

    try:
        results = audit_service.audit_contract_file(temp_path, rule_set_id=rule_set_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"审查失败：{exc}") from exc
    return results
