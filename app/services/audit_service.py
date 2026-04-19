from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from pathlib import Path
from typing import Any

from app.core.llm_client import DeepSeekClient
from app.core.skill_manager import SkillManager
from app.models.schemas import AuditResult
from app.services.vector_service import VectorService
from app.utils.document_parser import DocumentChunk, DocumentParser




class AuditService:
    def __init__(
        self,
        client: DeepSeekClient | None = None,
        vector_service: VectorService | None = None,
        parser: DocumentParser | None = None,
        skill_manager: SkillManager | None = None,
    ) -> None:
        self._client = client or DeepSeekClient()
        self._vector_service = vector_service or VectorService()
        self._parser = parser or DocumentParser()
        self._skill_manager = skill_manager or SkillManager()

    def audit_contract_file(self, file_path: str | Path, rule_set_id: str | None = None) -> list[AuditResult]:
        text, chunks = self._parser.parse(file_path)
        results: list[AuditResult] = []
        windows = self._build_sliding_windows(text, chunks)
        skill = self._skill_manager.get("contract_audit")
        if skill:
            print("[Skills] 正在调用执行脚本: executor.py")
        else:
            print("[Skills-Error] 未找到 contract_audit 技能，将使用内置降级流程")

        print(f"[Audit] 开始审查: file_path={file_path}, rule_set_id={rule_set_id}, chunks={len(chunks)}, windows={len(windows)}")
        print(f"[Audit] 片段并行发起中: 共 {len(windows)} 个请求")
        started_at = time.perf_counter()

        def _run_with_thread_pool() -> list[AuditResult]:
            results_local: list[AuditResult] = []
            lock = threading.Lock()
            exceptions: list[Exception] = []

            def _worker(index: int, window: dict[str, Any]) -> None:
                try:
                    batch = asyncio.run(self._audit_window(index=index, window=window, text=text, rule_set_id=rule_set_id, skill=skill))
                    with lock:
                        results_local.extend(batch)
                except Exception as exc:
                    exceptions.append(exc)

            threads = [threading.Thread(target=_worker, args=(index, window), daemon=True) for index, window in enumerate(windows, start=1)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            if exceptions:
                print(f"[Audit] 并发处理出现 {len(exceptions)} 个片段失败，但已继续返回可用结果")
            return results_local

        results = _run_with_thread_pool()
        duration = time.perf_counter() - started_at
        print(f"[Audit] 已完成 {len(windows)} 个片段的并发处理，耗时: {duration:.2f}s")

        if not results:
            global_rules = self._search_rules(text, rule_set_id=rule_set_id, top_k=8)
            print(f"[Audit] 全文规则命中数: {len(global_rules)}")
            if skill and hasattr(skill.executor_module, "ContractAuditExecutor"):
                fallback_results = skill.executor_module.ContractAuditExecutor().run_audit(
                    text,
                    global_rules,
                    source_text=text,
                    chunk_start=0,
                    chunk_end=len(text),
                )
            else:
                fallback_results = self._fallback_rule_based_results(text, chunks[0] if chunks else DocumentChunk(text=text, start=0, end=len(text), source_name=""), global_rules)
            print(f"[Audit] fallback 命中: {len(fallback_results)}")
            results.extend(fallback_results)

        final_results = self._deduplicate_results(results)
        print(f"[Audit] 审查结束: final_results={len(final_results)}")
        return final_results

    async def _audit_window(self, *, index: int, window: dict[str, Any], text: str, rule_set_id: str | None, skill: Any) -> list[AuditResult]:
        rules = self._search_rules(window["text"], rule_set_id=rule_set_id, top_k=8)
        print(f"[Audit] chunk 命中规则数: {len(rules)} (window={index})")

        if not rules:
            fallback_results = self._fallback_rule_based_results(text, window["chunk"], rules)
            print(f"[Audit] fallback 命中: {len(fallback_results)}")
            return fallback_results

        try:
            response = await asyncio.to_thread(self._audit_chunk, window["text"], rules, source_text=text, skill=skill)
            preview = response[:800].replace("\n", " ") if response else ""
            print(f"[Audit] DeepSeek 原始输出: {preview}")
            parsed = self._parse_llm_results(response, source_text=text, chunk=window["chunk"], skill=skill)
            print(f"[Audit] 解析后结果数: {len(parsed)}")
        except Exception as exc:
            print(f"[Audit] DeepSeek 调用失败: {exc}")
            parsed = []

        fallback_results = self._fallback_rule_based_results(text, window["chunk"], rules)
        print(f"[Audit] fallback 命中: {len(fallback_results)}")
        return parsed + fallback_results

    def _build_sliding_windows(self, text: str, chunks: list[DocumentChunk]) -> list[dict[str, Any]]:
        if not chunks:
            return [{"text": text, "chunk": DocumentChunk(text=text, start=0, end=len(text), source_name="")}]
        windows: list[dict[str, Any]] = []
        for chunk in chunks:
            windows.append({"text": chunk.text, "chunk": chunk})
        return windows

    def _audit_chunk(self, chunk_text: str, rules: list[dict[str, Any]], *, source_text: str, skill: Any | None = None) -> str:
        if skill and hasattr(skill.executor_module, "ContractAuditExecutor"):
            executor = skill.executor_module.ContractAuditExecutor()
            prompt = executor.build_prompt(chunk_text=chunk_text, source_text=source_text, retrieved_rules=rules)
            system_prompt = executor.system_prompt()
        else:
            prompt = self._build_prompt(chunk_text, rules, source_text=source_text)
            system_prompt = self._system_prompt()
        return self._client.chat(prompt, system_prompt=system_prompt, task_type="analysis")

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

    def _parse_llm_results(self, raw_response: str, *, source_text: str, chunk: DocumentChunk, skill: Any | None = None) -> list[AuditResult]:
        if skill and hasattr(skill.executor_module, "ContractAuditExecutor"):
            executor = skill.executor_module.ContractAuditExecutor()
            return executor.parse_llm_results(raw_response, source_text=source_text, chunk_start=chunk.start, chunk_end=chunk.end)
        if not skill:
            print("[Skills-Error] 技能未加载，采用内置 JSON 解析器")
        cleaned = self._extract_json_block(raw_response)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            print("[Audit] 丢弃一条结果，原因: json_error")
            print(f"[Audit] 失败的原文引用 (quote): <json_decode_failed>")
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
                match_index = self._find_fuzzy_quote(source_text, quote)
                char_index = item.get("char_index", {})
                if match_index is None:
                    start = max(0, getattr(chunk, "start", 0))
                    end = min(len(source_text), max(start + 50, chunk.end))
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
                normalized_quote = self._normalize_text(quote)
                if start < 0 or end <= start or self._normalize_text(source_text[start:end]) != normalized_quote:
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

    def _fallback_rule_based_results(self, text: str, chunk: Any, rules: list[dict[str, Any]]) -> list[AuditResult]:
        text_lower = text.lower()
        results: list[AuditResult] = []
        keywords = ["逾期", "赔偿", "解除", "免责", "罚息", "违约金", "转租", "试用期", "社保", "SLA", "知识产权", "责任", "归属", "争议", "管辖", "押金", "加班", "担保", "利息"]
        base_pattern = re.search(r"(甲方|乙方).{0,20}(义务|责任)|(.{0,20})(义务|责任).{0,20}(甲方|乙方)", text)
        base_quote = base_pattern.group(0).strip() if base_pattern else ""

        for rule in rules:
            content = str(rule.get("content", ""))
            meta = rule.get("metadata", {}) or {}
            audit_item = str(meta.get("audit_item") or "")
            risk_level = str(meta.get("risk_level") or "中")
            suggestion = str(meta.get("suggestion") or "建议结合合同上下文进一步修订相关条款。")

            if any(keyword in (audit_item + content + text_lower) for keyword in keywords):
                quote = self._find_fuzzy_quote(text, audit_item) or self._find_liquidated_damage_quote(text) or chunk.text
                start = max(self._find_fuzzy_quote(text, quote) or text.find(quote), 0)
                end = start + len(quote)
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
            start = self._find_fuzzy_quote(text, base_quote) or max(0, getattr(chunk, "start", 0))
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

    def _deduplicate_results(self, results: list[AuditResult]) -> list[AuditResult]:
        seen: list[tuple[int, int, str]] = []
        deduped: list[AuditResult] = []
        for item in results:
            start = item.char_index.start
            end = item.char_index.end
            normalized_quote = self._normalize_text(item.original_quote)
            overlap = False
            for seen_start, seen_end, seen_quote in seen:
                if not (end <= seen_start or start >= seen_end):
                    if normalized_quote == seen_quote or abs(start - seen_start) < 20:
                        overlap = True
                        break
            if overlap:
                continue
            seen.append((start, end, normalized_quote))
            deduped.append(item)
        return deduped

    def _extract_json_block(self, raw_response: str) -> str:
        match = re.search(r"```json\s*([\s\S]*?)\s*```", raw_response)
        if match:
            return match.group(1).strip()
        return raw_response.strip()

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"[\s\u3000]+", "", re.sub(r"[，。！？；：、,.!?;:\\-—()（）\[\]{}<>《》\"'“”‘’]", "", text)).lower()

    def _find_fuzzy_quote(self, source_text: str, quote: str) -> int | None:
        if not quote:
            return None
        exact = source_text.find(quote)
        if exact >= 0:
            return exact
        normalized_quote = self._normalize_text(quote)
        if not normalized_quote:
            return None
        normalized_source = self._normalize_text(source_text)
        idx = normalized_source.find(normalized_quote)
        if idx < 0:
            return None

        compact_map: list[int] = []
        for i, ch in enumerate(source_text):
            if self._normalize_text(ch):
                compact_map.append(i)
        if idx >= len(compact_map):
            return None
        return compact_map[idx]

    def _find_liquidated_damage_quote(self, text: str) -> str | None:
        match = re.search(r"[^。！？\n]*违约金[^。！？\n]*。", text)
        return match.group(0).strip() if match else None

    def _extract_percentage(self, text: str) -> int | None:
        match = re.search(r"(\d{1,3})\s*%", text)
        return int(match.group(1)) if match else None

    def _search_rules(self, query: str, *, rule_set_id: str | None = None, top_k: int = 8) -> list[dict[str, Any]]:
        rules = self._vector_service.search(query, top_k=top_k)
        if rule_set_id:
            preferred = [rule for rule in rules if str((rule.get("metadata") or {}).get("category") or "").lower() == str(rule_set_id).lower()]
            if preferred:
                return preferred
            category_queries = {
                "lease": ["租赁", "押金", "转租", "维修", "装修", "续租", "水电", "物业"],
                "labor": ["劳动", "试用期", "工资", "加班", "竞业", "社保", "离职", "服务期"],
                "service": ["服务", "SLA", "知识产权", "数据保密", "验收", "分包", "里程碑", "终止"],
                "loan": ["借款", "利息", "罚息", "担保", "提前还款", "展期", "强制扣款", "用途"],
            }
            for keyword in category_queries.get(str(rule_set_id).lower(), []):
                extra = self._vector_service.search(f"{query} {keyword}", top_k=top_k)
                preferred = [rule for rule in extra if str((rule.get("metadata") or {}).get("category") or "").lower() == str(rule_set_id).lower()]
                if preferred:
                    return preferred
        return rules
