from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass
class LegalToolResult:
    tool_name: str
    ok: bool
    message: str
    data: dict[str, Any]


class LegalTools:
    def __init__(self, lpr_rate: float = 0.03, internal_deadline_cap_days: int = 30) -> None:
        self.lpr_rate = lpr_rate
        self.internal_deadline_cap_days = internal_deadline_cap_days

    def interest_cap_check(self, *, rate_text: str, lpr_rate: float | None = None, multiplier_cap: float = 4.0) -> LegalToolResult:
        parsed_rate = self._parse_percent(rate_text)
        cap_rate = float(lpr_rate if lpr_rate is not None else self.lpr_rate) * float(multiplier_cap)
        if parsed_rate is None:
            return LegalToolResult(
                tool_name="interest_cap_check",
                ok=False,
                message="无法解析利率或违约金比例",
                data={"rate_text": rate_text, "cap_rate": cap_rate},
            )
        exceeded = parsed_rate > cap_rate
        message = "发现超过法定上限" if exceeded else "未超过法定上限"
        return LegalToolResult(
            tool_name="interest_cap_check",
            ok=not exceeded,
            message=message,
            data={"parsed_rate": parsed_rate, "cap_rate": cap_rate, "multiplier_cap": multiplier_cap},
        )

    def term_cap_check(self, *, grace_days: int, payment_days: int, cap_days: int | None = None) -> LegalToolResult:
        cap = int(cap_days if cap_days is not None else self.internal_deadline_cap_days)
        total = int(grace_days) + int(payment_days)
        exceeded = total > cap
        message = "超过公司内部合规红线" if exceeded else "符合公司内部合规红线"
        return LegalToolResult(
            tool_name="term_cap_check",
            ok=not exceeded,
            message=message,
            data={"grace_days": int(grace_days), "payment_days": int(payment_days), "total_days": total, "cap_days": cap},
        )

    def parse_days(self, text: str) -> int | None:
        match = re.search(r"(\d+)\s*天", text)
        return int(match.group(1)) if match else None

    def _parse_percent(self, text: str) -> float | None:
        if not text:
            return None
        normalized = text.replace("‰", "%").replace("元", "")
        match = re.search(r"(\d+(?:\.\d+)?)\s*%", normalized)
        if match:
            return float(match.group(1)) / 100.0
        match = re.search(r"(\d+(?:\.\d+)?)\s*倍", normalized)
        if match:
            return float(match.group(1))
        return None


DEFAULT_LEGAL_TOOLS = LegalTools()
