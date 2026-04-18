from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.core.llm_client import DeepSeekClient
from app.models.schemas import CharIndex, CompareResult
from app.utils.document_parser import DocumentParser


class CompareService:
    def __init__(self, client: DeepSeekClient | None = None, parser: DocumentParser | None = None) -> None:
        self._client = client or DeepSeekClient()
        self._parser = parser or DocumentParser()

    def compare_files(self, base_file: str | Path, current_file: str | Path) -> list[CompareResult]:
        base_text, _ = self._parser.parse(base_file)
        current_text, _ = self._parser.parse(current_file)
        response = self._compare_texts(base_text, current_text)
        parsed = self._parse_llm_results(response)
        if parsed:
            return parsed
        return self._fallback_semantic_compare(base_text, current_text)

    def compare_texts(self, base_text: str, current_text: str) -> list[CompareResult]:
        response = self._compare_texts(base_text, current_text)
        parsed = self._parse_llm_results(response)
        if parsed:
            return parsed
        return self._fallback_semantic_compare(base_text, current_text)

    def _compare_texts(self, base_text: str, current_text: str) -> str:
        prompt = self._build_prompt(base_text, current_text)
        return self._client.chat(prompt, system_prompt=self._system_prompt(), temperature=0.1)

    def _system_prompt(self) -> str:
        return (
            "你是合同智能比对引擎，只能做语义比对，不要做简单字符 diff。"
            "如果仅换行、空格、标点变化且语义不变，不要输出差异。"
            "如果日期、金额、期限、责任、权利义务发生变化，必须识别为重要变更。"
            "请严格输出 JSON 数组，每个元素必须包含 change_type, base_content, current_content, impact_analysis, base_index, current_index。"
            "base_index 和 current_index 必须是 {start, end} 结构。"
        )

    def _build_prompt(self, base_text: str, current_text: str) -> str:
        return json.dumps(
            {
                "base_version": base_text,
                "current_version": current_text,
                "output_requirements": {
                    "strict_json": True,
                    "semantic_compare": True,
                    "ignore_formatting_only_changes": True,
                },
            },
            ensure_ascii=False,
            indent=2,
        )

    def _parse_llm_results(self, raw_response: str) -> list[CompareResult]:
        try:
            payload = json.loads(raw_response)
        except json.JSONDecodeError:
            return []

        items = payload if isinstance(payload, list) else payload.get("items", []) if isinstance(payload, dict) else []
        results: list[CompareResult] = []
        for item in items:
            try:
                results.append(
                    CompareResult(
                        change_type=item["change_type"],
                        base_content=item["base_content"],
                        current_content=item["current_content"],
                        impact_analysis=item["impact_analysis"],
                        base_index=CharIndex(**item["base_index"]),
                        current_index=CharIndex(**item["current_index"]),
                    )
                )
            except Exception:
                continue
        return results

    def _fallback_semantic_compare(self, base_text: str, current_text: str) -> list[CompareResult]:
        if self._normalize(base_text) == self._normalize(current_text):
            return []

        changes: list[CompareResult] = []
        base_segments = self._split_segments(base_text)
        current_segments = self._split_segments(current_text)

        matched_current = set()
        for base_seg, base_start, base_end in base_segments:
            best_match = None
            best_score = 0
            for idx, (cur_seg, cur_start, cur_end) in enumerate(current_segments):
                if idx in matched_current:
                    continue
                score = self._semantic_score(base_seg, cur_seg)
                if score > best_score:
                    best_score = score
                    best_match = (idx, cur_seg, cur_start, cur_end)
            if best_match and best_score >= 0.55:
                idx, cur_seg, cur_start, cur_end = best_match
                matched_current.add(idx)
                if self._normalize(base_seg) != self._normalize(cur_seg):
                    changes.append(
                        CompareResult(
                            change_type="修改",
                            base_content=base_seg,
                            current_content=cur_seg,
                            impact_analysis=self._impact_analysis(base_seg, cur_seg),
                            base_index=CharIndex(start=base_start, end=base_end),
                            current_index=CharIndex(start=cur_start, end=cur_end),
                        )
                    )
            else:
                changes.append(
                    CompareResult(
                        change_type="删除",
                        base_content=base_seg,
                        current_content="",
                        impact_analysis="当前版本中未找到对应条款，可能导致权利义务缺失或责任转移。",
                        base_index=CharIndex(start=base_start, end=base_end),
                        current_index=CharIndex(start=0, end=0),
                    )
                )

        for idx, (cur_seg, cur_start, cur_end) in enumerate(current_segments):
            if idx not in matched_current:
                changes.append(
                    CompareResult(
                        change_type="新增",
                        base_content="",
                        current_content=cur_seg,
                        impact_analysis="新条款可能引入额外权利义务或风险，请核查其合规性与业务影响。",
                        base_index=CharIndex(start=0, end=0),
                        current_index=CharIndex(start=cur_start, end=cur_end),
                    )
                )

        return changes

    def _split_segments(self, text: str) -> list[tuple[str, int, int]]:
        segments: list[tuple[str, int, int]] = []
        for match in re.finditer(r"[^。；;\n]+[。；;\n]?", text):
            seg = match.group(0).strip()
            if seg:
                segments.append((seg, match.start(), match.end()))
        return segments

    def _normalize(self, text: str) -> str:
        return re.sub(r"\s+", "", text).strip()

    def _semantic_score(self, a: str, b: str) -> float:
        a_norm = self._normalize(a)
        b_norm = self._normalize(b)
        if not a_norm or not b_norm:
            return 0.0
        if a_norm == b_norm:
            return 1.0
        overlap = len(set(a_norm) & set(b_norm))
        return overlap / max(len(set(a_norm)), len(set(b_norm)), 1)

    def _impact_analysis(self, base_seg: str, cur_seg: str) -> str:
        keywords = ["金额", "违约金", "期限", "工作日", "日内", "责任", "赔偿"]
        if any(k in base_seg or k in cur_seg for k in keywords):
            return "该变更可能影响付款、履约期限或责任边界，建议重点复核。"
        return "该变更可能影响合同解释或执行细节，建议确认业务意图。"
