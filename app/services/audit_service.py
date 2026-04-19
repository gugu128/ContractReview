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
from app.core.tools import DEFAULT_LEGAL_TOOLS
from app.models.schemas import AuditResult, CharIndex, ClarificationRequest
from app.services.audit_history_service import AuditHistoryService
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
        self._history_service = AuditHistoryService()
        self._result_lookup: dict[str, AuditResult] = {}
        self._audit_context: dict[str, Any] = {}
        self._context_documents: list[dict[str, Any]] = []
        self._pending_audits: dict[str, dict[str, Any]] = {}

    def _generate_audit_plan(self, text: str) -> dict[str, Any] | ClarificationRequest:
        summary = text[:2000]
        prompt = (
            "请基于以下合同摘要生成一个合同审计计划。\n"
            "在开始审计前，你必须先判断：我是否拥有足够的信息来开始高精度审计？\n"
            "如果合同类型模糊，或者缺少关键背景（例如不知道该按甲方还是乙方视角审），请不要继续生成审计计划，直接输出 clarification。\n"
            "必须重点识别这些高频追问场景：劳务/劳动混淆、双向责任但未指定立场、多个版本行业标准导致审计严格程度不明确。\n"
            "请只输出 JSON，不要输出额外解释。\n"
            "输出格式二选一：\n"
            "1) 足够信息时，输出 {\"ready\": true, \"contract_type\": ..., \"priority_focus\": [...], \"suggested_rule_keywords\": [...], \"assumed_party_view\": ..., \"strictness\": ...}\n"
            "2) 信息不足时，输出 {\"ready\": false, \"question\": ..., \"options\": [...], \"context_fragment\": ...}\n\n"
            f"合同摘要如下：\n{summary}"
        )
        plan: dict[str, Any] = {}
        try:
            response = self._client.chat(prompt, system_prompt="你是合同类型识别和审计规划助手。", task_type="reasoning")
            raw = response.strip() if isinstance(response, str) else str(response).strip()
            cleaned = self._extract_json_block(raw)
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                plan = parsed
            else:
                raise ValueError("audit plan must be a JSON object")
        except Exception as exc:
            print(f"[Agent-Plan] 审计计划生成失败，使用默认计划: {exc}")

        if plan.get("ready") is False:
            clarification = ClarificationRequest(
                question=str(plan.get("question") or "请补充合同的关键背景信息，以便继续高精度审计。"),
                options=plan.get("options") if isinstance(plan.get("options"), list) else None,
                context_fragment=str(plan.get("context_fragment") or summary[:300]) or None,
            )
            print(f"[Agent-Clarify] 检测到关键背景缺失，已向用户发起追问：{clarification.question}")
            return clarification

        contract_type = str(plan.get("contract_type") or "未知")
        priority_focus = plan.get("priority_focus") or []
        suggested_rule_keywords = plan.get("suggested_rule_keywords") or []
        if not isinstance(priority_focus, list):
            priority_focus = [str(priority_focus)]
        if not isinstance(suggested_rule_keywords, list):
            suggested_rule_keywords = [str(suggested_rule_keywords)]

        normalized_plan = {
            "ready": True,
            "contract_type": contract_type,
            "priority_focus": [str(item) for item in priority_focus if str(item).strip()],
            "suggested_rule_keywords": [str(item) for item in suggested_rule_keywords if str(item).strip()],
            "assumed_party_view": str(plan.get("assumed_party_view") or ""),
            "strictness": str(plan.get("strictness") or "standard"),
        }
        print(f"[Agent-Plan] 识别到合同类型为: {normalized_plan['contract_type']}, 审计重点: {normalized_plan['priority_focus']}")
        return normalized_plan

    def audit_contract_file(self, file_path: str | Path, rule_set_id: str | None = None, background_files: list[str | Path] | None = None) -> list[AuditResult] | ClarificationRequest:
        text, chunks = self._parser.parse(file_path)
        audit_plan = self._generate_audit_plan(text)
        self._context_documents = self._load_context_documents(background_files or [])
        if isinstance(audit_plan, ClarificationRequest):
            task_id = str(time.time_ns())
            audit_plan.task_id = task_id
            self._pending_audits[task_id] = {
                "text": text,
                "chunks": chunks,
                "rule_set_id": rule_set_id,
                "background_files": background_files or [],
                "audit_plan": None,
                "clarification": audit_plan.model_dump(),
                "resume_context": {},
            }
            return audit_plan
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
                    batch = asyncio.run(self._audit_window(index=index, window=window, text=text, rule_set_id=rule_set_id, skill=skill, audit_plan=audit_plan, context_documents=self._context_documents))
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

        strategic_results = self._strategic_gap_analysis(text, audit_plan, results, rule_set_id=rule_set_id, skill=skill)
        if strategic_results:
            results.extend(strategic_results)

        results = self._resolve_global_conflicts(text, results, skill=skill, audit_plan=audit_plan)

        if not results:
            global_rules = self._search_rules(text, rule_set_id=rule_set_id, top_k=8, audit_plan=audit_plan)
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
            fallback_results = [item for item in fallback_results if not (item.audit_item == "基础合规性检查" and "火星" in item.risk_description)]
            if not fallback_results:
                fallback_results = [
                    AuditResult(
                        risk_level="低",
                        audit_item="未发现相关条款",
                        risk_description="未发现相关条款",
                        original_quote=text[:40],
                        char_index=CharIndex(start=0, end=min(len(text), 40)),
                        suggestion="当前文本未触发明确规则命中，建议结合背景文件继续审查。",
                    )
                ]
            print(f"[Audit] fallback 命中: {len(fallback_results)}")
            results.extend(fallback_results)

        summary_result = self._build_summary_result(text, results, skill=skill)
        if summary_result is not None and len(results) > 1:
            results.insert(0, summary_result)

        final_results = self._deduplicate_results(results)
        print(f"[Audit] 审查结束: final_results={len(final_results)}")
        return final_results

    async def _audit_window(self, *, index: int, window: dict[str, Any], text: str, rule_set_id: str | None, skill: Any, audit_plan: dict[str, Any] | None = None, context_documents: list[dict[str, Any]] | None = None) -> list[AuditResult]:
        rules = self._search_rules(window["text"], rule_set_id=rule_set_id, top_k=8, audit_plan=audit_plan)
        context_documents = context_documents or []
        conflict_notes = self._detect_context_conflicts(window["text"], context_documents)
        if conflict_notes:
            print(f"[Agent-Context] {conflict_notes[0]}")
        print(f"[Audit] chunk 命中规则数: {len(rules)} (window={index})")
        if self._needs_clarification_for_window(window["text"], rules, audit_plan=audit_plan):
            clarification = self._build_clarification_for_window(window["text"], audit_plan=audit_plan)
            print(f"[Agent-Clarify] 检测到关键背景缺失，已向用户发起追问：{clarification.question}")
            raise RuntimeError(f"NEEDS_CLARIFICATION::{json.dumps(clarification.model_dump(), ensure_ascii=False)}")

        if not rules:
            fallback_results = self._fallback_rule_based_results(text, window["chunk"], rules)
            print(f"[Audit] fallback 命中: {len(fallback_results)}")
            return fallback_results

        final_results: list[AuditResult] = []
        latest_response = ""
        feedback_messages: list[str] = []
        for attempt in range(2):
            try:
                if attempt == 0:
                    latest_response = await asyncio.to_thread(self._audit_chunk, window["text"], rules, source_text=text, skill=skill, audit_plan=audit_plan, context_documents=context_documents, window=window, conflict_notes=conflict_notes)
                else:
                    correction_prompt = (
                        "你上一轮输出中存在引用不准或幻觉，请只修正以下问题后重新输出 JSON。\n"
                        + "\n".join(feedback_messages)
                        + "\n请保持字段结构不变，只输出修正后的结果。"
                    )
                    latest_response = await asyncio.to_thread(
                        self._client.chat,
                        correction_prompt,
                        system_prompt="你是合同智能审核引擎，请基于修正反馈重新输出。",
                        task_type="analysis",
                    )
                preview = latest_response[:800].replace("\n", " ") if latest_response else ""
                print(f"[Audit] DeepSeek 原始输出: {preview}")
                thinking = self._extract_thinking(latest_response)
                if "[NEEDS_CLARIFICATION]" in thinking:
                    clarification = self._build_clarification_for_window(window["text"], audit_plan=audit_plan)
                    print(f"[Agent-Clarify] 检测到关键背景缺失，已向用户发起追问：{clarification.question}")
                    self._pending_audits[str(time.time_ns())] = {
                        "text": text,
                        "window": window,
                        "rule_set_id": rule_set_id,
                        "audit_plan": audit_plan or {},
                        "context_documents": context_documents,
                        "clarification": clarification.model_dump(),
                        "resume_window_index": index,
                    }
                    return []
                if "<thinking>" in latest_response.lower() and any(term in latest_response.lower() for term in ["信息不足", "需要上下文", "查阅上下文"]):
                    window = self._expand_window(window, text, padding=500)
                    print(f"[Agent-Reflection] 第 {index} 个片段信息不足，扩大上下文后重试")
                    continue
                parsed = self._parse_llm_results(latest_response, source_text=text, chunk=window["chunk"], skill=skill)
                thinking = self._extract_thinking(latest_response)
                if context_documents and hasattr(skill.executor_module, "ContractAuditExecutor"):
                    tool_results = skill.executor_module.ContractAuditExecutor().run_tool_checks(latest_response)
                    if tool_results:
                        print(f"[Agent-External] 工具校验完成: {len(tool_results)} 项")
                print(f"[Audit] 解析后结果数: {len(parsed)}")

                bad_items: list[str] = []
                thinking = self._extract_thinking(latest_response)
                for item in parsed:
                    quote = item.original_quote
                    match_index = self._find_fuzzy_quote(text, quote)
                    if match_index is None:
                        bad_items.append(quote)
                    else:
                        item.char_index = CharIndex(start=match_index, end=match_index + len(quote))
                        if hasattr(skill.executor_module, "ContractAuditExecutor"):
                            item.suggested_revision = skill.executor_module.ContractAuditExecutor().build_suggested_revision(
                                item.original_quote, item.audit_item, item.suggestion
                            )
                if not bad_items:
                    final_results = parsed
                    for item in parsed:
                        self._record_result_context(item, thinking=thinking, audit_plan=audit_plan, context_documents=context_documents, conflict_notes=conflict_notes)
                    break

                print(f"[Agent-Reflection] 发现第 {index} 个片段有 {len(bad_items)} 处引用不准，正在发起修正...")
                feedback_messages = [f'你引用的条款“{quote}”在原文中不存在或无法精确定位，请修正。' for quote in bad_items]
                final_results = parsed
                for item in parsed:
                    self._record_result_context(item, thinking=thinking, audit_plan=audit_plan, context_documents=context_documents, conflict_notes=conflict_notes)
            except Exception as exc:
                message = str(exc)
                if "NEEDS_CLARIFICATION::" in message:
                    payload = message.split("NEEDS_CLARIFICATION::", 1)[1]
                    clarification_payload = json.loads(payload)
                    self._pending_audits[str(time.time_ns())] = {
                        "text": text,
                        "window": window,
                        "rule_set_id": rule_set_id,
                        "audit_plan": audit_plan or {},
                        "context_documents": context_documents,
                        "clarification": clarification_payload,
                        "resume_window_index": index,
                    }
                    return []
                print(f"[Audit] DeepSeek 调用失败: {exc}")
                final_results = []
                break

        fallback_results = self._fallback_rule_based_results(text, window["chunk"], rules)
        print(f"[Audit] fallback 命中: {len(fallback_results)}")
        return final_results + fallback_results

    def _build_sliding_windows(self, text: str, chunks: list[DocumentChunk]) -> list[dict[str, Any]]:
        if not chunks:
            return [{"text": text, "chunk": DocumentChunk(text=text, start=0, end=len(text), source_name="")}]
        windows: list[dict[str, Any]] = []
        for chunk in chunks:
            windows.append({"text": chunk.text, "chunk": chunk})
        return windows

    def explain_risk(self, result_id: str) -> str:
        result = self._result_lookup.get(result_id)
        context = self._audit_context.get(result_id, {})
        if not result:
            return "未找到对应风险项。"
        thinking = str(context.get("thinking") or "")
        audit_plan = context.get("audit_plan") or {}
        prompt = (
            "请基于以下审计计划、推理过程和风险项，解释为什么需要这样修改，"
            "并说明如果不修改可能带来的具体法律后果。"
            f"\n审计计划: {json.dumps(audit_plan, ensure_ascii=False)}"
            f"\n推理过程: {thinking}"
            f"\n风险项: {json.dumps(result.model_dump(), ensure_ascii=False)}"
            "\n请输出简明、具体、可直接给用户看的解释。"
        )
        try:
            response = self._client.chat(prompt, system_prompt="你是合同风险解释助手。", task_type="reasoning")
            return response if isinstance(response, str) else str(response)
        except Exception as exc:
            return f"风险解释生成失败: {exc}"

    def resume_audit_with_answer(self, task_id: str, answer: str) -> list[AuditResult] | ClarificationRequest:
        pending = self._pending_audits.get(task_id)
        if not pending:
            return ClarificationRequest(question="未找到可恢复的挂起审计任务，请重新发起审计。", options=None, context_fragment=None, task_id=None)
        print("[Agent-Resume] 收到用户回答，正在更新审计策略并继续...")
        audit_plan = dict(pending.get("audit_plan") or {})
        audit_plan["user_answer"] = answer
        audit_plan["ready"] = True
        text = str(pending.get("text") or "")
        chunks = pending.get("chunks") or []
        rule_set_id = pending.get("rule_set_id")
        background_files = pending.get("background_files") or []
        self._context_documents = self._load_context_documents(background_files)
        windows = self._build_sliding_windows(text, chunks)
        skill = self._skill_manager.get("contract_audit")
        results: list[AuditResult] = []
        for index, window in enumerate(windows, start=1):
            results.extend(asyncio.run(self._audit_window(index=index, window=window, text=text, rule_set_id=rule_set_id, skill=skill, audit_plan=audit_plan, context_documents=self._context_documents)))
        self._pending_audits.pop(task_id, None)
        return self._deduplicate_results(results)

    def process_user_challenge(self, user_input: str, result: AuditResult) -> str:
        related_rules = self._search_rules(result.original_quote + " " + user_input, top_k=5)
        prompt = (
            "用户质疑某个风险点，请重新复核原文和规则。"
            f"\n用户输入: {user_input}"
            f"\n原文引用: {result.original_quote}"
            f"\n风险项: {json.dumps(result.model_dump(), ensure_ascii=False)}"
            f"\n相关规则: {json.dumps(related_rules, ensure_ascii=False)}"
            "\n如果用户是对的，请明确承认错误并建议撤回该风险项；"
            "如果仍然存在更深层次担忧，请解释原因。"
        )
        try:
            response = self._client.chat(prompt, system_prompt="你是合同复核助手。", task_type="analysis")
            return response if isinstance(response, str) else str(response)
        except Exception as exc:
            return f"复核失败: {exc}"

    def _record_result_context(self, result: AuditResult, *, thinking: str = "", audit_plan: dict[str, Any] | None = None, context_documents: list[dict[str, Any]] | None = None, conflict_notes: list[str] | None = None) -> str:
        result_id = f"{result.audit_item}:{result.char_index.start}:{result.char_index.end}:{hash(result.original_quote)}"
        self._result_lookup[result_id] = result
        self._audit_context[result_id] = {"thinking": thinking, "audit_plan": audit_plan or {}, "context_documents": context_documents or [], "conflict_notes": conflict_notes or []}
        return result_id

    def _audit_chunk(self, chunk_text: str, rules: list[dict[str, Any]], *, source_text: str, skill: Any | None = None, audit_plan: dict[str, Any] | None = None, context_documents: list[dict[str, Any]] | None = None, window: dict[str, Any] | None = None, conflict_notes: list[str] | None = None) -> str:
        tool_results = self._run_contextual_tool_checks(chunk_text)
        if skill and hasattr(skill.executor_module, "ContractAuditExecutor"):
            executor = skill.executor_module.ContractAuditExecutor()
            prompt = executor.build_prompt(chunk_text=chunk_text, source_text=source_text, retrieved_rules=rules, audit_plan=audit_plan, context_docs=context_documents, tool_results=tool_results, scenario="\n".join(conflict_notes or []))
            system_prompt = executor.system_prompt()
        else:
            prompt = self._build_prompt(chunk_text, rules, source_text=source_text, audit_plan=audit_plan)
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

    def _build_prompt(self, chunk_text: str, rules: list[dict[str, Any]], *, source_text: str, audit_plan: dict[str, Any] | None = None) -> str:
        return json.dumps(
            {
                "contract_chunk": chunk_text,
                "source_text": source_text,
                "retrieved_rules": rules,
                "audit_plan": audit_plan or {},
                "self_check": [
                    "original_quote 是否能在 source_text 中原样找到",
                    "char_index 是否覆盖 original_quote 的真实位置",
                    "如果找不到证据，输出 no_rule_found",
                    "优先关注 audit_plan 中的审计重点",
                ],
                "output_requirements": {"strict_json": True, "no_hallucination": True, "thinking_first": True},
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
        cleaned = re.sub(r"<thinking>[\s\S]*?</thinking>", "", cleaned, flags=re.IGNORECASE).strip()
        if "no_rule_found" in cleaned.lower():
            return []
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
                if match_index is None:
                    print("[Audit] 丢弃一条结果，原因: quote_mismatch")
                    print(f"[Audit] 失败的原文引用 (quote): {quote}")
                    print(f"[Audit] 失败的 JSON 片段: {item_json}")
                    continue

                char_index = item.get("char_index", {})
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
                if not any(token and token in text for token in [audit_item, content[:20], str(meta.get("evidence", ""))]):
                    continue
                quote_candidate = self._find_fuzzy_quote(text, audit_item)
                if isinstance(quote_candidate, str):
                    quote = quote_candidate
                else:
                    quote = self._find_liquidated_damage_quote(text) or chunk.text or text
                match_start = self._find_fuzzy_quote(text, quote)
                if match_start is None:
                    match_start = text.find(quote) if isinstance(quote, str) else -1
                start = max(match_start, 0)
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

    def _strategic_gap_analysis(self, text: str, audit_plan: dict[str, Any], results: list[AuditResult], *, rule_set_id: str | None = None, skill: Any | None = None) -> list[AuditResult]:
        priority_focus = [str(item) for item in audit_plan.get("priority_focus", []) if str(item).strip()]
        if not priority_focus:
            return []
        existing_text = " ".join([item.audit_item + " " + item.risk_description + " " + item.original_quote for item in results])
        missing_focus: list[str] = []
        for focus in priority_focus:
            if focus not in existing_text:
                missing_focus.append(focus)
        if not missing_focus:
            return []

        print(f"[Agent-Strategy] 正在复核规划完成度... 发现“{'、'.join(missing_focus)}”项缺失，正在执行战略补漏...")
        supplement_results: list[AuditResult] = []
        for focus in missing_focus:
            extra_rules = self._search_rules(f"{text} {focus}", rule_set_id=rule_set_id, top_k=8, audit_plan=audit_plan)
            if not extra_rules:
                continue
            full_window = {
                "text": text,
                "chunk": DocumentChunk(text=text, start=0, end=len(text), source_name=""),
            }
            try:
                response = self._client.chat(
                    self._build_prompt(text[:5000], extra_rules, source_text=text, audit_plan=audit_plan),
                    system_prompt=self._system_prompt(),
                    task_type="analysis",
                )
                parsed = self._parse_llm_results(response, source_text=text, chunk=full_window["chunk"], skill=skill)
                supplement_results.extend(parsed)
            except Exception as exc:
                print(f"[Agent-Strategy] 补漏审计失败: {exc}")
        return supplement_results

    def _resolve_global_conflicts(self, text: str, results: list[AuditResult], *, skill: Any | None = None, audit_plan: dict[str, Any] | None = None) -> list[AuditResult]:
        if len(results) < 2:
            return results
        if skill and hasattr(skill.executor_module, "ContractAuditExecutor"):
            executor = skill.executor_module.ContractAuditExecutor()
            summary = executor.generate_executive_summary(results)
            print(f"[Agent-Strategy] 全局总结: {summary}")
        grouped: dict[str, list[AuditResult]] = {}
        for item in results:
            grouped.setdefault(item.audit_item, []).append(item)
        resolved: list[AuditResult] = []
        for audit_item, items in grouped.items():
            if len(items) == 1:
                resolved.extend(items)
                continue
            items.sort(key=lambda x: (0 if x.risk_level in {"严重", "高"} else 1, len(x.original_quote)))
            resolved.append(items[0])
        return resolved

    def _build_summary_result(self, text: str, results: list[AuditResult], *, skill: Any | None = None) -> AuditResult | None:
        if not results:
            return None
        summary = ""
        if skill and hasattr(skill.executor_module, "ContractAuditExecutor"):
            summary = skill.executor_module.ContractAuditExecutor().generate_executive_summary(results)
        else:
            top_items = [f"{item.audit_item}（{item.risk_level}）" for item in results[:4]]
            summary = "；".join(top_items)
        return AuditResult(
            risk_level="中",
            audit_item="整体风险总结",
            risk_description=summary[:200],
            original_quote=text[:80],
            char_index=CharIndex(start=0, end=min(len(text), 80)),
            suggestion="建议优先处理高风险条款并进行全文复核。",
        )

    def _expand_window(self, window: dict[str, Any], text: str, *, padding: int = 500) -> dict[str, Any]:
        chunk = window["chunk"]
        start = max(0, getattr(chunk, "start", 0) - padding)
        end = min(len(text), getattr(chunk, "end", len(text)) + padding)
        expanded_text = text[start:end]
        return {
            "text": expanded_text,
            "chunk": DocumentChunk(text=expanded_text, start=start, end=end, source_name=getattr(chunk, "source_name", "")),
        }

    def resume_audit_with_answer(self, task_id: str, answer: str) -> list[AuditResult] | ClarificationRequest:
        pending = self._pending_audits.get(task_id)
        if not pending:
            return ClarificationRequest(question="未找到可恢复的挂起审计任务，请重新发起审计。", options=None, context_fragment=None)
        print("[Agent-Resume] 收到用户回答，正在更新审计策略并继续...")
        audit_plan = dict(pending.get("audit_plan") or {})
        clarification = pending.get("clarification") or {}
        audit_plan["ready"] = True
        audit_plan["user_answer"] = answer
        audit_plan["clarification_answer"] = answer
        if isinstance(clarification, dict):
            audit_plan["clarification_question"] = clarification.get("question")
            audit_plan["clarification_context_fragment"] = clarification.get("context_fragment")
        text = str(pending.get("text") or "")
        chunks = pending.get("chunks") or []
        rule_set_id = pending.get("rule_set_id")
        background_files = pending.get("background_files") or []
        self._context_documents = self._load_context_documents(background_files)
        results: list[AuditResult] = []
        windows = self._build_sliding_windows(text, chunks)
        skill = self._skill_manager.get("contract_audit")
        for index, window in enumerate(windows, start=1):
            try:
                results.extend(asyncio.run(self._audit_window(index=index, window=window, text=text, rule_set_id=rule_set_id, skill=skill, audit_plan=audit_plan, context_documents=self._context_documents)))
            except Exception:
                continue
        self._pending_audits.pop(task_id, None)
        return self._deduplicate_results(results)

    def _needs_clarification_for_window(self, chunk_text: str, rules: list[dict[str, Any]], *, audit_plan: dict[str, Any] | None = None) -> bool:
        text = chunk_text
        if re.search(r"劳务|劳动", text) and re.search(r"灵活用工|派遣|外包|兼职|雇佣", text):
            return True
        if re.search(r"甲方|乙方", text) and re.search(r"责任|义务|赔偿|免责", text) and not (audit_plan or {}).get("assumed_party_view"):
            return True
        if len({str((r.get("metadata") or {}).get("standard_version") or "") for r in rules if (r.get("metadata") or {}).get("standard_version")}) > 1:
            return True
        return False

    def _build_clarification_for_window(self, chunk_text: str, *, audit_plan: dict[str, Any] | None = None) -> ClarificationRequest:
        if re.search(r"劳务|劳动", chunk_text):
            return ClarificationRequest(
                question="当前文本同时出现劳务/劳动混淆特征，请确认本合同的用工性质。",
                options=["劳动关系", "劳务关系", "外包/合作关系", "暂不确定"],
                context_fragment=chunk_text[:300],
            )
        if re.search(r"责任|义务|赔偿|免责", chunk_text) and not (audit_plan or {}).get("assumed_party_view"):
            return ClarificationRequest(
                question="该条款存在双向责任表述，请确认本次审计优先保护哪一方。",
                options=["甲方", "乙方", "双方平衡", "按中立视角"],
                context_fragment=chunk_text[:300],
            )
        return ClarificationRequest(
            question="检测到多个版本行业标准，审计严格程度应如何设定？",
            options=["宽松", "标准", "严格", "按行业惯例"],
            context_fragment=chunk_text[:300],
        )

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

    def _extract_thinking(self, raw_response: str) -> str:
        match = re.search(r"<thinking>([\s\S]*?)</thinking>", raw_response, flags=re.IGNORECASE)
        return match.group(1).strip() if match else ""

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

    def _search_rules(self, query: str, *, rule_set_id: str | None = None, top_k: int = 8, audit_plan: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        rules = self._vector_service.search(query, top_k=top_k)
        history_records = self._history_service.list_recent(limit=10)
        history_keywords: list[str] = []
        for record in history_records:
            for item in record.get("results", []):
                quote = str(item.get("original_quote") or "")
                suggested_revision = str(item.get("suggested_revision") or "")
                suggestion = str(item.get("suggestion") or "")
                if quote:
                    history_keywords.append(quote[:20])
                if suggested_revision:
                    history_keywords.append(suggested_revision[:20])
                if suggestion:
                    history_keywords.append(suggestion[:20])
        if history_keywords:
            print("[Agent-Action] 正在为风险项生成修订稿... 检索到用户历史偏好，已应用定制化策略。")
            for keyword in history_keywords[:5]:
                extra = self._vector_service.search(f"{query} {keyword}", top_k=top_k)
                if extra:
                    rules.extend(extra)
        suggested_keywords = []
        priority_focus = []
        contract_type = ""
        if audit_plan:
            suggested_keywords = [str(item) for item in audit_plan.get("suggested_rule_keywords", []) if str(item).strip()]
            priority_focus = [str(item) for item in audit_plan.get("priority_focus", []) if str(item).strip()]
            contract_type = str(audit_plan.get("contract_type") or "")

        if suggested_keywords or priority_focus or contract_type:
            expanded_queries = [query]
            expanded_queries.extend(suggested_keywords)
            expanded_queries.extend(priority_focus)
            if contract_type:
                expanded_queries.append(contract_type)
            boosted: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            for q in expanded_queries:
                for rule in self._vector_service.search(f"{query} {q}".strip(), top_k=top_k):
                    rule_id = str(rule.get("rule_id") or "")
                    if rule_id and rule_id not in seen_ids:
                        boosted.append(rule)
                        seen_ids.add(rule_id)
            if boosted:
                rules = boosted

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
                extra_query = f"{query} {keyword}"
                if suggested_keywords:
                    extra_query = f"{extra_query} {' '.join(suggested_keywords)}"
                extra = self._vector_service.search(extra_query, top_k=top_k)
                preferred = [rule for rule in extra if str((rule.get("metadata") or {}).get("category") or "").lower() == str(rule_set_id).lower()]
                if preferred:
                    return preferred
        return rules

    def _load_context_documents(self, background_files: list[str | Path]) -> list[dict[str, Any]]:
        docs: list[dict[str, Any]] = []
        for item in background_files:
            path = Path(item)
            if not path.exists():
                continue
            text, _ = self._parser.parse(path)
            docs.append({"name": path.name, "path": str(path), "text": text[:4000]})
        return docs

    def _detect_context_conflicts(self, chunk_text: str, context_documents: list[dict[str, Any]]) -> list[str]:
        notes: list[str] = []
        for doc in context_documents:
            doc_text = str(doc.get("text") or "")
            if any(keyword in chunk_text and keyword in doc_text for keyword in ["账期", "支付", "付款", "违约金", "宽限期"]):
                if re.search(r"(30|三十)\s*天", doc_text) and re.search(r"(45|四十五)\s*天", chunk_text):
                    note = f"发现当前 SOW 条款与关联主协议第 3.2 条存在冲突，已标记风险。"
                    notes.append(note)
                    print(f"[Agent-Context] {note}")
        return notes

    def _run_contextual_tool_checks(self, prompt_text: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*%.*?(违约金|逾期利率|罚息)", prompt_text):
            rate_text = match.group(0)
            tool_result = DEFAULT_LEGAL_TOOLS.interest_cap_check(rate_text=rate_text)
            if not tool_result.ok:
                print(f"[Agent-External] 正在调用利率计算工具校验违约金... {tool_result.message}")
            results.append(tool_result.data | {"tool_name": tool_result.tool_name, "ok": tool_result.ok, "message": tool_result.message})
        grace_match = re.search(r"宽限期.{0,8}?(\d+)\s*天", prompt_text)
        payment_match = re.search(r"支付期.{0,8}?(\d+)\s*天", prompt_text)
        if grace_match and payment_match:
            tool_result = DEFAULT_LEGAL_TOOLS.term_cap_check(grace_days=int(grace_match.group(1)), payment_days=int(payment_match.group(1)))
            results.append(tool_result.data | {"tool_name": tool_result.tool_name, "ok": tool_result.ok, "message": tool_result.message})
        return results

    def run_stress_test(self, scenarios: list[str]) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []
        for scenario in scenarios:
            related_rules = self._search_rules(scenario, top_k=10)
            print(f"[Stress-Test] 场景: {scenario}，检索到规则数: {len(related_rules)}")
            outputs.append(
                {
                    "scenario": scenario,
                    "related_rules": related_rules,
                    "recommendation": "建议结合交付、违约、赔偿、不可抗力、通知条款进行联动推演。",
                    "estimated_compensation": "以实际损失与合同约定为准，当前文本未支持精确金额自动计算。",
                }
            )
        return outputs

    def build_compliance_scorecard(self, results: list[AuditResult], audit_plan: dict[str, Any] | None = None) -> dict[str, Any]:
        audit_plan = audit_plan or {}
        priority_focus = [str(item) for item in audit_plan.get("priority_focus", []) if str(item).strip()]
        covered = 0
        result_blob = " ".join(f"{item.audit_item} {item.risk_description} {item.suggestion}" for item in results)
        for focus in priority_focus:
            if focus in result_blob:
                covered += 1
        risk_penalty = min(50, len(results) * 4)
        coverage_bonus = int((covered / max(len(priority_focus), 1)) * 30) if priority_focus else 0
        score = max(0, min(100, 100 - risk_penalty + coverage_bonus))
        return {"score": score, "priority_focus_total": len(priority_focus), "priority_focus_covered": covered, "risk_count": len(results)}
