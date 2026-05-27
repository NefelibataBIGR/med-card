from __future__ import annotations

import json
import re
from typing import Any

import httpx

from ..core.config import get_settings
from .text_extraction import ParagraphChunk


class MissingLLMConfigurationError(RuntimeError):
    pass


class LLMClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def validate_configuration(self) -> None:
        provider = self.settings.llm_provider.strip().lower()
        if provider != "mock" and not self.settings.llm_api_key:
            raise MissingLLMConfigurationError(
                "缺少 MED_CARD_LLM_API_KEY，请先在 .env 中完成配置后再导入 PDF。"
            )

    async def extract_cards(self, chunk: ParagraphChunk) -> list[dict[str, str]]:
        provider = self.settings.llm_provider.strip().lower()
        if provider == "mock":
            return self._extract_mock(chunk)
        self.validate_configuration()
        return await self._extract_openai_compatible(chunk)

    def _extract_mock(self, chunk: ParagraphChunk) -> list[dict[str, str]]:
        paragraph = " ".join(chunk.text.split())
        if len(paragraph) < 16:
            return []

        concept_name, english_name, summary = self._infer_concept_from_paragraph(paragraph)
        if not concept_name or not summary:
            return []

        return [
            {
                "concept_name": concept_name,
                "english_name": english_name,
                "summary": summary,
                "chapter": chunk.section_path,
                "page_number": str(chunk.page_number),
                "source_excerpt": chunk.text[: self.settings.source_excerpt_limit],
            }
        ]

    async def _extract_openai_compatible(self, chunk: ParagraphChunk) -> list[dict[str, str]]:
        prompt = (
            "You extract one medical concept revision card from a single textbook paragraph. "
            "Return strict JSON only. "
            "Prefer a top-level object with a cards array. "
            "Do not create cards for chapter or section headings. "
            "Do not use chapter titles, section titles, subsection titles, or heading labels as the concept itself. "
            "If a paragraph starts with a heading label, ignore that label and extract from the explanatory body only. "
            "If the input is only a heading or lacks explanatory body text, return an empty cards array. "
            "At most one card should be returned. "
            "The card must represent the main anatomical or medical concept introduced in the paragraph. "
            "Each item must include concept_name, english_name, summary, chapter, page_number, and source_excerpt. "
            "english_name may be empty if absent. "
            "summary should be a concise concept introduction under 180 Chinese characters and should not repeat the title. "
            "source_excerpt should be copied from the paragraph rather than invented."
        )
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        f"Section path: {chunk.section_path}\n"
                        f"PDF page: {chunk.page_number}\n"
                        f"Paragraph:\n{chunk.text}"
                    ),
                },
            ],
        }
        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}"}
        url = f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()

        body = response.json()
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        raw_cards = parsed.get("cards", []) if isinstance(parsed, dict) else parsed
        if not isinstance(raw_cards, list):
            raise ValueError("LLM response does not contain a valid card list.")

        normalized: list[dict[str, str]] = []
        for item in raw_cards[:1]:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "concept_name": str(item.get("concept_name", "")).strip(),
                    "english_name": str(item.get("english_name", "")).strip(),
                    "summary": str(item.get("summary", "")).strip(),
                    "chapter": str(item.get("chapter", "")).strip(),
                    "page_number": str(item.get("page_number", "")).strip(),
                    "source_excerpt": str(item.get("source_excerpt", "")).strip(),
                }
            )
        return normalized

    def _infer_concept_from_paragraph(self, paragraph: str) -> tuple[str, str, str]:
        normalized = " ".join(paragraph.split())
        match = self._match_bilingual_title(normalized)
        if match:
            concept_name = match.group("cn").strip(" ，,：:;；。")
            english_name = match.group("en").strip()
            summary = match.group("body").strip(" ，,：:;；。")
            return (
                concept_name[:255],
                english_name[:255],
                summary[: self.settings.extraction_summary_limit],
            )

        match = re.match(
            r"^(?P<cn>[\u4e00-\u9fffA-Za-z0-9（）()·\-]{2,40})[：: ]+(?P<body>.+)$",
            normalized,
        )
        if match:
            concept_name = match.group("cn").strip(" ，,：:;；。")
            summary = match.group("body").strip(" ，,：:;；。")
            return concept_name[:255], "", summary[: self.settings.extraction_summary_limit]

        pieces = re.split(r"[，,。；; ]", normalized, maxsplit=1)
        concept_name = pieces[0].strip(" ，,：:;；。")[:255]
        summary = normalized[len(pieces[0]) :].strip(" ，,：:;；。")[: self.settings.extraction_summary_limit]
        return concept_name, "", summary

    def _match_bilingual_title(self, text: str):
        return re.match(
            r"^(?P<cn>[\u4e00-\u9fffA-Za-z0-9（）()·\-]{2,40})\s+"
            r"(?P<en>[A-Za-z][A-Za-z\s\-,'()/]{2,80})\s+"
            r"(?P<body>.+)$",
            text,
        )
