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

    def run_audit(self, chunk_text: str, rules: list[dict[str, Any]], **kwargs: Any) -> list[AuditResult]:
        source_text = str(kwargs.get("source_text") or chunk_text)
        chunk_start = int(kwargs.get("chunk_start") or 0)
        chunk_end = int(kwargs.get("chunk_end") or len(source_text))
        raw_response = kwargs.get("raw_response")
        if raw_response is not None:
            return self.parse_llm_results(str(raw_response), source_text=source_text, chunk_start=chunk_start, chunk_end=chunk_end)
        return self.fallback_rule_based_results(source_text, chunk_text, rules, chunk_start=chunk_start, chunk_end=chunk_end)

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

    def fallback_rule_based_results(self, text: str, chunk: Any, rules: list[dict[str, Any]], *, chunk_start: int = 0, chunk_end: int | None = None) -> list[AuditResult]:
        text_lower = text.lower()
        results: list[AuditResult] = []
        keywords = ["逾期", "赔偿", "解除", "免责", "罚息", "违约金", "转租", "试用期", "社保", "SLA", "知识产权", "责任", "归属", "争议", "管辖", "押金", "加班", "担保", "利息"]
        base_pattern = re.search(r"(甲方|乙方).{0,20}(义务|责任)|(.{0,20})(义务|责任).{0,20}(甲方|乙方)", text)
        base_quote = base_pattern.group(0).strip() if base_pattern else ""
        chunk_text = getattr(chunk, "text", str(chunk) if chunk is not None else "")
        chunk_start = int(getattr(chunk, "start", chunk_start) or chunk_start)
        chunk_end = int(getattr(chunk, "end", chunk_end if chunk_end is not None else len(text)) or len(text))

        for rule in rules:
            content = str(rule.get("content", ""))
            meta = rule.get("metadata", {}) or {}
            audit_item = str(meta.get("audit_item") or "")
            risk_level = str(meta.get("risk_level") or "中")
            suggestion = str(meta.get("suggestion") or "建议结合合同上下文进一步修订相关条款。")

            if any(keyword in (audit_item + content + text_lower) for keyword in keywords):
                quote = self.find_fuzzy_quote(text, audit_item) or self.find_liquidated_damage_quote(text) or chunk_text or text
                start = self.find_fuzzy_quote(text, quote)
                if start is None:
                    start = max(chunk_start, 0)
                end = min(len(text), max(start + len(quote), chunk_end))
                results.append(
                    AuditResult(
                        risk_level=risk_level,
                        audit_item=audit_item or "规则命中",
                        risk_description=f"规则库命中：{audit_item or '相关条款'}。",
                        original_quote=quote,
                        char_index=CharIndex(start=start, end=end),
                        suggestion=suggestion,
                    )
                )

        if base_pattern and base_quote:
            start = self.find_fuzzy_quote(text, base_quote) or max(0, chunk_start)
            end = min(len(text), start + len(base_quote))
            results.append(
                AuditResult(
                    risk_level="中",
                    audit_item="基础合规性检查",
                    risk_description="检测到甲乙双方责任/义务表述，建议检查责任边界、违约后果和免责条件是否完整。",
                    original_quote=base_quote,
                    char_index=CharIndex(start=start, end=end),
                    suggestion="建议补充双方责任边界、违约后果、免责条件及争议解决条款。",
                )
            )

        return results
