from __future__ import annotations

from io import BytesIO
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from fastapi import UploadFile

from app.core.database import Base
from app.models import Card, ImportChunkFailure, Textbook, TextbookStatus
from app.services.textbook_importer import ImportErrorWithMessage, TextbookImporter
from app.services.text_extraction import ParagraphChunk


def build_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_process_textbook_merges_duplicate_cards_and_keeps_partial_success_on_chunk_failure(monkeypatch) -> None:
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

    monkeypatch.setattr(
        importer.text_extractor,
        "extract_chunks",
        lambda _path: [
            ParagraphChunk(index=1, page_number=12, section_path="Nephrology", text="chunk-1"),
            ParagraphChunk(index=2, page_number=13, section_path="Nephrology", text="chunk-2"),
        ],
    )

    async def fake_extract_cards(chunk: ParagraphChunk) -> list[dict[str, str]]:
        if chunk.text == "chunk-1":
            return [
                {
                    "concept_name": "Renal clearance",
                    "summary": "The virtual plasma volume cleared of a substance per unit time.",
                    "chapter": "Nephrology",
                    "source_excerpt": "Clearance estimates renal excretion efficiency.",
                },
                {
                    "concept_name": "Renal clearance",
                    "summary": "Duplicate concept in the same chapter should be merged.",
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
    assert result.skipped_cards == 0
    assert cards[0].page_number == 12
    assert "Duplicate concept in the same chapter should be merged." in cards[0].summary
    assert "Duplicate entry" in cards[0].source_excerpt

    textbook = db.get(Textbook, textbook.id)
    assert textbook is not None
    assert textbook.status == TextbookStatus.failed
    assert textbook.card_count == 1
    assert textbook.skipped_cards == 0
    assert textbook.total_chunks == 2
    assert textbook.processed_chunks == 2
    assert textbook.failed_chunks == 1

    failures = list(db.scalars(select(ImportChunkFailure)).all())
    assert len(failures) == 1
    assert failures[0].error_message == "mock batch failure"


def test_process_textbook_merges_highly_similar_concepts(monkeypatch) -> None:
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

    monkeypatch.setattr(
        importer.text_extractor,
        "extract_chunks",
        lambda _path: [ParagraphChunk(index=1, page_number=21, section_path="Circulation", text="chunk-1")],
    )

    async def fake_extract_cards(_chunk: ParagraphChunk) -> list[dict[str, str]]:
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
    assert result.skipped_cards == 0
    assert cards[0].page_number == 21
    assert "Same concept with punctuation variance." in cards[0].summary
    assert "Definition two." in cards[0].source_excerpt


def test_process_textbook_merges_duplicate_names_across_chapters(monkeypatch) -> None:
    db = build_session()
    importer = TextbookImporter(db)

    textbook = Textbook(
        filename="merge-cross-chapter.pdf",
        stored_path="merge-cross-chapter.pdf",
        status=TextbookStatus.pending,
        summary="queued",
    )
    db.add(textbook)
    db.commit()
    db.refresh(textbook)

    monkeypatch.setattr(
        importer.text_extractor,
        "extract_chunks",
        lambda _path: [
            ParagraphChunk(index=1, page_number=31, section_path="Circulation", text="chunk-1"),
            ParagraphChunk(index=2, page_number=42, section_path="Emergency", text="chunk-2"),
        ],
    )

    async def fake_extract_cards(chunk: ParagraphChunk) -> list[dict[str, str]]:
        if chunk.text == "chunk-1":
            return [
                {
                    "concept_name": "Shock",
                    "summary": "A state of inadequate tissue perfusion.",
                    "chapter": "Circulation",
                    "page_number": "31",
                    "source_excerpt": "Shock reduces effective tissue perfusion.",
                }
            ]
        return [
            {
                "concept_name": "Shock",
                "summary": "Clinical management focuses on reversing the underlying cause.",
                "chapter": "Emergency",
                "page_number": "42",
                "source_excerpt": "Shock treatment targets the cause and supports perfusion.",
            }
        ]

    monkeypatch.setattr(importer.llm, "extract_cards", fake_extract_cards)

    import anyio

    result = anyio.run(importer.process_textbook, textbook.id)

    cards = list(db.scalars(select(Card)).all())

    assert len(cards) == 1
    assert result.imported_cards == 1
    assert result.skipped_cards == 0
    assert cards[0].concept_name == "Shock"
    assert cards[0].page_number == 31
    assert cards[0].chapter == "Circulation | Emergency"
    assert "Clinical management focuses on reversing the underlying cause." in cards[0].summary
    assert "supports perfusion" in cards[0].source_excerpt


def test_process_textbook_skips_heading_like_chunks(monkeypatch) -> None:
    db = build_session()
    importer = TextbookImporter(db)

    textbook = Textbook(
        filename="heading-only.pdf",
        stored_path="heading-only.pdf",
        status=TextbookStatus.pending,
        summary="queued",
    )
    db.add(textbook)
    db.commit()
    db.refresh(textbook)

    monkeypatch.setattr(
        importer.text_extractor,
        "extract_chunks",
        lambda _path: [
            ParagraphChunk(
                index=1,
                page_number=22,
                section_path="Chapter 1 Overview",
                text="Physiologic effects of adrenocortical hormones",
            )
        ],
    )

    async def fake_extract_cards(_chunk: ParagraphChunk) -> list[dict[str, str]]:
        return [
            {
                "concept_name": "Physiologic effects of adrenocortical hormones",
                "summary": "Physiologic effects of adrenocortical hormones",
                "chapter": "Chapter 1 Overview",
                "source_excerpt": "Physiologic effects of adrenocortical hormones",
            }
        ]

    monkeypatch.setattr(importer.llm, "extract_cards", fake_extract_cards)

    import anyio

    result = anyio.run(importer.process_textbook, textbook.id)

    cards = list(db.scalars(select(Card)).all())
    refreshed_textbook = db.get(Textbook, textbook.id)

    assert cards == []
    assert result.imported_cards == 0
    assert result.skipped_cards == 1
    assert refreshed_textbook is not None
    assert refreshed_textbook.status == TextbookStatus.completed
    assert refreshed_textbook.card_count == 0
    assert refreshed_textbook.skipped_cards == 1


def test_process_textbook_counts_empty_llm_result_as_skipped(monkeypatch) -> None:
    db = build_session()
    importer = TextbookImporter(db)

    textbook = Textbook(
        filename="empty-result.pdf",
        stored_path="empty-result.pdf",
        status=TextbookStatus.pending,
        summary="queued",
    )
    db.add(textbook)
    db.commit()
    db.refresh(textbook)

    monkeypatch.setattr(
        importer.text_extractor,
        "extract_chunks",
        lambda _path: [ParagraphChunk(index=1, page_number=23, section_path="Chapter 1 Overview", text="正文段落")],
    )

    async def fake_extract_cards(_chunk: ParagraphChunk) -> list[dict[str, str]]:
        return []

    monkeypatch.setattr(importer.llm, "extract_cards", fake_extract_cards)

    import anyio

    result = anyio.run(importer.process_textbook, textbook.id)

    cards = list(db.scalars(select(Card)).all())
    refreshed_textbook = db.get(Textbook, textbook.id)

    assert cards == []
    assert result.imported_cards == 0
    assert result.skipped_cards == 1
    assert refreshed_textbook is not None
    assert refreshed_textbook.status == TextbookStatus.completed
    assert refreshed_textbook.card_count == 0
    assert refreshed_textbook.skipped_cards == 1


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

    monkeypatch.setattr(
        importer.text_extractor,
        "extract_chunks",
        lambda _path: [
            ParagraphChunk(index=1, page_number=31, section_path="Circulation", text="chunk-1"),
            ParagraphChunk(index=2, page_number=32, section_path="Respiration", text="chunk-2"),
        ],
    )

    async def failing_extract(chunk: ParagraphChunk) -> list[dict[str, str]]:
        if chunk.text == "chunk-1":
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

    async def success_extract(_chunk: ParagraphChunk) -> list[dict[str, str]]:
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

    monkeypatch.setattr(
        importer.text_extractor,
        "extract_chunks",
        lambda _path: [
            ParagraphChunk(index=1, page_number=41, section_path="Circulation", text="chunk-1"),
            ParagraphChunk(index=2, page_number=42, section_path="Circulation", text="chunk-2"),
        ],
    )

    async def failing_extract(chunk: ParagraphChunk) -> list[dict[str, str]]:
        if chunk.text == "chunk-1":
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

    async def retry_fail(_chunk: ParagraphChunk) -> list[dict[str, str]]:
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

    monkeypatch.setattr(
        importer.text_extractor,
        "extract_chunks",
        lambda _path: [
            ParagraphChunk(index=1, page_number=51, section_path="General", text="chunk-1"),
            ParagraphChunk(index=2, page_number=52, section_path="General", text="chunk-2"),
            ParagraphChunk(index=3, page_number=53, section_path="General", text="chunk-3"),
        ],
    )

    async def failing_extract(chunk: ParagraphChunk) -> list[dict[str, str]]:
        if chunk.text == "chunk-1":
            return [
                {
                    "concept_name": "Baseline concept",
                    "summary": "Baseline concept summary for successful chunk.",
                    "chapter": "General",
                    "source_excerpt": "chunk one",
                }
            ]
        raise RuntimeError(f"failed {chunk.text}")

    monkeypatch.setattr(importer.llm, "extract_cards", failing_extract)

    import anyio

    anyio.run(importer.process_textbook, textbook.id)

    async def success_extract(chunk: ParagraphChunk) -> list[dict[str, str]]:
        return [
            {
                "concept_name": f"Recovered {chunk.text}",
                "summary": "Recovered summary for failed chunk.",
                "chapter": "Recovered",
                "source_excerpt": chunk.text,
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

    async def extract_cards(chunk: ParagraphChunk) -> list[dict[str, str]]:
        assert chunk.text == full_chunk
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


def test_create_import_replaces_old_textbook_data(monkeypatch, tmp_path) -> None:
    db = build_session()
    importer = TextbookImporter(db)
    importer.settings.uploads_dir = str(tmp_path)

    old_file = tmp_path / "old.pdf"
    old_file.write_bytes(b"old-data")

    old_textbook = Textbook(
        filename="old.pdf",
        stored_path=str(old_file),
        status=TextbookStatus.completed,
        summary="old",
        card_count=1,
    )
    db.add(old_textbook)
    db.commit()
    db.refresh(old_textbook)

    db.add(
        Card(
            textbook_id=old_textbook.id,
            concept_name="Old concept",
            summary="Old summary for an outdated card.",
            chapter="Old chapter",
            page_number=8,
            source_excerpt="Old excerpt",
        )
    )
    db.commit()

    monkeypatch.setattr(importer.llm, "validate_configuration", lambda: None)

    upload = UploadFile(filename="new.pdf", file=BytesIO(b"%PDF-1.4 new"))
    new_textbook = importer.create_import(upload)

    textbooks = list(db.scalars(select(Textbook)).all())
    cards = list(db.scalars(select(Card)).all())

    assert len(textbooks) == 1
    assert textbooks[0].id == new_textbook.id
    assert textbooks[0].filename == "new.pdf"
    assert cards == []
    assert old_file.exists() is False
