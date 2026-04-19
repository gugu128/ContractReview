from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    import chromadb
    from chromadb.api.models.Collection import Collection
except Exception:  # pragma: no cover - optional dependency
    chromadb = None
    Collection = Any


@dataclass
class RuleRecord:
    rule_id: str
    audit_item: str
    audit_point: str
    risk_level: str
    tags: list[str]
    content: str
    metadata: dict[str, Any]


class VectorService:
    """Lightweight private rule repository with optional ChromaDB backend."""

    def __init__(self, persist_dir: str | Path = "data/chroma_rules") -> None:
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._memory_store: dict[str, RuleRecord] = {}
        self._collection: Collection | None = None
        if chromadb is not None:
            client = chromadb.PersistentClient(path=str(self.persist_dir))
            self._collection = client.get_or_create_collection(name="audit_rules")
        self._bootstrap_from_csv()

    def upsert_rule(
        self,
        *,
        rule_id: str,
        audit_item: str,
        audit_point: str,
        risk_level: str,
        tags: list[str] | None = None,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RuleRecord:
        tags = tags or []
        content = content or f"{audit_item}\n{audit_point}\n{' '.join(tags)}"
        metadata = metadata or {}
        record = RuleRecord(rule_id, audit_item, audit_point, risk_level, tags, content, metadata)
        if self._collection is not None:
            self._collection.upsert(
                ids=[rule_id],
                documents=[content],
                metadatas=[{**metadata, "audit_item": audit_item, "audit_point": audit_point, "risk_level": risk_level, "tags": tags}],
            )
        self._memory_store[rule_id] = record
        return record

    def upsert_rule_from_row(
        self,
        *,
        rule_id: str,
        category: str,
        audit_item: str,
        audit_point: str,
        risk_level: str,
        content: str,
        suggestion: str,
    ) -> RuleRecord:
        metadata = {"category": category, "suggestion": suggestion, "source": "initial_rules.csv"}
        tags = [category, audit_item]
        return self.upsert_rule(
            rule_id=rule_id,
            audit_item=audit_item,
            audit_point=audit_point,
            risk_level=risk_level,
            tags=tags,
            content=content,
            metadata=metadata,
        )

    def _bootstrap_from_csv(self) -> None:
        csv_path = Path("data/initial_rules.csv")
        if not csv_path.exists():
            return
        try:
            import csv

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
                    if rule_id and category and audit_item and audit_point and content:
                        self.upsert_rule_from_row(
                            rule_id=rule_id,
                            category=category,
                            audit_item=audit_item,
                            audit_point=audit_point,
                            risk_level=risk_level,
                            content=content,
                            suggestion=suggestion,
                        )
        except Exception:
            pass

    def get_rule(self, rule_id: str) -> RuleRecord | None:
        if rule_id in self._memory_store:
            return self._memory_store[rule_id]
        if self._collection is not None:
            res = self._collection.get(ids=[rule_id])
            if res.get("ids"):
                meta = (res.get("metadatas") or [[{}]])[0][0] if res.get("metadatas") else {}
                doc = (res.get("documents") or [[""]])[0][0] if res.get("documents") else ""
                record = RuleRecord(
                    rule_id=rule_id,
                    audit_item=str(meta.get("audit_item", "")),
                    audit_point=str(meta.get("audit_point", "")),
                    risk_level=str(meta.get("risk_level", "")),
                    tags=list(meta.get("tags", [])),
                    content=doc,
                    metadata=meta,
                )
                self._memory_store[rule_id] = record
                return record
        return None

    def list_rules(self) -> list[RuleRecord]:
        return list(self._memory_store.values())

    def delete_rule(self, rule_id: str) -> bool:
        existed = self._memory_store.pop(rule_id, None) is not None
        if self._collection is not None:
            self._collection.delete(ids=[rule_id])
        return existed

    def search(self, query: str, *, top_k: int = 5) -> list[dict[str, Any]]:
        records = list(self._memory_store.values())

        if self._collection is not None:
            result = self._collection.query(query_texts=[query], n_results=top_k)
            ids = (result.get("ids") or [[]])[0]
            docs = (result.get("documents") or [[]])[0]
            metas = (result.get("metadatas") or [[]])[0]
            distances = (result.get("distances") or [[]])[0]
            items: list[dict[str, Any]] = []
            for idx, rule_id in enumerate(ids):
                items.append(
                    {
                        "rule_id": rule_id,
                        "content": docs[idx] if idx < len(docs) else "",
                        "metadata": metas[idx] if idx < len(metas) else {},
                        "distance": distances[idx] if idx < len(distances) else None,
                    }
                )
            if items:
                return items

            if not records:
                fetched = self._collection.get()
                ids_all = fetched.get("ids") or []
                docs_all = fetched.get("documents") or []
                metas_all = fetched.get("metadatas") or []
                for idx, rule_id in enumerate(ids_all):
                    meta = metas_all[idx] if idx < len(metas_all) else {}
                    doc = docs_all[idx] if idx < len(docs_all) else ""
                    record = RuleRecord(
                        rule_id=str(rule_id),
                        audit_item=str(meta.get("audit_item", "")),
                        audit_point=str(meta.get("audit_point", "")),
                        risk_level=str(meta.get("risk_level", "")),
                        tags=list(meta.get("tags", [])),
                        content=str(doc),
                        metadata=dict(meta),
                    )
                    self._memory_store[record.rule_id] = record
                records = list(self._memory_store.values())

        query_parts = self._build_query_parts(query)
        scored: list[tuple[int, RuleRecord]] = []
        for record in records:
            haystack = " ".join([record.audit_item, record.audit_point, " ".join(record.tags), record.content, str(record.metadata.get("category", ""))]).lower()
            score = 0
            for token in query_parts:
                if token and token in haystack:
                    score += 2 if len(token) >= 2 else 1
            scored.append((score, record))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                "rule_id": record.rule_id,
                "content": record.content,
                "metadata": asdict(record),
                "distance": None,
            }
            for score, record in scored[:top_k]
            if score > 0
        ]

    def _build_query_parts(self, query: str) -> list[str]:
        import re

        parts = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]+", query.lower())
        if parts:
            return parts
        chars = [ch for ch in query.lower() if ch.strip()]
        return ["".join(chars[i : i + 2]) for i in range(max(0, len(chars) - 1))]
