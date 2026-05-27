from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path

from pypdf import PdfReader

from ..core.config import get_settings


class TextExtractionError(RuntimeError):
    pass


class OCRFallbackNotImplementedError(TextExtractionError):
    pass


@dataclass(frozen=True)
class ParagraphChunk:
    index: int
    page_number: int | None
    section_path: str
    text: str

    @property
    def excerpt(self) -> str:
        return self.text[:1000]


class OCRPlaceholderExtractor:
    def extract_chunks(self, _pdf_path: Path) -> list[ParagraphChunk]:
        raise OCRFallbackNotImplementedError(
            "PDF 中未找到可提取的文本层；当前版本仅预留 OCR 扩展接口，尚未实现。"
        )


class TextLayerChunkExtractor:
    _chapter_patterns = (
        re.compile(r"^\s*第\s*[一二三四五六七八九十百千万0-9]+\s*[章节篇部]\s*.*$"),
        re.compile(r"^\s*Chapter\s+\d+[:.\s-].*$", re.IGNORECASE),
        re.compile(r"^\s*[一二三四五六七八九十]+[、.．]\s*.+$"),
    )
    _section_patterns = (
        re.compile(r"^\s*第\s*[一二三四五六七八九十百千万0-9]+\s*节\s*.*$"),
        re.compile(r"^\s*[（(]?[一二三四五六七八九十0-9]+[)）]\s*.+$"),
        re.compile(r"^\s*[0-9]+\.[0-9.]*\s+.+$"),
    )
    _standalone_page_pattern = re.compile(r"^\d{1,4}$")

    def __init__(self) -> None:
        self.settings = get_settings()
        self.ocr_fallback = OCRPlaceholderExtractor()

    def extract_chunks(self, pdf_path: Path) -> list[ParagraphChunk]:
        reader = PdfReader(str(pdf_path))
        chunks: list[ParagraphChunk] = []
        current_path: list[str] = []
        started_content = False
        chunk_index = 1

        for page in reader.pages:
            raw_text = page.extract_text() or ""
            lines = self._normalize_lines(raw_text)
            printed_page_number = self._detect_printed_page_number(lines)
            paragraphs = self._extract_paragraphs(lines)

            for paragraph_index, paragraph in enumerate(paragraphs):
                if not paragraph:
                    continue
                if self._is_noise_paragraph(paragraph) and not started_content:
                    continue

                heading_level = self._heading_level(paragraph)
                if heading_level is None:
                    next_paragraph = self._next_content_paragraph(paragraphs, paragraph_index + 1)
                    if self._is_standalone_heading_paragraph(paragraph, next_paragraph):
                        heading_level = 3
                if heading_level:
                    started_content = True
                    current_path = self._update_section_path(current_path, heading_level, paragraph)
                    continue

                if self._is_short_non_content(paragraph):
                    continue

                started_content = True
                section_path = " / ".join(current_path)[:255] or "Uncategorized"
                chunks.append(
                    ParagraphChunk(
                        index=chunk_index,
                        page_number=printed_page_number,
                        section_path=section_path,
                        text=paragraph,
                    )
                )
                chunk_index += 1

        if not chunks:
            return self.ocr_fallback.extract_chunks(pdf_path)

        return chunks

    def _normalize_lines(self, text: str) -> list[str]:
        lines = [self._normalize_line(line) for line in text.splitlines()]
        return [line for line in lines if line]

    def _extract_paragraphs(self, lines: list[str]) -> list[str]:
        paragraphs: list[str] = []
        current: list[str] = []

        for line in lines:
            if self._is_noise_paragraph(line):
                if current:
                    paragraphs.append(self._merge_paragraph_lines(current))
                    current = []
                continue

            heading_level = self._heading_level(line)
            if heading_level:
                if current:
                    paragraphs.append(self._merge_paragraph_lines(current))
                    current = []
                paragraphs.append(line)
                continue

            if current and len(current) == 1 and self._is_standalone_heading_paragraph(current[0], line):
                paragraphs.append(self._merge_paragraph_lines(current))
                current = [line]
                continue

            if current and self._starts_new_paragraph(line, current):
                paragraphs.append(self._merge_paragraph_lines(current))
                current = [line]
                continue

            current.append(line)
            paragraph_length = sum(len(item) for item in current)
            if paragraph_length >= self.settings.extraction_paragraph_limit:
                paragraphs.append(self._merge_paragraph_lines(current))
                current = []

        if current:
            paragraphs.append(self._merge_paragraph_lines(current))
        return paragraphs

    def _merge_paragraph_lines(self, lines: list[str]) -> str:
        return re.sub(r"\s+", " ", " ".join(lines)).strip()

    def _starts_new_paragraph(self, line: str, current: list[str]) -> bool:
        previous = current[-1]
        if previous.endswith(("。", ".", ";", "；", "!", "！", "?", "？", "：", ":")):
            return True
        if len(previous) <= 20 and not previous.endswith(("，", ",", "、", "及", "与", "和")):
            return True
        return False

    def _update_section_path(self, current_path: list[str], level: int, heading: str) -> list[str]:
        cleaned = heading[:255]
        if level == 1:
            return [cleaned]
        if level == 2:
            if not current_path:
                return [cleaned]
            return [current_path[0], cleaned]
        return current_path + [cleaned]

    def _heading_level(self, text: str) -> int | None:
        stripped = text.strip()
        if len(stripped) > 80:
            return None
        if any(pattern.match(stripped) for pattern in self._chapter_patterns):
            return 1
        if any(pattern.match(stripped) for pattern in self._section_patterns):
            return 2
        return None

    def _next_content_paragraph(self, paragraphs: list[str], start_index: int) -> str | None:
        for paragraph in paragraphs[start_index:]:
            if paragraph.strip():
                return paragraph
        return None

    def _is_standalone_heading_paragraph(self, text: str, next_paragraph: str | None) -> bool:
        stripped = text.strip()
        if len(stripped) < 8 or len(stripped) > 40:
            return False
        if next_paragraph is None or len(next_paragraph.strip()) < 16:
            return False
        if any(mark in stripped for mark in ("。", "；", "！", "？", ".", ";", "!", "?")):
            return False
        if stripped.endswith(("：", ":")):
            return False
        if self._contains_sentence_marker(stripped):
            return False
        if not re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9()（）·、/\-\s]+", stripped):
            return False
        return len(stripped) <= 24 or len(stripped) <= max(18, len(next_paragraph.strip()) // 2)

    def _contains_sentence_marker(self, text: str) -> bool:
        lowered = text.casefold()
        sentence_markers = (
            "是",
            "为",
            "有",
            "可",
            "会",
            "将",
            "包括",
            "位于",
            "表现为",
            "称为",
            "分为",
            "属于",
            "出现",
            "形成",
            "产生",
            "引起",
            "进入",
            "refers to",
            "defined as",
            "contains",
            "includes",
        )
        return any(marker in lowered for marker in sentence_markers)

    def _detect_printed_page_number(self, lines: list[str]) -> int | None:
        if not lines:
            return None

        edge_candidates = lines[:4] + lines[-4:]
        for line in edge_candidates:
            stripped = line.strip()
            if self._standalone_page_pattern.fullmatch(stripped):
                return int(stripped)
        return None

    def _normalize_line(self, line: str) -> str:
        line = line.replace("\u3000", " ")
        line = line.replace("\u2002", " ")
        line = line.replace("\u2003", " ")
        return re.sub(r"\s+", " ", line).strip()

    def _is_short_non_content(self, text: str) -> bool:
        return len(text.strip()) < 8

    def _is_noise_paragraph(self, text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return True
        if len(stripped) <= 3 and stripped.isdigit():
            return True
        if re.fullmatch(r"[0-9\s]+", stripped):
            return True
        if any(
            token in stripped
            for token in ("ISBN", "www.", "pmph.com", "定价", "购书热线", "CIP", "版权所有", "E-mail")
        ):
            return True
        weird_ratio = sum(
            1 for char in stripped if ord(char) < 32 and char not in ("\t", "\n", "\r")
        ) / len(stripped)
        return weird_ratio > 0.08
