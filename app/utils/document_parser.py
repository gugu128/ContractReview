from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class DocumentChunk:
    text: str
    start: int
    end: int
    source_name: str
    title_path: tuple[str, ...] = ()
    level: int = 0
    page_start: int | None = None
    page_end: int | None = None


class DocumentParser:
    _heading_pattern = re.compile(
        r"^(?P<prefix>(?:第[一二三四五六七八九十百千0-9]+[章节条款项部分编]|[一二三四五六七八九十]+、|\d+(?:\.\d+)*))"
        r"(?P<title>[^\n]{0,60})$"
    )

    def parse(self, file_path: str | Path) -> tuple[str, list[DocumentChunk]]:
        path = Path(file_path)
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            text = self._parse_pdf(path)
        elif suffix in {".docx", ".doc"}:
            text = self._parse_word(path)
        else:
            text = path.read_text(encoding="utf-8", errors="ignore")
        chunks = self.chunk_text(text, chunk_size=800, overlap=120, source_name=path.name)
        return text, chunks

    def _parse_pdf(self, path: Path) -> str:
        try:
            from pypdf import PdfReader
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("PDF parsing requires pypdf") from exc

        reader = PdfReader(str(path))
        pages: list[str] = []
        for page_number, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or ""
            pages.append(f"\n[PAGE {page_number}]\n{page_text.strip()}\n")
        return "".join(pages).strip()

    def _parse_word(self, path: Path) -> str:
        try:
            from docx import Document
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Word parsing requires python-docx") from exc

        doc = Document(str(path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)

    def chunk_text(self, text: str, *, chunk_size: int = 800, overlap: int = 120, source_name: str = "") -> list[DocumentChunk]:
        if not text:
            return []

        blocks = self._split_blocks(text)
        chunks: list[DocumentChunk] = []
        current_title: list[str] = []
        current_start = 0
        current_level = 0

        for block in blocks:
            block_start, block_end, block_text = block
            heading = self._match_heading(block_text)
            if heading:
                title, level = heading
                while len(current_title) >= level:
                    current_title.pop()
                current_title.append(title)
                current_start = block_start
                current_level = level

            hierarchical_prefix = " / ".join(current_title[-3:])
            padded_text = self._build_context_padding(text, block_start, block_end, overlap, chunk_size)
            if hierarchical_prefix and hierarchical_prefix not in padded_text[: max(120, len(hierarchical_prefix) + 20)]:
                padded_text = f"{hierarchical_prefix}\n{padded_text}"

            if not padded_text.strip():
                continue

            chunks.append(
                DocumentChunk(
                    text=padded_text.strip(),
                    start=max(0, block_start - overlap),
                    end=min(len(text), block_end + overlap),
                    source_name=source_name,
                    title_path=tuple(current_title),
                    level=current_level,
                    page_start=self._extract_page_number(text, block_start),
                    page_end=self._extract_page_number(text, block_end),
                )
            )

        if not chunks:
            return self._fallback_chunks(text, chunk_size=chunk_size, overlap=overlap, source_name=source_name)
        return self._merge_overlapping_chunks(chunks)

    def _split_blocks(self, text: str) -> list[tuple[int, int, str]]:
        blocks: list[tuple[int, int, str]] = []
        start = 0
        for match in re.finditer(r"^.*(?:\n|$)", text, flags=re.MULTILINE):
            line = match.group(0)
            line_text = line.rstrip("\n")
            if line_text.strip():
                blocks.append((match.start(), match.end(), line_text.strip()))
            start = match.end()
        if not blocks and text.strip():
            blocks.append((0, len(text), text.strip()))
        return blocks

    def _match_heading(self, line: str) -> tuple[str, int] | None:
        normalized = line.strip().replace(" ", "")
        if len(normalized) > 80:
            return None
        match = self._heading_pattern.match(normalized)
        if not match:
            return None
        prefix = match.group("prefix")
        title = match.group("title").strip("：:、. ")
        if not title:
            title = prefix
        level = prefix.count(".") + (1 if prefix else 0)
        if prefix.startswith("第"):
            level = max(1, prefix.count("章") or prefix.count("节") or prefix.count("条") or 1)
        return title, level

    def _build_context_padding(self, text: str, start: int, end: int, overlap: int, chunk_size: int) -> str:
        left = max(0, start - overlap)
        right = min(len(text), end + max(overlap, chunk_size // 4))
        window = text[left:right].strip()
        return window

    def _extract_page_number(self, text: str, index: int) -> int | None:
        page_markers = list(re.finditer(r"\[PAGE\s+(\d+)\]", text[: max(index, 0) + 1]))
        if not page_markers:
            return None
        return int(page_markers[-1].group(1))

    def _fallback_chunks(self, text: str, *, chunk_size: int, overlap: int, source_name: str) -> list[DocumentChunk]:
        chunks: list[DocumentChunk] = []
        start = 0
        text_length = len(text)
        while start < text_length:
            end = min(start + chunk_size, text_length)
            if end < text_length:
                split_at = text.rfind("\n", start, end)
                if split_at > start + chunk_size // 2:
                    end = split_at + 1
            chunk_text = text[start:end].strip()
            if chunk_text:
                actual_start = self._find_chunk_start(text, chunk_text, start)
                actual_end = actual_start + len(chunk_text)
                chunks.append(DocumentChunk(text=chunk_text, start=actual_start, end=actual_end, source_name=source_name))
            if end >= text_length:
                break
            start = max(end - overlap, start + 1)
        return chunks

    def _merge_overlapping_chunks(self, chunks: list[DocumentChunk]) -> list[DocumentChunk]:
        merged: list[DocumentChunk] = []
        for chunk in chunks:
            if merged and chunk.start <= merged[-1].end and merged[-1].title_path == chunk.title_path:
                prev = merged[-1]
                merged[-1] = DocumentChunk(
                    text=f"{prev.text}\n{chunk.text}",
                    start=prev.start,
                    end=max(prev.end, chunk.end),
                    source_name=chunk.source_name,
                    title_path=chunk.title_path,
                    level=max(prev.level, chunk.level),
                    page_start=prev.page_start,
                    page_end=chunk.page_end,
                )
                continue
            merged.append(chunk)
        return merged

    def _find_chunk_start(self, text: str, chunk_text: str, approximate_start: int) -> int:
        exact = text.find(chunk_text, approximate_start)
        if exact >= 0:
            return exact
        return approximate_start
