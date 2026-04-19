from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from app.services.audit_service import AuditService


class DummyParser:
    def parse(self, file_path):
        text = (
            "SaaS服务合同\n"
            "1. 服务范围：甲方向乙方提供软件服务。\n"
            "2. 责任限制：乙方责任以合同金额为限。\n"
            "3. 违约金：逾期付款按每日千分之五支付违约金。\n"
        )
        return text, []


class DummyVectorService:
    def search(self, query, top_k=5):
        print(f"[Test-Search] query={query}")
        return [
            {
                "rule_id": "r1",
                "content": "责任限制条款",
                "metadata": {"category": "service", "audit_item": "责任限制", "risk_level": "高", "suggestion": "建议明确责任上限。"},
                "distance": 0.1,
            },
            {
                "rule_id": "r2",
                "content": "违约金条款",
                "metadata": {"category": "service", "audit_item": "逾期违约金", "risk_level": "高", "suggestion": "建议降低违约金比例。"},
                "distance": 0.2,
            },
        ]


class DummyResponse:
    def __init__(self, content: str):
        self.choices = [type("Choice", (), {"message": type("Message", (), {"content": content})()})()]


class DummyClient:
    def chat(self, prompt, system_prompt="", temperature=0.2, task_type="analysis"):
        if task_type == "reasoning":
            return '{"contract_type":"SaaS","priority_focus":["责任限制","知识产权","逾期违约金"],"suggested_rule_keywords":["SaaS","服务范围","数据安全"]}'
        return '{"items":[{"risk_level":"高","audit_item":"逾期违约金","evidence_points":["逾期付款"],"original_quote":"逾期付款按每日千分之五支付违约金。","char_index":{"start":0,"end":20},"conclusion":"存在高额违约金风险","suggestion":"建议调低违约金比例。"}]}'


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_path = Path(tmpdir) / "contract.txt"
        fake_path.write_text("dummy", encoding="utf-8")

        service = AuditService(
            client=DummyClient(),
            vector_service=DummyVectorService(),
            parser=DummyParser(),
        )

        results = service.audit_contract_file(fake_path)
        print(f"[Test] results={len(results)}")
