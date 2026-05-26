from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fastapi import UploadFile
from pypdf import PdfReader
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..models import Card, CardStatus, Textbook, TextbookStatus, utc_now
from .llm import LLMClient


@dataclass
class ImportResult:
    textbook: Textbook
    imported_cards: int
    skipped_cards: int


class ImportErrorWithMessage(RuntimeError):
    pass


class TextbookImporter:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.llm = LLMClient()

    async def import_pdf(self, upload: UploadFile) -> ImportResult:
        if not upload.filename or not upload.filename.lower().endswith(".pdf"):
            raise ImportErrorWithMessage("Only a single PDF file can be imported.")

        uploads_dir = Path(self.settings.uploads_dir)
        uploads_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex}_{Path(upload.filename).name}"
        stored_path = uploads_dir / stored_name
        with stored_path.open("wb") as destination:
            shutil.copyfileobj(upload.file, destination)

        textbook = Textbook(
            filename=upload.filename,
            stored_path=str(stored_path),
            status=TextbookStatus.processing,
        )
        self.db.add(textbook)
        self.db.commit()
        self.db.refresh(textbook)

        imported_cards = 0
        skipped_cards = 0
        try:
            chunks = self._extract_chunks(stored_path)
            for chunk in chunks:
                imported, skipped = self._persist_cards(textbook, await self.llm.extract_cards(chunk))
                imported_cards += imported
                skipped_cards += skipped
            textbook.status = TextbookStatus.completed
            textbook.processed_at = utc_now()
            textbook.card_count = imported_cards
            textbook.summary = f"Imported {len(chunks)} chunks and created {imported_cards} cards."
            textbook.error_message = None
            self.db.commit()
            self.db.refresh(textbook)
            return ImportResult(textbook=textbook, imported_cards=imported_cards, skipped_cards=skipped_cards)
        except Exception as exc:
            textbook.status = TextbookStatus.failed
            textbook.error_message = str(exc)
            self.db.commit()
            raise

    def _extract_chunks(self, pdf_path: Path) -> list[str]:
        reader = PdfReader(str(pdf_path))
        pages: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            normalized = re.sub(r"\s+", " ", text).strip()
            if normalized:
                pages.append(normalized)
        if not pages:
            raise ImportErrorWithMessage("No text layer was found in the PDF. OCR is not implemented in this version.")

        chunks: list[str] = []
        buffer: list[str] = []
        size = 0
        for page_text in pages:
            if buffer and size + len(page_text) > self.settings.extraction_chunk_size:
                chunks.append("\n".join(buffer))
                buffer = [page_text]
                size = len(page_text)
            else:
                buffer.append(page_text)
                size += len(page_text)
        if buffer:
            chunks.append("\n".join(buffer))
        return chunks

    def _persist_cards(self, textbook: Textbook, raw_cards: list[dict[str, str]]) -> tuple[int, int]:
        imported = 0
        skipped = 0
        local_seen: set[tuple[str, str]] = set()
        for raw_card in raw_cards:
            cleaned = self._clean_card(raw_card)
            if not cleaned:
                skipped += 1
                continue
            key = (cleaned["chapter"].casefold(), cleaned["concept_name"].casefold())
            if key in local_seen:
                skipped += 1
                continue
            duplicate_stmt = select(func.count()).select_from(Card).where(
                Card.textbook_id == textbook.id,
                Card.chapter == cleaned["chapter"],
                func.lower(Card.concept_name) == cleaned["concept_name"].lower(),
                Card.is_deleted.is_(False),
            )
            if self.db.scalar(duplicate_stmt):
                skipped += 1
                continue
            local_seen.add(key)
            self.db.add(Card(textbook_id=textbook.id, status=CardStatus.new, **cleaned))
            imported += 1
        self.db.commit()
        return imported, skipped

    def _clean_card(self, raw_card: dict[str, str]) -> dict[str, str] | None:
        concept_name = " ".join(raw_card.get("concept_name", "").split())[:255]
        summary = " ".join(raw_card.get("summary", "").split())[: self.settings.extraction_summary_limit]
        chapter = " ".join(raw_card.get("chapter", "").split())[:255] or "Uncategorized"
        source_excerpt = " ".join(raw_card.get("source_excerpt", "").split())[: self.settings.source_excerpt_limit]
        if not concept_name or not summary or len(summary) < 8:
            return None
        if not source_excerpt:
            source_excerpt = summary
        return {
            "concept_name": concept_name,
            "summary": summary,
            "chapter": chapter,
            "source_excerpt": source_excerpt,
        }
