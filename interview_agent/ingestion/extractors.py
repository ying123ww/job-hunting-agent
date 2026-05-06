from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path


@dataclass(slots=True)
class ExtractedText:
    text: str
    filename: str | None


class TextExtractor:
    def extract(
        self,
        *,
        text: str | None,
        content_base64: str | None,
        filename: str | None,
    ) -> ExtractedText:
        if text:
            return ExtractedText(text=text.strip(), filename=filename)
        if not content_base64:
            raise ValueError("No content supplied.")
        raw = base64.b64decode(content_base64)
        suffix = Path(filename or "document.txt").suffix.lower()
        if suffix in {".txt", ".md", ".tex"}:
            return ExtractedText(text=raw.decode("utf-8", errors="ignore").strip(), filename=filename)
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError as exc:
                raise ValueError("PDF support requires pypdf to be installed.") from exc
            reader = PdfReader(BytesIO(raw))
            pages = [page.extract_text() or "" for page in reader.pages]
            return ExtractedText(text="\n".join(pages).strip(), filename=filename)
        raise ValueError(f"Unsupported file suffix: {suffix or '<none>'}")
