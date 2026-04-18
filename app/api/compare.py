from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.models.schemas import CompareResult
from app.services.compare_service import CompareService

router = APIRouter(tags=["compare"])
compare_service = CompareService()


@router.post("/compare/files", response_model=list[CompareResult])
async def compare_files(base_file: UploadFile = File(...), current_file: UploadFile = File(...)) -> list[CompareResult]:
    if not base_file.filename or not current_file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    temp_dir = Path("data/uploads")
    temp_dir.mkdir(parents=True, exist_ok=True)

    base_path = temp_dir / f"base_{base_file.filename}"
    current_path = temp_dir / f"current_{current_file.filename}"
    base_path.write_bytes(await base_file.read())
    current_path.write_bytes(await current_file.read())

    return compare_service.compare_files(base_path, current_path)
