from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models import Card, ImportChunkFailure, Textbook, TextbookStatus
from app.services.textbook_importer import ImportErrorWithMessage, TextbookImporter
from app.services.text_extraction import TextExtractionError


def build_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_process_textbook_dedupes_and_keeps_partial_success_on_chunk_failure(monkeypatch) -> None:
    db = build_session()
    importer = TextbookImporter(db)

    textbook = Textbook(
        filename="sample.pdf",
        stored_path="sample.pdf",
        status=TextbookStatus.pending,
        summary="queued",
    )
    db.add(textbook)
    db.commit()
    db.refresh(textbook)

    monkeypatch.setattr(importer.text_extractor, "extract_chunks", lambda _path: ["chunk-1", "chunk-2"])

    async def fake_extract_cards(chunk: str) -> list[dict[str, str]]:
        if chunk == "chunk-1":
            return [
                {
                    "concept_name": "Renal clearance",
                    "summary": "The virtual plasma volume cleared of a substance per unit time.",
                    "chapter": "Nephrology",
                    "source_excerpt": "Clearance estimates renal excretion efficiency.",
                },
                {
                    "concept_name": "Renal clearance",
                    "summary": "Duplicate concept in the same chapter should be skipped.",
                    "chapter": "Nephrology",
                    "source_excerpt": "Duplicate entry",
                },
            ]
        raise RuntimeError("mock batch failure")

    monkeypatch.setattr(importer.llm, "extract_cards", fake_extract_cards)

    import anyio

    result = anyio.run(importer.process_textbook, textbook.id)

    cards = list(db.scalars(select(Card)).all())
    assert len(cards) == 1
    assert result.imported_cards == 1
    assert result.skipped_cards == 1

    textbook = db.get(Textbook, textbook.id)
    assert textbook is not None
    assert textbook.status == TextbookStatus.failed
    assert textbook.card_count == 1
    assert textbook.skipped_cards == 1
    assert textbook.total_chunks == 2
    assert textbook.processed_chunks == 2
    assert textbook.failed_chunks == 1

    failures = list(db.scalars(select(ImportChunkFailure)).all())
    assert len(failures) == 1
    assert failures[0].error_message == "mock batch failure"


def test_process_textbook_skips_highly_similar_concepts(monkeypatch) -> None:
    db = build_session()
    importer = TextbookImporter(db)

    textbook = Textbook(
        filename="similar.pdf",
        stored_path="similar.pdf",
        status=TextbookStatus.pending,
        summary="queued",
    )
    db.add(textbook)
    db.commit()
    db.refresh(textbook)

    monkeypatch.setattr(importer.text_extractor, "extract_chunks", lambda _path: ["chunk-1"])

    async def fake_extract_cards(_chunk: str) -> list[dict[str, str]]:
        return [
            {
                "concept_name": "Cardiac output",
                "summary": "Blood pumped by a ventricle per minute.",
                "chapter": "Circulation",
                "source_excerpt": "Definition one.",
            },
            {
                "concept_name": "cardiac-output",
                "summary": "Same concept with punctuation variance.",
                "chapter": "Circulation",
                "source_excerpt": "Definition two.",
            },
        ]

    monkeypatch.setattr(importer.llm, "extract_cards", fake_extract_cards)

    import anyio

    result = anyio.run(importer.process_textbook, textbook.id)

    cards = list(db.scalars(select(Card)).all())
    assert len(cards) == 1
    assert result.imported_cards == 1
    assert result.skipped_cards == 1


def test_process_textbook_marks_text_extraction_failure(monkeypatch) -> None:
    db = build_session()
    importer = TextbookImporter(db)

    textbook = Textbook(
        filename="missing-text-layer.pdf",
        stored_path="missing-text-layer.pdf",
        status=TextbookStatus.pending,
        summary="queued",
    )
    db.add(textbook)
    db.commit()
    db.refresh(textbook)

    monkeypatch.setattr(
        importer.text_extractor,
        "extract_chunks",
        lambda _path: (_ for _ in ()).throw(TextExtractionError("no text layer")),
    )

    import anyio

    with pytest.raises(ImportErrorWithMessage, match="no text layer"):
        anyio.run(importer.process_textbook, textbook.id)

    refreshed = db.get(Textbook, textbook.id)
    assert refreshed is not None
    assert refreshed.status == TextbookStatus.failed
    assert refreshed.error_message == "no text layer"
    assert refreshed.summary == "文本提取阶段失败。"
    assert refreshed.processed_at is not None


def test_process_textbook_cleans_and_drops_invalid_cards(monkeypatch) -> None:
    db = build_session()
    importer = TextbookImporter(db)

    textbook = Textbook(
        filename="cleaning.pdf",
        stored_path="cleaning.pdf",
        status=TextbookStatus.pending,
        summary="queued",
    )
    db.add(textbook)
    db.commit()
    db.refresh(textbook)

    monkeypatch.setattr(importer.text_extractor, "extract_chunks", lambda _path: ["chunk-1"])

    async def fake_extract_cards(_chunk: str) -> list[dict[str, str]]:
        return [
            {
                "concept_name": "   ",
                "summary": "too short",
                "chapter": "General",
                "source_excerpt": "missing concept should be dropped",
            },
            {
                "concept_name": "C" * 400,
                "summary": "S" * (importer.settings.extraction_summary_limit + 50),
                "chapter": "",
                "source_excerpt": "E" * (importer.settings.source_excerpt_limit + 50),
            },
        ]

    monkeypatch.setattr(importer.llm, "extract_cards", fake_extract_cards)

    import anyio

    result = anyio.run(importer.process_textbook, textbook.id)

    cards = list(db.scalars(select(Card)).all())
    assert result.imported_cards == 1
    assert result.skipped_cards == 1
    assert len(cards) == 1

    card = cards[0]
    assert len(card.concept_name) == 255
    assert len(card.summary) == importer.settings.extraction_summary_limit
    assert card.chapter == "Uncategorized"
    assert len(card.source_excerpt) == importer.settings.source_excerpt_limit


def test_retry_failure_resolves_queue_and_updates_textbook(monkeypatch) -> None:
    db = build_session()
    importer = TextbookImporter(db)

    textbook = Textbook(
        filename="retry.pdf",
        stored_path="retry.pdf",
        status=TextbookStatus.pending,
        summary="queued",
    )
    db.add(textbook)
    db.commit()
    db.refresh(textbook)

    monkeypatch.setattr(importer.text_extractor, "extract_chunks", lambda _path: ["chunk-1", "chunk-2"])

    async def failing_extract(chunk: str) -> list[dict[str, str]]:
        if chunk == "chunk-1":
            return [
                {
                    "concept_name": "Stroke volume",
                    "summary": "Volume ejected by a ventricle in one beat.",
                    "chapter": "Circulation",
                    "source_excerpt": "Definition one.",
                }
            ]
        raise RuntimeError("temporary failure")

    monkeypatch.setattr(importer.llm, "extract_cards", failing_extract)

    import anyio

    anyio.run(importer.process_textbook, textbook.id)

    failure = db.scalars(select(ImportChunkFailure)).one()

    async def success_extract(_chunk: str) -> list[dict[str, str]]:
        return [
            {
                "concept_name": "Minute ventilation",
                "summary": "Total air entering or leaving the lungs each minute.",
                "chapter": "Respiration",
                "source_excerpt": "Definition two.",
            }
        ]

    monkeypatch.setattr(importer.llm, "extract_cards", success_extract)
    result = anyio.run(importer.retry_failure, failure.id)

    assert result.imported_cards == 1
    assert result.skipped_cards == 0

    refreshed_failure = db.get(ImportChunkFailure, failure.id)
    assert refreshed_failure is not None
    assert refreshed_failure.resolved is True
    assert refreshed_failure.retry_count == 1

    refreshed_textbook = db.get(Textbook, textbook.id)
    assert refreshed_textbook is not None
    assert refreshed_textbook.status == TextbookStatus.completed
    assert refreshed_textbook.failed_chunks == 0
    assert refreshed_textbook.card_count == 2
    assert refreshed_textbook.error_message is None


def test_retry_failure_keeps_failure_open_when_retry_fails(monkeypatch) -> None:
    db = build_session()
    importer = TextbookImporter(db)

    textbook = Textbook(
        filename="retry-fail.pdf",
        stored_path="retry-fail.pdf",
        status=TextbookStatus.pending,
        summary="queued",
    )
    db.add(textbook)
    db.commit()
    db.refresh(textbook)

    monkeypatch.setattr(importer.text_extractor, "extract_chunks", lambda _path: ["chunk-1", "chunk-2"])

    async def failing_extract(chunk: str) -> list[dict[str, str]]:
        if chunk == "chunk-1":
            return [
                {
                    "concept_name": "Cardiac reserve",
                    "summary": "Ability of the heart to increase output above resting level.",
                    "chapter": "Circulation",
                    "source_excerpt": "Definition one.",
                }
            ]
        raise RuntimeError("initial failure")

    monkeypatch.setattr(importer.llm, "extract_cards", failing_extract)

    import anyio

    anyio.run(importer.process_textbook, textbook.id)
    failure = db.scalars(select(ImportChunkFailure)).one()

    async def retry_fail(_chunk: str) -> list[dict[str, str]]:
        raise RuntimeError("retry failed again")

    monkeypatch.setattr(importer.llm, "extract_cards", retry_fail)

    with pytest.raises(ImportErrorWithMessage):
        anyio.run(importer.retry_failure, failure.id)

    refreshed_failure = db.get(ImportChunkFailure, failure.id)
    assert refreshed_failure is not None
    assert refreshed_failure.resolved is False
    assert refreshed_failure.retry_count == 1
    assert refreshed_failure.error_message == "retry failed again"


def test_retry_all_failures_resolves_multiple_chunks(monkeypatch) -> None:
    db = build_session()
    importer = TextbookImporter(db)

    textbook = Textbook(
        filename="retry-all.pdf",
        stored_path="retry-all.pdf",
        status=TextbookStatus.pending,
        summary="queued",
    )
    db.add(textbook)
    db.commit()
    db.refresh(textbook)

    monkeypatch.setattr(importer.text_extractor, "extract_chunks", lambda _path: ["chunk-1", "chunk-2", "chunk-3"])

    async def failing_extract(chunk: str) -> list[dict[str, str]]:
        if chunk == "chunk-1":
            return [
                {
                    "concept_name": "Baseline concept",
                    "summary": "Baseline concept summary for successful chunk.",
                    "chapter": "General",
                    "source_excerpt": "chunk one",
                }
            ]
        raise RuntimeError(f"failed {chunk}")

    monkeypatch.setattr(importer.llm, "extract_cards", failing_extract)

    import anyio

    anyio.run(importer.process_textbook, textbook.id)

    async def success_extract(chunk: str) -> list[dict[str, str]]:
        return [
            {
                "concept_name": f"Recovered {chunk}",
                "summary": "Recovered summary for failed chunk.",
                "chapter": "Recovered",
                "source_excerpt": chunk,
            }
        ]

    monkeypatch.setattr(importer.llm, "extract_cards", success_extract)
    result = anyio.run(importer.retry_all_failures, textbook.id)

    assert result.retried_count == 2
    assert result.resolved_count == 2
    assert result.remaining_failures == 0

    refreshed_textbook = db.get(Textbook, textbook.id)
    assert refreshed_textbook is not None
    assert refreshed_textbook.status == TextbookStatus.completed


def test_retry_failure_uses_full_chunk_text_not_truncated_excerpt(monkeypatch) -> None:
    db = build_session()
    importer = TextbookImporter(db)

    textbook = Textbook(
        filename="retry-full-chunk.pdf",
        stored_path="retry-full-chunk.pdf",
        status=TextbookStatus.pending,
        summary="queued",
    )
    db.add(textbook)
    db.commit()
    db.refresh(textbook)

    full_chunk = "A" * 1200 + " FULL-ONLY-CONTENT"
    excerpt = full_chunk[:1000]

    db.add(
        ImportChunkFailure(
            textbook_id=textbook.id,
            chunk_index=1,
            chunk_text=full_chunk,
            chunk_excerpt=excerpt,
            error_message="temporary failure",
        )
    )
    textbook.status = TextbookStatus.failed
    textbook.failed_chunks = 1
    db.commit()

    async def extract_cards(chunk: str) -> list[dict[str, str]]:
        assert chunk == full_chunk
        return [
            {
                "concept_name": "Recovered concept",
                "summary": "Recovered summary for the full failed chunk.",
                "chapter": "Recovered",
                "source_excerpt": "Recovered from the stored full chunk.",
            }
        ]

    monkeypatch.setattr(importer.llm, "extract_cards", extract_cards)

    import anyio

    failure = db.scalars(select(ImportChunkFailure)).one()
    result = anyio.run(importer.retry_failure, failure.id)

    assert result.imported_cards == 1
    refreshed_failure = db.get(ImportChunkFailure, failure.id)
    assert refreshed_failure is not None
    assert refreshed_failure.resolved is True
