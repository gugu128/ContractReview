"""RAG 检索引擎。

这个模块负责三件事：
1. 读取 data/rules.txt
2. 使用 sentence-transformers 生成向量
3. 用 FAISS 做相似度检索
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List, Optional

import faiss
import numpy as np
import requests
from sentence_transformers import SentenceTransformer

from app.utils import load_rules_text


@dataclass
class RuleItem:
    """单条规则及其相似度分数。"""

    text: str
    score: float
    rule_id: str | None = None


class RAGEngine:
    """负责规则库向量化、建索引和检索。"""

    def __init__(self):
        self.model: SentenceTransformer | None = None
        self.index = None
        self.rules: List[str] = []
        self.embeddings = None

    def _load_model(self) -> SentenceTransformer:
        """优先加载中文向量模型，失败时回退到兼容模型。

        为了避免网络慢导致长时间阻塞：
        1) 先尝试 local_files_only=True（若本地缓存有模型可秒开）
        2) 再尝试联网下载
        """
        candidates = [
            "BAAI/bge-small-zh",
            "shibing624/text2vec-base-chinese",
            "paraphrase-multilingual-MiniLM-L12-v2",
        ]

        # 可选：通过环境变量切换 HF 镜像，例如 https://hf-mirror.com
        if os.getenv("HF_ENDPOINT"):
            os.environ["HF_ENDPOINT"] = os.getenv("HF_ENDPOINT", "")

        last_error: Optional[Exception] = None

        # 第一轮：只用本地缓存，避免无网络时长时间重试
        for model_name in candidates:
            try:
                return SentenceTransformer(model_name, local_files_only=True)
            except Exception as exc:
                last_error = exc

        # 第二轮：允许联网下载（加长超时，减少频繁失败重试）
        try:
            requests.adapters.DEFAULT_RETRIES = 1
        except Exception:
            pass

        timeout_backup = os.getenv("HF_HUB_DOWNLOAD_TIMEOUT")
        os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = os.getenv("HF_HUB_DOWNLOAD_TIMEOUT", "60")

        for model_name in candidates:
            try:
                return SentenceTransformer(model_name)
            except Exception as exc:
                last_error = exc

        if timeout_backup is None:
            os.environ.pop("HF_HUB_DOWNLOAD_TIMEOUT", None)
        else:
            os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = timeout_backup

        if last_error is not None:
            raise RuntimeError(f"无法加载向量模型，请检查网络或预下载模型缓存。最后错误：{last_error}")
        raise RuntimeError("无法加载任意 sentence-transformers 模型。")

    def ensure_model(self) -> None:
        """延迟加载模型，避免页面打开时就初始化大模型。"""
        if self.model is None:
            self.model = self._load_model()

    @staticmethod
    def _report_progress(callback, value: float, message: str) -> None:
        if callback is not None:
            try:
                callback(value, message)
            except Exception:
                pass

    def _split_rules(self, text: str) -> List[str]:
        """按 [Rxxx] 标记切分规则库，确保每条规则独立成块。"""
        content = text.strip()
        if not content:
            return []

        # 主路径：基于 [R001]...[R020] 的位置切片，避免把整库误合并成一条。
        marker_iter = list(re.finditer(r"\[R\d{3}\]", content))
        chunks: List[str] = []
        if marker_iter:
            for idx, match in enumerate(marker_iter):
                start = match.start()
                end = marker_iter[idx + 1].start() if idx + 1 < len(marker_iter) else len(content)
                block = content[start:end].strip()
                if block and re.match(r"^\[R\d{3}\]", block):
                    chunks.append(block)
            if chunks:
                return chunks

        # 回退路径：兼容旧格式（R001 开头、空行分段）
        raw_blocks = [block.strip() for block in re.split(r"\n\s*\n+", content) if block.strip()]
        fallback_chunks: List[str] = []
        current: List[str] = []

        def flush() -> None:
            chunk = "\n".join(current).strip()
            if len(chunk) >= 50:
                fallback_chunks.append(chunk)

        for block in raw_blocks:
            is_rule_start = bool(re.match(r"^(\[)?R\d{3}(\])?\b", block))
            if is_rule_start and current:
                flush()
                current = [block]
            else:
                current.append(block)

        if current:
            flush()

        return fallback_chunks

    @staticmethod
    def _extract_rule_id(text: str) -> str | None:
        match = re.search(r"\[(R\d+)\]", text)
        if match:
            return match.group(1)
        match = re.search(r"\b(R\d{3})\b", text)
        return match.group(1) if match else None

    def rebuild(self, progress_callback=None) -> None:
        """重新加载规则库并构建 FAISS 索引。"""
        self._report_progress(progress_callback, 5, "正在读取规则库…")
        try:
            raw_text = load_rules_text().strip()
        except Exception:
            raw_text = ""
        self.rules = self._split_rules(raw_text)

        if not self.rules:
            self.index = None
            self.embeddings = None
            self._report_progress(progress_callback, 100, "规则库为空，已完成")
            return

        self._report_progress(progress_callback, 20, "正在加载中文向量模型…")
        self.ensure_model()
        assert self.model is not None
        self._report_progress(progress_callback, 55, f"正在向量化 {len(self.rules)} 条规则…")
        vectors = self.model.encode(self.rules, normalize_embeddings=True)
        vectors = np.asarray(vectors, dtype="float32")
        dimension = vectors.shape[1]
        self._report_progress(progress_callback, 85, "正在构建检索索引…")
        self.index = faiss.IndexFlatIP(dimension)
        self.index.add(vectors)
        self.embeddings = vectors
        self._report_progress(progress_callback, 100, "规则索引已完成")

    def retrieve(self, query: str, top_k: int = 5, min_score: float = 0.2) -> List[RuleItem]:
        """检索最相关的规则。"""
        if self.index is None or not self.rules:
            self.rebuild()
        if self.index is None or not self.rules:
            return []

        self.ensure_model()
        assert self.model is not None
        query_vec = self.model.encode([query], normalize_embeddings=True)
        query_vec = np.asarray(query_vec, dtype="float32")
        scores, indices = self.index.search(query_vec, min(max(top_k, 1), len(self.rules)))

        results: List[RuleItem] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1 or float(score) < min_score:
                continue
            text = self.rules[idx]
            results.append(RuleItem(text=text, score=float(score), rule_id=self._extract_rule_id(text)))
        return results
