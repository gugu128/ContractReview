from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from app.models.schemas import AuditResult
from app.services.audit_service import AuditService
from app.services.vector_service import VectorService
from app.utils.document_parser import DocumentParser


SAMPLE_TEXT = """第一章 总则
第一条 本合同由甲乙双方依法签订。
第二条 合同目的在于明确双方权利义务。

第二章 权利义务
第三条 乙方应按期交付成果。
第四条 甲方应按期付款。

第三章 违约责任
第五条 逾期付款的，违约金按合同总额的30%支付。

第四章 其他
第六条 本合同未尽事宜，由双方协商解决。"""


class DebugClient:
    def __init__(self, sleep_seconds: float = 0.1) -> None:
        self.sleep_seconds = sleep_seconds
        self.calls: list[dict[str, Any]] = []

    def chat(self, prompt: str, **kwargs: Any) -> str:
        task_type = kwargs.get("task_type", "analysis")
        self.calls.append({"task_type": task_type, "prompt_size": len(prompt)})
        time.sleep(self.sleep_seconds)
        return json.dumps(
            [
                {
                    "risk_level": "高",
                    "audit_item": "违约金比例上限",
                    "evidence_points": ["违约金为30%"],
                    "original_quote": "第五条 逾期付款的，违约金按合同总额的30%支付。",
                    "char_index": {"start": 0, "end": 0},
                    "conclusion": "违约金比例过高",
                    "suggestion": "建议将违约金比例调整至 20% 及以下。",
                }
            ],
            ensure_ascii=False,
        )


class NoRuleClient:
    def __init__(self, sleep_seconds: float = 0.05) -> None:
        self.sleep_seconds = sleep_seconds
        self.calls: int = 0

    def chat(self, prompt: str, **kwargs: Any) -> str:
        self.calls += 1
        time.sleep(self.sleep_seconds)
        return json.dumps(
            [
                {
                    "risk_level": "中",
                    "audit_item": "工资支付周期",
                    "evidence_points": [],
                    "original_quote": "",
                    "char_index": {"start": 0, "end": 0},
                    "conclusion": "no_rule_found",
                    "suggestion": "",
                }
            ],
            ensure_ascii=False,
        )


def build_temp_contract() -> Path:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
    tmp.write(SAMPLE_TEXT)
    tmp.close()
    return Path(tmp.name)


def main() -> int:
    contract_path = build_temp_contract()
    parser = DocumentParser()
    full_text, chunks = parser.parse(contract_path)
    print(f"[Diag] 合同路径: {contract_path}")
    print(f"[Diag] 全文长度: {len(full_text)}")
    print(f"[Diag] chunks 数量: {len(chunks)}")
    for idx, chunk in enumerate(chunks[:5], start=1):
        print(f"[Diag] chunk{idx}: start={chunk.start}, end={chunk.end}, size={len(chunk.text)}")
        print(f"[Diag] chunk{idx} preview: {chunk.text[:80].replace(chr(10), ' ')}")

    vector_service = VectorService()
    print(f"[Diag] 规则总数: {len(vector_service.list_rules())}")

    print("[Diag] 开始运行真实解析管线（DebugClient 快速模拟 DeepSeek）")
    service = AuditService(client=DebugClient(), vector_service=vector_service, parser=parser)
    started = time.perf_counter()
    results = service.audit_contract_file(contract_path, rule_set_id="default")
    duration = time.perf_counter() - started
    print(f"[Diag] 耗时: {duration:.2f}s")
    print(f"[Diag] 结果数: {len(results)}")
    for idx, item in enumerate(results[:5], start=1):
        payload = item.model_dump() if isinstance(item, AuditResult) else item
        print(f"[Diag] result{idx}: {json.dumps(payload, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
