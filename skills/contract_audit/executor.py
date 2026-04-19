from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.models.schemas import AuditResult, CharIndex


@dataclass
class ParsedLLMResult:
    payload: dict[str, Any]
    original_quote: str
    conclusion: str


class ContractAuditExecutor:
    def system_prompt(self) -> str:
        return (
            "你是合同智能审核引擎。你只能依据输入的审核规则进行判断，"
            "不得输出通用法律建议，不得编造不存在的条款。"
            "你必须先列出 evidence_points，再给出 conclusion。"
            "如果规则库中没有对应规则，请明确返回 no_rule_found，不要补充任何法律建议。"
            "请严格输出 JSON 数组，每个元素符合以下字段："
            "risk_level, audit_item, evidence_points, original_quote, char_index, conclusion, suggestion。"
            "其中 original_quote 必须来自原文，char_index 必须包含 start 和 end。"
        )

    def build_prompt(self, *, chunk_text: str, source_text: str, retrieved_rules: list[dict[str, Any]]) -> str:
        return json.dumps(
            {
                "contract_chunk": chunk_text,
                "source_text": source_text,
                "retrieved_rules": retrieved_rules,
                "self_check": [
                    "original_quote 是否能在 source_text 中原样找到",
                    "char_index 是否覆盖 original_quote 的真实位置",
                    "如果找不到证据，输出 no_rule_found",
                ],
                "output_requirements": {"strict_json": True, "no_hallucination": True},
            },
            ensure_ascii=False,
            indent=2,
        )

    def extract_json_block(self, raw_response: str) -> str:
        match = re.search(r"```json\s*([\s\S]*?)\s*```", raw_response)
        if match:
            return match.group(1).strip()
        return raw_response.strip()

    def normalize_text(self, text: str) -> str:
        return re.sub(r"[\s\u3000]+", "", re.sub(r"[，。！？；：、,.!?;:\\-—()（）\[\]{}<>《》\"'“”‘’]", "", text)).lower()

    def find_fuzzy_quote(self, source_text: str, quote: str) -> int | None:
        if not quote:
            return None
        exact = source_text.find(quote)
        if exact >= 0:
            return exact
        normalized_quote = self.normalize_text(quote)
        if not normalized_quote:
            return None
        normalized_source = self.normalize_text(source_text)
        idx = normalized_source.find(normalized_quote)
        if idx < 0:
            return None

        compact_map: list[int] = []
        for i, ch in enumerate(source_text):
            if self.normalize_text(ch):
                compact_map.append(i)
        if idx >= len(compact_map):
            return None
        return compact_map[idx]

    def parse_llm_results(self, raw_response: str, *, source_text: str, chunk_start: int, chunk_end: int) -> list[AuditResult]:
        cleaned = self.extract_json_block(raw_response)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            print("[Audit] 丢弃一条结果，原因: json_error")
            print("[Audit] 失败的原文引用 (quote): <json_decode_failed>")
            print(f"[Audit] 失败的 JSON 片段: {cleaned[:500]}")
            return []

        items = payload if isinstance(payload, list) else payload.get("items", []) if isinstance(payload, dict) else []
        results: list[AuditResult] = []
        for item in items:
            try:
                item_json = json.dumps(item, ensure_ascii=False)
                conclusion = str(item.get("conclusion") or item.get("risk_description") or "")
                if conclusion.strip().lower() == "no_rule_found":
                    continue

                quote = str(item["original_quote"])
                match_index = self.find_fuzzy_quote(source_text, quote)
                char_index = item.get("char_index", {})
                if match_index is None:
                    start = max(0, chunk_start)
                    end = min(len(source_text), max(start + 50, chunk_end))
                    print("[Audit] 丢弃一条结果，原因: quote_mismatch")
                    print(f"[Audit] 失败的原文引用 (quote): {quote}")
                    print(f"[Audit] 失败的 JSON 片段: {item_json}")
                    results.append(
                        AuditResult(
                            risk_level=item["risk_level"],
                            audit_item=item["audit_item"],
                            risk_description=conclusion,
                            original_quote=quote,
                            char_index=CharIndex(start=start, end=end),
                            suggestion=item["suggestion"],
                        )
                    )
                    continue

                start = int(char_index.get("start", match_index))
                end = int(char_index.get("end", start + len(quote)))
                normalized_quote = self.normalize_text(quote)
                if start < 0 or end <= start or self.normalize_text(source_text[start:end]) != normalized_quote:
                    start = match_index
                    end = start + len(quote)

                results.append(
                    AuditResult(
                        risk_level=item["risk_level"],
                        audit_item=item["audit_item"],
                        risk_description=str(item.get("conclusion") or item.get("risk_description") or ""),
                        original_quote=quote,
                        char_index=CharIndex(start=start, end=end),
                        suggestion=item["suggestion"],
                    )
                )
            except KeyError as exc:
                item_json = json.dumps(item, ensure_ascii=False)
                print("[Audit] 丢弃一条结果，原因: missing_field")
                print(f"[Audit] 失败的原文引用 (quote): {item.get('original_quote', '<missing>')}")
                print(f"[Audit] 失败的 JSON 片段: {item_json}")
                print(f"[Audit] 缺失字段: {exc}")
            except Exception as exc:
                item_json = json.dumps(item, ensure_ascii=False)
                print(f"[Audit] 丢弃一条结果，原因: {type(exc).__name__}")
                print(f"[Audit] 失败的原文引用 (quote): {item.get('original_quote', '<missing>')}")
                print(f"[Audit] 失败的 JSON 片段: {item_json}")
        return results
