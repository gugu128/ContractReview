from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.models.schemas import AuditResult, ClarificationAnswerRequest, ChallengeRequest, ClarificationRequest, ExplainRequest
from app.services.audit_service import AuditService

router = APIRouter(tags=["audit"])
audit_service = AuditService()


@router.get("/audit/health")
async def audit_health() -> dict[str, str]:
    return {"module": "audit", "status": "ready"}


@router.post("/audit/upload", response_model=list[AuditResult] | ClarificationRequest)
async def upload_audit(file: UploadFile = File(...), rule_set_id: str = Form(default="default")) -> list[AuditResult] | ClarificationRequest:
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

    print(f"[Backend] 上传成功: {file.filename} -> {temp_path.name}")
    print(f"[Backend] 正在审查: rule_set_id={rule_set_id}")
    print("[Backend] DeepSeek 调用中...")

    try:
        results = audit_service.audit_contract_file(temp_path, rule_set_id=rule_set_id)
        if isinstance(results, ClarificationRequest):
            print("[Backend] 审查挂起，等待用户补充信息")
            return results
        print(f"[Backend] 审查完成: {len(results)} 条结果")
        return results
    except Exception as exc:
        print(f"[Backend] 审查失败: {exc}")
        raise HTTPException(status_code=500, detail=f"审查失败：{exc}") from exc


@router.post("/audit/resume")
async def resume_audit(payload: ClarificationAnswerRequest):
    result = audit_service.resume_audit_with_answer(payload.task_id, payload.answer)
    if isinstance(result, ClarificationRequest):
        return result
    return result


@router.post("/audit/explain")
async def explain_audit(payload: ExplainRequest):
    explanation = audit_service.explain_risk(payload.result_id)
    return {"content": explanation}


@router.post("/audit/challenge")
async def challenge_audit(payload: ChallengeRequest):
    result = audit_service.process_user_challenge(payload.message, audit_service._result_lookup.get(payload.result_id))
    return {"content": result}
