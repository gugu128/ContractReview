from __future__ import annotations

import json
import tempfile
from pathlib import Path

from app.models.schemas import AuditResult
from app.services.audit_service import AuditService
from app.services.vector_service import VectorService
from app.utils.document_parser import DocumentParser


PRIVATE_RULE_ID = "rule-liquidated-damages-cap"
PRIVATE_QUERY = "违约金"
CONTRACT_TEXT = "本合同约定违约金为总价款的 35%。其他条款保持不变。"
EXPECTED_QUOTE = "本合同约定违约金为总价款的 35%。"


def print_section(title: str) -> None:
    print(f"\n{'=' * 12} {title} {'=' * 12}")


def fail(message: str) -> None:
    raise AssertionError(message)


def main() -> int:
    print_section("1) 规则库注入测试")
    vector_service = VectorService(persist_dir=Path(tempfile.mkdtemp()) / "chroma_rules")
    record = vector_service.upsert_rule(
        rule_id=PRIVATE_RULE_ID,
        audit_item="违约金比例上限",
        audit_point="违约金不得超过总金额的 20%",
        risk_level="高",
        tags=["违约金", "比例", "上限", "风险控制"],
    )
    print(f"已注入规则: {record.rule_id} | {record.audit_item} | {record.risk_level}")

    hits = vector_service.search(PRIVATE_QUERY, top_k=3)
    print(f"检索命中数: {len(hits)}")
    for idx, hit in enumerate(hits, 1):
        print(f"  {idx}. {hit['rule_id']} | {hit['metadata'].get('audit_item', '')}")
    if not any(hit["rule_id"] == PRIVATE_RULE_ID for hit in hits):
        fail("规则库检索未召回目标私有规则")

    print_section("2) 解析与坐标测试")
    parser = DocumentParser()
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(CONTRACT_TEXT)
        temp_path = Path(f.name)

    full_text, chunks = parser.parse(temp_path)
    print(f"全文长度: {len(full_text)}")
    print(f"切片数量: {len(chunks)}")
    matched_chunks = [c for c in chunks if EXPECTED_QUOTE in c.text]
    if not matched_chunks:
        fail("切片中未找到目标风险句子")
    chunk = matched_chunks[0]
    actual_start = full_text.find(EXPECTED_QUOTE)
    actual_end = actual_start + len(EXPECTED_QUOTE)
    print(f"目标句子坐标: start={actual_start}, end={actual_end}")
    print(f"切片坐标: start={chunk.start}, end={chunk.end}")
    if chunk.start > actual_start or chunk.end < actual_end:
        fail("document_parser 未正确覆盖目标句子的字符偏移范围")

    print_section("3) AI 逻辑与 JSON 协议测试")
    audit_service = AuditService(vector_service=vector_service, parser=parser)
    results = audit_service.audit_contract_file(temp_path, rule_set_id="default")
    print(f"审核结果数: {len(results)}")
    if not results:
        fail("AuditService 未返回任何审核结果")

    first = next((item for item in results if item.audit_item == "违约金比例上限"), results[0])
    if not isinstance(first, AuditResult):
        fail("返回结果不是 AuditResult 模型")

    payload = first.model_dump()
    print("首条审核结果 JSON:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    required_fields = ["risk_level", "audit_item", "risk_description", "original_quote", "char_index", "suggestion"]
    for field in required_fields:
        if field not in payload:
            fail(f"缺少字段: {field}")

    if payload["risk_level"] != "高":
        fail(f"风险等级判定不符合预期，实际为: {payload['risk_level']}")

    if "35%" not in payload["original_quote"]:
        fail("original_quote 未命中 35% 风险条款")

    char_index = payload["char_index"]
    if not isinstance(char_index, dict) or "start" not in char_index or "end" not in char_index:
        fail("char_index 结构不正确")

    if char_index["start"] > char_index["end"]:
        fail("char_index start 大于 end")

    print_section("4) 结论")
    print("PASS: 全链路验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
