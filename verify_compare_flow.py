from __future__ import annotations

import json
import tempfile
from pathlib import Path

from app.models.schemas import CompareResult
from app.services.compare_service import CompareService

BASE_TEXT = "甲方应在三日内完成付款。逾期需承担违约责任。合同金额为100万元。"
CURRENT_TEXT = "甲方应在三个工作日内完成付款。逾期需承担违约责任。合同金额为120万元。"


def print_section(title: str) -> None:
    print(f"\n{'=' * 12} {title} {'=' * 12}")


def fail(message: str) -> None:
    raise AssertionError(message)


def main() -> int:
    print_section("1) 文本准备")
    print("Base:", BASE_TEXT)
    print("Current:", CURRENT_TEXT)

    print_section("2) 比对执行")
    service = CompareService()
    results = service.compare_texts(BASE_TEXT, CURRENT_TEXT)
    print(f"差异条数: {len(results)}")
    if not results:
        fail("未识别出任何差异")

    serialized = [item.model_dump() if isinstance(item, CompareResult) else item for item in results]
    print("比对结果 JSON:")
    print(json.dumps(serialized, ensure_ascii=False, indent=2))

    if not any(r["change_type"] == "修改" for r in serialized):
        fail("未识别出修改类型差异")

    if not any("三个工作日" in r["current_content"] or "120万元" in r["current_content"] for r in serialized):
        fail("未捕捉到核心语义变更")

    for r in serialized:
        if "base_index" not in r or "current_index" not in r:
            fail("缺少坐标字段")
        if not isinstance(r["base_index"], dict) or not isinstance(r["current_index"], dict):
            fail("坐标结构不正确")

    print_section("3) 文件接口可用性测试")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fb:
        fb.write(BASE_TEXT)
        base_path = Path(fb.name)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fc:
        fc.write(CURRENT_TEXT)
        current_path = Path(fc.name)

    file_results = service.compare_files(base_path, current_path)
    print(f"文件比对差异条数: {len(file_results)}")
    if not file_results:
        fail("compare_files 未返回结果")

    print_section("4) 结论")
    print("PASS: 合同智能比对引擎验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
