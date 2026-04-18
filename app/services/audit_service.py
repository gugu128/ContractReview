from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.core.llm_client import DeepSeekClient
from app.models.schemas import AuditResult, CharIndex
from app.services.vector_service import VectorService
from app.utils.document_parser import DocumentChunk, DocumentParser


class AuditService:
    def __init__(
        self,
        client: DeepSeekClient | None = None,
        vector_service: VectorService | None = None,
        parser: DocumentParser | None = None,
    ) -> None:
        self._client = client or DeepSeekClient()
        self._vector_service = vector_service or VectorService()
        self._parser = parser or DocumentParser()

    def audit_contract_file(self, file_path: str | Path, rule_set_id: str | None = None) -> list[AuditResult]:
        text, chunks = self._parser.parse(file_path)
        results: list[AuditResult] = []
        windows = self._build_sliding_windows(text, chunks)

        for window in windows:
            rules = self._vector_service.search(window["text"], top_k=5)
            if not rules:
                continue
            response = self._audit_chunk(window["text"], rules, source_text=text)
            parsed = self._parse_llm_results(response, source_text=text)
            results.extend(parsed)
            results.extend(self._fallback_rule_based_results(text, window["chunk"], rules))

        if not results:
            global_rules = self._vector_service.search(text, top_k=5)
            if global_rules:
                results.extend(self._fallback_rule_based_results(text, chunks[0] if chunks else type("Chunk", (), {"text": text, "start": 0, "end": len(text)})(), global_rules))

        return self._deduplicate_results(results)

    def _build_sliding_windows(self, text: str, chunks: list[DocumentChunk]) -> list[dict[str, Any]]:
        if not chunks:
            return [{"text": text, "chunk": DocumentChunk(text=text, start=0, end=len(text), source_name="")}] 
        windows: list[dict[str, Any]] = []
        for chunk in chunks:
            windows.append({"text": chunk.text, "chunk": chunk})
        return windows

    def _audit_chunk(self, chunk_text: str, rules: list[dict[str, Any]], *, source_text: str) -> str:
        prompt = self._build_prompt(chunk_text, rules, source_text=source_text)
        return self._client.chat(prompt, system_prompt=self._system_prompt(), task_type="reasoning")

    def _system_prompt(self) -> str:
        return (
            "你是合同智能审核引擎。你只能依据输入的审核规则进行判断，"
            "不得输出通用法律建议，不得编造不存在的条款。"
            "你必须先列出 evidence_points，再给出 conclusion。"
            "如果规则库中没有对应规则，请明确返回 no_rule_found，不要补充任何法律建议。"
            "请严格输出 JSON 数组，每个元素符合以下字段："
            "risk_level, audit_item, evidence_points, original_quote, char_index, conclusion, suggestion。"
            "其中 original_quote 必须来自原文，char_index 必须包含 start 和 end。"
        )

    def _build_prompt(self, chunk_text: str, rules: list[dict[str, Any]], *, source_text: str) -> str:
        return json.dumps(
            {
                "contract_chunk": chunk_text,
                "source_text": source_text,
                "retrieved_rules": rules,
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

    def _parse_llm_results(self, raw_response: str, *, source_text: str) -> list[AuditResult]:
        try:
            payload = json.loads(raw_response)
        except json.JSONDecodeError:
            return []

        items = payload if isinstance(payload, list) else payload.get("items", []) if isinstance(payload, dict) else []
        results: list[AuditResult] = []
        for item in items:
            try:
                quote = str(item["original_quote"])
                if quote not in source_text:
                    continue
                char_index = item.get("char_index", {})
                start = int(char_index.get("start", source_text.find(quote)))
                end = int(char_index.get("end", start + len(quote)))
                if source_text[start:end] != quote:
                    start = source_text.find(quote)
                    end = start + len(quote) if start >= 0 else 0
                    if start < 0:
                        continue
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
            except Exception:
                continue
        return results

    def _fallback_rule_based_results(self, text: str, chunk: Any, rules: list[dict[str, Any]]) -> list[AuditResult]:
        text_lower = text.lower()
        results: list[AuditResult] = []
        for rule in rules:
            content = str(rule.get("content", ""))
            meta = rule.get("metadata", {}) or {}
            audit_item = str(meta.get("audit_item") or "")
            risk_level = str(meta.get("risk_level") or "中")

            if "违约金" in audit_item or "违约金" in content or "违约金" in text_lower:
                percent = self._extract_percentage(text)
                if percent is not None and percent > 20:
                    quote = self._find_liquidated_damage_quote(text) or chunk.text
                    start = max(text.find(quote), 0)
                    end = start + len(quote)
                    results.append(
                        AuditResult(
                            risk_level=risk_level,
                            audit_item=audit_item or "违约金比例上限",
                            risk_description=f"检测到违约金比例为 {percent}%，超过 20% 上限。",
                            original_quote=quote,
                            char_index=CharIndex(start=start, end=end),
                            suggestion="建议将违约金比例调整至总金额的 20% 及以下。",
                        )
                    )
        return results

    def _deduplicate_results(self, results: list[AuditResult]) -> list[AuditResult]:
        seen: set[tuple[str, int, int]] = set()
        deduped: list[AuditResult] = []
        for item in results:
            key = (item.original_quote, item.char_index.start, item.char_index.end)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _find_liquidated_damage_quote(self, text: str) -> str | None:
        match = re.search(r"[^。！？\n]*违约金[^。！？\n]*。", text)
        return match.group(0).strip() if match else None

    def _extract_percentage(self, text: str) -> int | None:
        match = re.search(r"(\d{1,3})\s*%", text)
        return int(match.group(1)) if match else None
