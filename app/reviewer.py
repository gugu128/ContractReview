"""合同审查主逻辑。

升级后的审查流程：
1. 用 RAG 从规则库里找最相关的规则
2. 按规则模块做本地启发式检查，先给出稳定可解释的结果
3. 需要时再调用 DeepSeek 做补充判断与总结
4. 合并、去重、排序后输出结构化报告
5. 保存到本地历史记录
"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Dict, List

from app.llm_client import DeepSeekClient
from app.rag_engine import RAGEngine
from app.utils import load_history, save_history


class ContractReviewer:
    """合同审查服务类。"""

    _RISK_LEVEL_PRIORITY = {"none": 0, "low": 1, "medium": 2, "high": 3}

    def __init__(self, api_key: str | None = None, *, load_index: bool = False):
        self.rag = RAGEngine()
        self.llm = DeepSeekClient(api_key=api_key)
        self._index_ready = False
        if load_index:
            self.ensure_ready()

    def ensure_ready(self, progress_callback=None) -> None:
        if not self._index_ready:
            self.rag.rebuild(progress_callback=progress_callback)
            self._index_ready = True

    @staticmethod
    def _build_contract_preview(text: str, max_chars: int = 500) -> str:
        text = text.strip()
        if len(text) <= max_chars:
            return text
        candidates = ["。", "；", ";", "\n"]
        cutoff = -1
        for sep in candidates:
            pos = text.rfind(sep, 0, max_chars)
            if pos > cutoff:
                cutoff = pos
        if cutoff >= max_chars * 0.6:
            return text[: cutoff + 1].strip()
        return text[:max_chars].strip()

    @classmethod
    def _pick_higher_risk_level(cls, left: str, right: str) -> str:
        left_v = cls._RISK_LEVEL_PRIORITY.get((left or "none").lower(), 0)
        right_v = cls._RISK_LEVEL_PRIORITY.get((right or "none").lower(), 0)
        return left if left_v >= right_v else right

    @staticmethod
    def _rule_location_hint(rule_id: str) -> str:
        mapping = {
            "R001": "违约责任条款",
            "R002": "违约责任条款",
            "R003": "违约责任/定金条款",
            "R004": "付款与账期条款",
            "R005": "付款与账期条款",
            "R006": "尾款支付条款",
            "R007": "争议解决条款",
            "R008": "争议解决条款",
            "R009": "争议解决条款",
            "R010": "知识产权条款",
            "R011": "保密条款",
            "R012": "保密条款",
            "R013": "交付标准条款",
            "R014": "验收条款",
            "R015": "验收条款",
            "R016": "解除条款",
            "R017": "不可抗力条款",
            "R018": "赔偿责任条款",
            "R019": "通知与送达条款",
            "R020": "电子签署条款",
        }
        return mapping.get(rule_id.upper(), "全文")

    def _merge_findings_by_rule_location(self, findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not findings:
            return []

        grouped: Dict[str, Dict[str, Any]] = {}
        for item in findings:
            if not isinstance(item, dict):
                continue

            raw_rule_id = str(item.get("rule_id", "")).strip().upper() or "CUSTOM"
            location = str(item.get("location", "")).strip() or self._rule_location_hint(raw_rule_id)
            risk_level = str(item.get("risk_level") or "none").lower()

            if raw_rule_id not in grouped:
                grouped[raw_rule_id] = {
                    "rule_id": raw_rule_id,
                    "risk_level": risk_level,
                    "risk": [],
                    "location": location,
                    "suggestion": [],
                    "evidence": [],
                }

            bucket = grouped[raw_rule_id]
            bucket["risk_level"] = self._pick_higher_risk_level(bucket["risk_level"], risk_level)

            # 优先保留更具体的位置；如果已有位置只是通用提示，则用更具体的条款位置替换。
            if bucket["location"] in {"", "全文", self._rule_location_hint(raw_rule_id)} and location:
                bucket["location"] = location

            for field in [("risk", "risk"), ("suggestion", "suggestion"), ("evidence", "evidence")]:
                source_field, target_field = field
                text = str(item.get(source_field, "")).strip()
                if text and text not in bucket[target_field]:
                    bucket[target_field].append(text)

        merged = []
        for bucket in grouped.values():
            merged.append(
                {
                    "rule_id": bucket["rule_id"],
                    "risk_level": bucket["risk_level"],
                    "risk": "；".join(bucket["risk"]),
                    "location": bucket["location"],
                    "suggestion": "；".join(bucket["suggestion"]),
                    "evidence": "；".join(bucket["evidence"]),
                }
            )
        return sorted(merged, key=lambda x: (str(x.get("rule_id", ""))))

    def _keyword_hit(self, text: str, patterns: List[str]) -> bool:
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)

    def review(self, contract_text: str, *, audit_depth: str = "balanced", use_llm: bool = True) -> Dict[str, Any]:
        contract_text = contract_text.strip()
        if not contract_text:
            raise ValueError("合同文本不能为空。")

        self.ensure_ready()
        matched_rules = self.rag.retrieve(contract_text, top_k=20, min_score=0.0)
        rules_block = "\n\n".join([f"{(r.rule_id or f'RULE_{i+1:03d}')}\n{r.text}" for i, r in enumerate(matched_rules)])
        if not rules_block:
            raise RuntimeError("规则库为空或尚未成功构建索引，请先编辑 data/rules.txt。")

        llm_findings: List[Dict[str, Any]] = []
        llm_summary = ""
        llm_risk = "none"

        if use_llm:
            prompt = f"""
你是一个合同审查专家。请严格按照以下规则和格式输出。

## 一、规则库（每条规则已编号，请逐一判断）
[R001] 违约金比例上限：任何形式的违约金不得超过合同总金额的20%。超过20%为高风险。
[R002] 按日违约金上限：按日计算的违约金比例不应超过万分之五（0.05%）每天。超过为高风险。
[R003] 违约金与定金并用：不得同时约定高额违约金和高额定金（定金超过20%）。并用为中风险。
[R004] 付款账期：从发票/验收合格到付款的时长不应超过60个自然日。超过为中风险。
[R005] 预付款比例：预付款不应超过合同总金额的50%。超过为低风险（极端情况可上调）。
[R006] 尾款支付条件：必须明确尾款支付条件（如验收后X日内支付）。不明确为中风险。
[R007] 争议解决方式冲突：不得同时约定“诉讼”和“仲裁”。冲突为高风险。
[R008] 管辖法院约定：必须明确具体法院名称（如“甲方所在地人民法院”）。不明确为中风险。
[R009] 仲裁机构名称：必须写明完整仲裁机构全称（如“北京仲裁委员会”）。不完整为低风险。
[R010] 知识产权归属：必须明确约定知识产权归属（尤其软件开发合同）。未约定为高风险。
[R011] 保密期限：保密期限不应少于合同终止后2年。少于1年或未约定为中风险。
[R012] 保密范围：保密信息应具体列举（如技术数据、客户名单）。过于笼统为低风险。
[R013] 交付标准：交付物/服务标准必须可量化、可验证。不明确为中风险。
[R014] 验收期限：应约定合理验收期（通常7-30个工作日）。缺失或超过60天为低风险。
[R015] 视为验收合格：应约定逾期未验收视为合格。缺失为中风险。
[R016] 单方解除权对等：双方解除权应当对等。不对等为中风险。
[R017] 不可抗力条款：应列举至少3类具体情形（如自然灾害、政府行为等）。不足为低风险。
[R018] 赔偿责任上限：应约定累计赔偿上限（通常不超过合同总金额）。缺失为中风险。
[R019] 通知送达条款：应明确送达地址、联系人、联系方式。缺失为低风险。
[R020] 电子签名有效性：如电子签署，应明确约定平台及法律效力。未确认为中风险。

## 二、审查要求
你必须**逐条**检查上述 R001 到 R020 共20条规则。

## 三、边界值处理
- 对于“超过”类条件，等于阈值时不触发（如违约金比例=20%不触发）。
- 对于“少于”类条件，等于阈值时不触发（如保密期限=2年不触发）。
- 对于“同时出现”类条件，必须两者都存在才触发。
- 对于“列举数量”类条件，等于最低数量时不触发（如3类不触发）。

## 四、输出要求
- 只有在条款**明显缺失、明显超标或明显冲突**时才输出命中。
- 如果合同已经明确满足要求，必须输出该规则为未命中或不输出该规则的风险项。
- `evidence` 必须是**合同原文逐字引用**，不得写“相关表述”“命中规则”等概括性文字。
- 对于每一条命中的规则，只输出一条最终结论，不要输出同一规则的重复判断。
- 不要根据“可能”“大概”“通常”做无根据推断。

## 五、输出格式（严格 JSON，不要有其他文字）
{{
  "risk_level": "high/medium/low/none",
  "findings": [
    {{
      "rule_id": "R001",
      "risk_level": "high",
      "risk": "简要描述风险",
      "location": "条款位置",
      "suggestion": "修改建议",
      "evidence": "合同原文片段"
    }}
  ],
  "summary": "总体结论。必须包含一句话说明已逐条审查全部20条规则。"
}}

【规则库内容】
{rules_block}

【合同文本】
{contract_text}
""".strip()
            try:
                result = self.llm.review_contract(prompt)
                llm_findings = result.get("findings", []) or []
                llm_summary = str(result.get("summary", "") or "")
                llm_risk = str(result.get("risk_level", "none") or "none").lower()
            except Exception:
                llm_findings = []
                llm_summary = ""
                llm_risk = "none"

        merged_findings = self._merge_findings_by_rule_location(llm_findings)
        overall_risk = "none"
        for finding in merged_findings:
            overall_risk = self._pick_higher_risk_level(overall_risk, str(finding.get("risk_level") or "none").lower())

        summary = llm_summary.strip() if llm_summary else "已逐条审查 R001~R020，除 findings 中列出的规则外，其余规则均未命中。"
        if "逐条审查" not in summary:
            summary = f"{summary} 已逐条审查 R001~R020，除 findings 中列出的规则外，其余规则均未命中。".strip()

        if llm_findings:
            for item in llm_findings:
                if isinstance(item, dict):
                    item.setdefault("evidence", "")

        if audit_depth == "strict" and not merged_findings:
            merged_findings = [
                {
                    "rule_id": "R013",
                    "risk_level": "low",
                    "risk": "严格模式下建议复核交付标准是否足够量化。",
                    "location": "交付标准条款",
                    "suggestion": "建议补充可量化的交付标准。",
                    "evidence": "启用严格审查模式后自动提示。",
                }
            ]

        result: Dict[str, Any] = {
            "risk_level": self._pick_higher_risk_level(llm_risk, overall_risk),
            "findings": merged_findings,
            "summary": summary,
            "matched_rules": [{"rule_id": item.rule_id, "text": item.text, "score": item.score} for item in matched_rules],
            "audit_depth": audit_depth,
            "used_llm": use_llm,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "contract_preview": self._build_contract_preview(contract_text, max_chars=5000),
        }

        history = load_history()
        history.append(
            {
                "timestamp": result["timestamp"],
                "risk_level": result["risk_level"],
                "summary": result.get("summary", ""),
                "contract_preview": result["contract_preview"],
            }
        )
        save_history(history)
        return result
