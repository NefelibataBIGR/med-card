from __future__ import annotations

import json
from typing import Any

import httpx

from ..core.config import get_settings


class MissingLLMConfigurationError(RuntimeError):
    pass


class LLMClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def validate_configuration(self) -> None:
        provider = self.settings.llm_provider.strip().lower()
        if provider != "mock" and not self.settings.llm_api_key:
            raise MissingLLMConfigurationError(
                "MED_CARD_LLM_API_KEY is missing. Set it in .env before importing PDFs."
            )

    async def extract_cards(self, chunk: str) -> list[dict[str, str]]:
        provider = self.settings.llm_provider.strip().lower()
        if provider == "mock":
            return self._extract_mock(chunk)
        self.validate_configuration()
        return await self._extract_openai_compatible(chunk)

    def _extract_mock(self, chunk: str) -> list[dict[str, str]]:
        cards: list[dict[str, str]] = []
        chapter = "Uncategorized"
        chapter_tokens = ("\u7b2c", "\u7ae0", "\u8282")
        trim_chars = "\uff1a:;\uff1b\uff0c,\u3002 "

        for raw_line in chunk.splitlines():
            line = " ".join(raw_line.split())
            if not line:
                continue
            if len(line) <= 40 and any(token in line for token in chapter_tokens):
                chapter = line[:255]
                continue
            if len(line) < 30:
                continue
            concept_name = line[:32].strip(trim_chars)
            summary = line[: self.settings.extraction_summary_limit]
            cards.append(
                {
                    "concept_name": concept_name or "Untitled Concept",
                    "summary": summary,
                    "chapter": chapter,
                    "source_excerpt": line[: self.settings.source_excerpt_limit],
                }
            )
            if len(cards) >= 12:
                break
        return cards

    async def _extract_openai_compatible(self, chunk: str) -> list[dict[str, str]]:
        prompt = (
            "You extract revision cards from medical textbook text. "
            "Return strict JSON only. "
            "Prefer a top-level object with a cards array. "
            "Each item must include concept_name, summary, chapter, and source_excerpt as strings. "
            "Keep summary concise and under 180 Chinese characters."
        )
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Textbook excerpt:\n{chunk}"},
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
        for item in raw_cards:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "concept_name": str(item.get("concept_name", "")).strip(),
                    "summary": str(item.get("summary", "")).strip(),
                    "chapter": str(item.get("chapter", "")).strip(),
                    "source_excerpt": str(item.get("source_excerpt", "")).strip(),
                }
            )
        return normalized
