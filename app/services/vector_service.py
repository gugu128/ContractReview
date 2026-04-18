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

        # Fallback heuristic search for environments without ChromaDB.
        query_tokens = set(query.lower().split())
        scored: list[tuple[int, RuleRecord]] = []
        for record in self._memory_store.values():
            haystack = " ".join([record.audit_item, record.audit_point, " ".join(record.tags), record.content]).lower()
            score = sum(1 for token in query_tokens if token and token in haystack)
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
