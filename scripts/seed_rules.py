from __future__ import annotations

import csv
from pathlib import Path

from app.services.vector_service import VectorService

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "initial_rules.csv"


def seed_rules(csv_path: Path = CSV_PATH) -> int:
    vector_service = VectorService()
    if not csv_path.exists():
        raise FileNotFoundError(f"规则文件不存在: {csv_path}")

    loaded = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rule_id = (row.get("rule_id") or "").strip()
            category = (row.get("category") or "").strip()
            audit_item = (row.get("audit_item") or "").strip()
            audit_point = (row.get("audit_point") or "").strip()
            risk_level = (row.get("risk_level") or "中").strip() or "中"
            content = (row.get("content") or "").strip()
            suggestion = (row.get("suggestion") or "").strip()
            if not rule_id or not category or not audit_item or not audit_point or not content:
                continue

            vector_service.upsert_rule_from_row(
                rule_id=rule_id,
                category=category,
                audit_item=audit_item,
                audit_point=audit_point,
                risk_level=risk_level,
                content=content,
                suggestion=suggestion,
            )
            loaded += 1
            print(f"[Seed] 已导入/更新规则: {rule_id} - {audit_item}")

    print(f"规则库初始化完成，当前已加载 {loaded} 条专业规则")
    return loaded


if __name__ == "__main__":
    seed_rules()
