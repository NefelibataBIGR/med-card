from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models import Card, ImportChunkFailure, Textbook, TextbookStatus
from app.services.textbook_importer import TextbookImporter


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

    monkeypatch.setattr(importer, "_extract_chunks", lambda _path: ["chunk-1", "chunk-2"])

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

    monkeypatch.setattr(importer, "_extract_chunks", lambda _path: ["chunk-1"])

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
