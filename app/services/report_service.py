from __future__ import annotations

from pathlib import Path

from app.models.schemas import AuditResult


class ReportService:
    def export_pdf(self, filename: str, results: list[AuditResult], output_dir: str | Path = "data/reports") -> Path:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        report_file = output_path / f"{Path(filename).stem}_audit_report.pdf"
        content_lines = [
            "合规罗盘审核报告",
            f"文件：{filename}",
            "",
        ]
        for idx, item in enumerate(results, start=1):
            content_lines.extend(
                [
                    f"{idx}. {item.audit_item}",
                    f"风险等级：{item.risk_level}",
                    f"风险提示：{item.risk_description}",
                    f"原文引用：{item.original_quote}",
                    f"建议：{item.suggestion}",
                    "",
                ]
            )
        report_file.write_text("\n".join(content_lines), encoding="utf-8")
        return report_file
