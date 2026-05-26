from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from ..core.config import get_settings


class TextExtractionError(RuntimeError):
    pass


class OCRFallbackNotImplementedError(TextExtractionError):
    pass


class OCRPlaceholderExtractor:
    def extract_chunks(self, _pdf_path: Path) -> list[str]:
        raise OCRFallbackNotImplementedError(
            "No text layer was found in the PDF. OCR fallback is reserved but not implemented in this version."
        )


class TextLayerChunkExtractor:
    _chapter_patterns = (
        re.compile(r"^\s*第[一二三四五六七八九十百千0-9]+[章节篇部卷]\s*.*$"),
        re.compile(r"^\s*Chapter\s+\d+[:.\s-].*$", re.IGNORECASE),
        re.compile(r"^\s*[一二三四五六七八九十]+[、.．]\s*.+$"),
    )

    def __init__(self) -> None:
        self.settings = get_settings()
        self.ocr_fallback = OCRPlaceholderExtractor()

    def extract_chunks(self, pdf_path: Path) -> list[str]:
        reader = PdfReader(str(pdf_path))
        paragraphs: list[str] = []
        current_chapter = "Uncategorized"
        started_content = False

        for page in reader.pages:
            text = page.extract_text() or ""
            for paragraph in self._extract_paragraphs(text):
                if not paragraph:
                    continue
                if self._is_noise_paragraph(paragraph) and not started_content:
                    continue
                started_content = True
                if self._is_chapter_heading(paragraph):
                    current_chapter = paragraph
                    paragraphs.append(f"## {current_chapter}")
                    continue
                paragraphs.append(f"[{current_chapter}] {paragraph}")

        if not paragraphs:
            return self.ocr_fallback.extract_chunks(pdf_path)

        return self._group_paragraphs(paragraphs)

    def _extract_paragraphs(self, text: str) -> list[str]:
        lines = [self._normalize_line(line) for line in text.splitlines()]
        lines = [line for line in lines if line]
        paragraphs: list[str] = []
        current: list[str] = []

        for line in lines:
            if self._is_noise_paragraph(line):
                if current:
                    paragraphs.append(" ".join(current))
                    current = []
                continue
            if self._is_chapter_heading(line):
                if current:
                    paragraphs.append(" ".join(current))
                    current = []
                paragraphs.append(line)
                continue

            current.append(line)
            paragraph_length = sum(len(item) for item in current)
            if paragraph_length >= self.settings.extraction_paragraph_limit or line.endswith(
                ("。", ".", ";", "；", "!", "！", "?", "？")
            ):
                paragraphs.append(" ".join(current))
                current = []

        if current:
            paragraphs.append(" ".join(current))
        return paragraphs

    def _group_paragraphs(self, paragraphs: list[str]) -> list[str]:
        chunks: list[str] = []
        current: list[str] = []
        size = 0

        for paragraph in paragraphs:
            is_heading = paragraph.startswith("## ")
            paragraph_size = len(paragraph)
            if current and (is_heading or size + paragraph_size > self.settings.extraction_chunk_size):
                chunks.append("\n".join(current))
                current = [paragraph]
                size = paragraph_size
            else:
                current.append(paragraph)
                size += paragraph_size

        if current:
            chunks.append("\n".join(current))
        return chunks

    def _normalize_line(self, line: str) -> str:
        line = line.replace("\u3000", " ")
        line = re.sub(r"\s+", " ", line).strip()
        return line

    def _is_noise_paragraph(self, text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return True
        if len(stripped) <= 2 and stripped.isdigit():
            return True
        if re.fullmatch(r"[0-9\s]+", stripped):
            return True
        if any(token in stripped for token in ("ISBN", "www.", "pmph.com", "定价", "购书热线", "CIP", "版权所有")):
            return True
        weird_ratio = sum(1 for char in stripped if ord(char) < 32 and char not in ("\t", "\n", "\r")) / len(stripped)
        return weird_ratio > 0.08

    def _is_chapter_heading(self, text: str) -> bool:
        stripped = text.strip()
        if len(stripped) > 80:
            return False
        return any(pattern.match(stripped) for pattern in self._chapter_patterns)
