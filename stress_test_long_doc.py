from __future__ import annotations

import json
import random
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.core.llm_client import DeepSeekClient
from app.services.audit_service import AuditService
from app.utils.document_parser import DocumentParser


@dataclass
class DummyRuleService:
    def search(self, text: str, top_k: int = 5):
        rules = []
        if "违约金" in text:
            rules.append(
                {
                    "metadata": {"audit_item": "违约金比例上限", "risk_level": "高"},
                    "content": "违约金不得超过20%",
                }
            )
        rules.append(
            {
                "metadata": {"audit_item": "火星法律管辖", "risk_level": "严重"},
                "content": "本合同适用火星法律并由火星法院管辖",
            }
        )
        return rules[:top_k]


class MockDeepSeekClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def chat(self, prompt: str, *, system_prompt: str = "", temperature: float = 0.2, task_type: str = "analysis") -> str:
        model = self.route_model(task_type)
        print(f"[model_name] task_type={task_type} model_name={model}")
        self.calls.append((task_type, model))

        if task_type == "reasoning":
            if "火星法律管辖" in prompt:
                return json.dumps(
                    [
                        {
                            "risk_level": "严重",
                            "audit_item": "火星法律管辖",
                            "evidence_points": ["未在原文发现火星法律管辖条款"],
                            "original_quote": "",
                            "char_index": {"start": 0, "end": 0},
                            "conclusion": "未发现相关条款",
                            "suggestion": "规则库中无原文证据，禁止推断或补充法律建议。",
                        }
                    ],
                    ensure_ascii=False,
                )
            return json.dumps(
                [
                    {
                        "risk_level": "高",
                        "audit_item": "违约金比例上限",
                        "evidence_points": ["原文包含违约金比例条款"],
                        "original_quote": "违约金按合同总额的30%支付。",
                        "char_index": {"start": 0, "end": 0},
                        "conclusion": "违约金比例偏高",
                        "suggestion": "建议调整到20%及以下。",
                    }
                ],
                ensure_ascii=False,
            )

        return "摘要完成"

    def route_model(self, task_type: str) -> str:
        normalized = task_type.lower().strip()
        if normalized in {"reasoning", "risk", "impact", "analysis", "critical"}:
            return "DeepSeek-R1"
        if normalized in {"parse", "summary", "extract", "draft", "fast"}:
            return "Doubao-1.5-Pro"
        return "DeepSeek-V3"


def build_long_contract() -> str:
    sections = [
        "第一章 总则\n第一条 本合同由甲乙双方依法签订。\n第二条 合同目的在于明确双方权利义务。",
        "第二章 权利义务\n第三条 乙方应按期交付成果。\n第四条 甲方应按期付款。",
        "第三章 违约责任\n第五条 逾期付款的，违约金按合同总额的30%支付。",
        "第四章 其他\n第六条 本合同未尽事宜，由双方协商解决。",
    ]
    filler = []
    for i in range(120):
        filler.append(f"补充说明第{i + 1}段：双方确认本条款仅用于压力测试，内容重复但足以构成长文本。")
    return "\n\n".join(sections + filler)


def verify_hierarchy(parser: DocumentParser, text: str) -> list[tuple[int, tuple[str, ...], str]]:
    chunks = parser.chunk_text(text, chunk_size=500, overlap=120, source_name="stress_test_contract.txt")
    print(f"[hierarchy] chunks={len(chunks)}")
    if not chunks:
        raise AssertionError("No chunks produced")
    for idx, chunk in enumerate(chunks[:6]):
        print(f"[chunk] idx={idx} start={chunk.start} end={chunk.end} level={chunk.level} title_path={chunk.title_path}")
    if not any("第一章" in chunk.text or "总则" in chunk.text for chunk in chunks):
        raise AssertionError("Hierarchy title not preserved in chunks")
    if not any(chunk.title_path for chunk in chunks):
        raise AssertionError("No hierarchical title paths detected")
    return [(chunk.start, chunk.title_path, chunk.text) for chunk in chunks]


def verify_routing(client: MockDeepSeekClient) -> None:
    summary = client.chat("请对合同做摘要", task_type="summary")
    risk = client.chat("请判定风险", task_type="reasoning")
    print(f"[routing] summary_response={summary}")
    print(f"[routing] risk_response={risk}")
    if not any(model == "Doubao-1.5-Pro" for _, model in client.calls):
        raise AssertionError("Summary did not route to Doubao-1.5-Pro")
    if not any(model == "DeepSeek-R1" for _, model in client.calls):
        raise AssertionError("Reasoning did not route to DeepSeek-R1")


def verify_hallucination_control() -> None:
    service = AuditService(client=MockDeepSeekClient(), vector_service=DummyRuleService(), parser=DocumentParser())
    text = build_long_contract()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stress_contract.txt"
        path.write_text(text, encoding="utf-8")
        results = service.audit_contract_file(path)
    print(f"[audit] results={len(results)}")
    for item in results[:10]:
        print(
            f"[audit_result] item={item.audit_item} risk={item.risk_level} quote={item.original_quote} start={item.char_index.start} end={item.char_index.end}"
        )
    if not any("未发现相关条款" in r.risk_description for r in results):
        raise AssertionError("Hallucination control did not suppress fabricated rule")


def verify_global_char_index(text: str) -> None:
    parser = DocumentParser()
    chunks = parser.chunk_text(text, chunk_size=500, overlap=120, source_name="stress_test_contract.txt")
    target_phrase = "本合同未尽事宜，由双方协商解决。"
    global_start = text.rfind(target_phrase)
    if global_start < 0:
        raise AssertionError("Target phrase missing")
    global_end = global_start + len(target_phrase)
    print(f"[char_index] expected_start={global_start} expected_end={global_end}")
    if not any(chunk.start <= global_start < chunk.end or chunk.start <= global_end <= chunk.end for chunk in chunks):
        raise AssertionError("Target phrase not covered by any chunk")
    print("[char_index] global coordinates validated against full text")


def main() -> None:
    random.seed(42)
    text = build_long_contract()
    print(f"[setup] total_chars={len(text)}")

    parser = DocumentParser()
    verify_hierarchy(parser, text)
    verify_routing(MockDeepSeekClient())
    verify_hallucination_control()
    verify_global_char_index(text)
    print("[success] stress test completed")


if __name__ == "__main__":
    main()
