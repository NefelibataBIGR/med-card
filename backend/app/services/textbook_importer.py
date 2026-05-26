from __future__ import annotations

from difflib import SequenceMatcher
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..models import (
    Card,
    CardStatus,
    ImportChunkFailure,
    ReviewAction,
    ReviewLog,
    Textbook,
    TextbookStatus,
    utc_now,
)
from .llm import LLMClient
from .text_extraction import TextExtractionError, TextLayerChunkExtractor


@dataclass
class ImportResult:
    textbook: Textbook
    imported_cards: int
    skipped_cards: int


@dataclass
class RetryResult:
    textbook: Textbook
    failure: ImportChunkFailure
    imported_cards: int
    skipped_cards: int


@dataclass
class RetryBatchResult:
    textbook: Textbook
    retried_count: int
    resolved_count: int
    remaining_failures: int


class ImportErrorWithMessage(RuntimeError):
    pass


class TextbookImporter:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.llm = LLMClient()
        self.text_extractor = TextLayerChunkExtractor()

    def create_import(self, upload: UploadFile) -> Textbook:
        if not upload.filename or not upload.filename.lower().endswith(".pdf"):
            raise ImportErrorWithMessage("一次只能导入一个 PDF 文件。")

        self.llm.validate_configuration()

        uploads_dir = Path(self.settings.uploads_dir)
        uploads_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex}_{Path(upload.filename).name}"
        stored_path = uploads_dir / stored_name
        with stored_path.open("wb") as destination:
            shutil.copyfileobj(upload.file, destination)

        textbook = Textbook(
            filename=upload.filename,
            stored_path=str(stored_path),
            status=TextbookStatus.pending,
            summary="教材已加入导入队列。",
            skipped_cards=0,
            total_chunks=0,
            processed_chunks=0,
            failed_chunks=0,
        )
        self.db.add(textbook)
        self.db.commit()
        self.db.refresh(textbook)
        return textbook

    async def process_textbook(self, textbook_id: int) -> ImportResult:
        textbook = self.db.get(Textbook, textbook_id)
        if textbook is None:
            raise ImportErrorWithMessage("未找到教材导入记录。")

        textbook.status = TextbookStatus.processing
        textbook.error_message = None
        textbook.summary = "正在从 PDF 提取文本。"
        textbook.processed_chunks = 0
        textbook.failed_chunks = 0
        textbook.card_count = 0
        textbook.skipped_cards = 0
        self.db.query(ImportChunkFailure).filter(ImportChunkFailure.textbook_id == textbook.id).delete()
        self.db.commit()

        imported_cards = 0
        skipped_cards = 0
        try:
            chunks = self.text_extractor.extract_chunks(Path(textbook.stored_path))
            textbook.total_chunks = len(chunks)
            textbook.summary = f"正在处理 {len(chunks)} 个文本块。"
            self.db.commit()

            for chunk_index, chunk in enumerate(chunks, start=1):
                imported, skipped = await self._process_chunk(textbook, chunk_index, chunk)
                imported_cards += imported
                skipped_cards += skipped

                textbook.processed_chunks = chunk_index
                textbook.card_count = imported_cards
                textbook.skipped_cards = skipped_cards
                textbook.summary = (
                    f"已处理 {textbook.processed_chunks}/{textbook.total_chunks} 个文本块，"
                    f"生成 {imported_cards} 张卡片，跳过 {skipped_cards} 条。"
                )
                self.db.commit()

            textbook.processed_at = utc_now()
            textbook.card_count = imported_cards
            textbook.skipped_cards = skipped_cards
            if textbook.failed_chunks:
                textbook.status = TextbookStatus.failed
                textbook.error_message = f"{textbook.failed_chunks} 个文本块抽取失败。"
                textbook.summary = (
                    f"导入完成，但有部分失败：生成 {imported_cards} 张卡片，"
                    f"跳过 {skipped_cards} 条，失败 {textbook.failed_chunks} 个文本块。"
                )
            else:
                textbook.status = TextbookStatus.completed
                textbook.error_message = None
                textbook.summary = (
                    f"导入完成：共处理 {textbook.total_chunks} 个文本块，"
                    f"生成 {imported_cards} 张卡片，跳过 {skipped_cards} 条。"
                )
            self.db.commit()
            self.db.refresh(textbook)
            return ImportResult(textbook=textbook, imported_cards=imported_cards, skipped_cards=skipped_cards)
        except TextExtractionError as exc:
            textbook.status = TextbookStatus.failed
            textbook.processed_at = utc_now()
            textbook.error_message = str(exc)
            textbook.summary = "文本提取阶段失败。"
            self.db.commit()
            raise ImportErrorWithMessage(str(exc)) from exc
        except Exception as exc:
            textbook.status = TextbookStatus.failed
            textbook.processed_at = utc_now()
            textbook.error_message = str(exc)
            textbook.summary = "导入在文本块处理完成前失败。"
            self.db.commit()
            raise

    async def retry_failure(self, failure_id: int) -> RetryResult:
        failure = self.db.get(ImportChunkFailure, failure_id)
        if failure is None:
            raise ImportErrorWithMessage("未找到失败文本块记录。")
        if failure.resolved:
            raise ImportErrorWithMessage("该失败文本块已经处理完成。")

        textbook = self.db.get(Textbook, failure.textbook_id)
        if textbook is None:
            raise ImportErrorWithMessage("未找到教材导入记录。")

        try:
            imported_cards, skipped_cards = await self._process_chunk(
                textbook,
                failure.chunk_index,
                failure.chunk_text or failure.chunk_excerpt,
                failure,
            )
        except ImportErrorWithMessage as exc:
            self.db.refresh(failure)
            failure.retry_count += 1
            failure.error_message = str(exc)
            failure.updated_at = utc_now()
            self.db.commit()
            raise

        self.db.refresh(failure)
        failure.retry_count += 1
        failure.resolved = True
        failure.error_message = "已通过手动重试恢复。"
        failure.updated_at = utc_now()
        self.db.flush()

        unresolved_failures = list(
            self.db.scalars(
                select(ImportChunkFailure).where(
                    ImportChunkFailure.textbook_id == textbook.id,
                    ImportChunkFailure.resolved.is_(False),
                )
            ).all()
        )
        textbook.failed_chunks = len(unresolved_failures)
        textbook.card_count += imported_cards
        textbook.skipped_cards += skipped_cards
        if textbook.failed_chunks == 0:
            textbook.status = TextbookStatus.completed
            textbook.error_message = None
            textbook.summary = (
                f"所有失败文本块已恢复，当前共生成 {textbook.card_count} 张卡片，"
                f"跳过 {textbook.skipped_cards} 条。"
            )
        else:
            textbook.status = TextbookStatus.failed
            textbook.error_message = f"仍有 {textbook.failed_chunks} 个文本块需要重试。"
            textbook.summary = (
                f"已重试 1 个失败文本块，仍剩 {textbook.failed_chunks} 个待处理，"
                f"当前共生成 {textbook.card_count} 张卡片。"
            )

        self.db.add(
            ReviewLog(
                card_id=None,
                session_id=f"textbook:{textbook.id}",
                action=ReviewAction.retry_import_chunk,
                note=f"retry failure {failure.id}",
            )
        )
        self.db.commit()
        self.db.refresh(textbook)
        self.db.refresh(failure)
        return RetryResult(
            textbook=textbook,
            failure=failure,
            imported_cards=imported_cards,
            skipped_cards=skipped_cards,
        )

    async def retry_all_failures(self, textbook_id: int) -> RetryBatchResult:
        textbook = self.db.get(Textbook, textbook_id)
        if textbook is None:
            raise ImportErrorWithMessage("未找到教材导入记录。")

        failures = self.list_failures(textbook_id)
        retried_count = 0
        resolved_count = 0

        for failure in failures:
            retried_count += 1
            try:
                result = await self.retry_failure(failure.id)
            except ImportErrorWithMessage:
                continue
            if result.failure.resolved:
                resolved_count += 1

        self.db.refresh(textbook)
        return RetryBatchResult(
            textbook=textbook,
            retried_count=retried_count,
            resolved_count=resolved_count,
            remaining_failures=textbook.failed_chunks,
        )

    def list_failures(self, textbook_id: int) -> list[ImportChunkFailure]:
        stmt = select(ImportChunkFailure).where(
            ImportChunkFailure.textbook_id == textbook_id,
            ImportChunkFailure.resolved.is_(False),
        )
        return list(self.db.scalars(stmt.order_by(ImportChunkFailure.chunk_index.asc())).all())

    async def _process_chunk(
        self,
        textbook: Textbook,
        chunk_index: int,
        chunk: str,
        failure: ImportChunkFailure | None = None,
    ) -> tuple[int, int]:
        try:
            raw_cards = await self.llm.extract_cards(chunk)
            return self._persist_cards(textbook, raw_cards)
        except Exception as exc:
            if failure is None:
                self.db.add(
                    ImportChunkFailure(
                        textbook_id=textbook.id,
                        chunk_index=chunk_index,
                        chunk_text=chunk,
                        chunk_excerpt=chunk[:1000],
                        error_message=str(exc),
                    )
                )
                textbook.failed_chunks += 1
                self.db.commit()
                return 0, 0
            raise ImportErrorWithMessage(str(exc)) from exc

    def _persist_cards(self, textbook: Textbook, raw_cards: list[dict[str, str]]) -> tuple[int, int]:
        imported = 0
        skipped = 0
        local_seen: dict[str, list[str]] = {}
        existing_by_chapter: dict[str, list[str]] = {}
        for raw_card in raw_cards:
            cleaned = self._clean_card(raw_card)
            if not cleaned:
                skipped += 1
                continue
            chapter_key = cleaned["chapter"].casefold()
            local_candidates = local_seen.setdefault(chapter_key, [])
            if any(self._is_similar_concept(cleaned["concept_name"], candidate) for candidate in local_candidates):
                skipped += 1
                continue
            existing_candidates = existing_by_chapter.setdefault(
                chapter_key,
                self._load_existing_concepts(textbook.id, cleaned["chapter"]),
            )
            if any(self._is_similar_concept(cleaned["concept_name"], candidate) for candidate in existing_candidates):
                skipped += 1
                continue
            local_candidates.append(cleaned["concept_name"])
            existing_candidates.append(cleaned["concept_name"])
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

    def _load_existing_concepts(self, textbook_id: int, chapter: str) -> list[str]:
        stmt = select(Card.concept_name).where(
            Card.textbook_id == textbook_id,
            Card.chapter == chapter,
            Card.is_deleted.is_(False),
        )
        return list(self.db.scalars(stmt).all())

    def _is_similar_concept(self, left: str, right: str) -> bool:
        normalized_left = self._normalize_concept(left)
        normalized_right = self._normalize_concept(right)
        if not normalized_left or not normalized_right:
            return False
        if normalized_left == normalized_right:
            return True
        if (
            min(len(normalized_left), len(normalized_right)) >= 4
            and (normalized_left in normalized_right or normalized_right in normalized_left)
        ):
            return True
        return SequenceMatcher(a=normalized_left, b=normalized_right).ratio() >= 0.88

    def _normalize_concept(self, value: str) -> str:
        return re.sub(r"[\W_]+", "", value).casefold()
