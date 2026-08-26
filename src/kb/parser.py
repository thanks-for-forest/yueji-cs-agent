"""知识库文档解析器：支持 .md / .docx / .pdf → 纯文本 + 分块。

借鉴 Langchain-Chatchat / RAGFlow 的 KB 解析模式，轻量自研。
"""
from __future__ import annotations

import re
from pathlib import Path

SUPPORTED_EXT = {".md", ".markdown", ".docx", ".pdf", ".txt"}


def parse_document(filename: str, data: bytes) -> str:
    """按扩展名解析文档为纯文本。"""
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXT:
        raise ValueError(f"不支持的格式：{ext}（支持 {', '.join(sorted(SUPPORTED_EXT))}）")
    if ext in (".md", ".markdown", ".txt"):
        return data.decode("utf-8", errors="replace")
    if ext == ".docx":
        return _parse_docx(data)
    if ext == ".pdf":
        return _parse_pdf(data)
    raise ValueError(f"不支持的格式：{ext}")


def _parse_docx(data: bytes) -> str:
    import io

    from docx import Document

    doc = Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _parse_pdf(data: bytes) -> str:
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    parts = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            parts.append(text)
    return "\n".join(parts)


def chunk_text(text: str, chunk_size: int = 400, overlap: int = 60) -> list[str]:
    """按字符窗口分块（保留语义边界：优先在段落/句号处切断）。"""
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            # 在窗口内找最近的段落/句号边界
            window = text[start:end]
            cut = -1
            for sep in ("\n\n", "\n", "。", "！", "？", "；"):
                idx = window.rfind(sep)
                if idx > chunk_size * 0.4:
                    cut = idx
                    break
            if cut > 0:
                end = start + cut + len(sep)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break  # 已到文末，收尾
        start = end - overlap
    return chunks
