from __future__ import annotations

from io import BytesIO

import anyio
from fastapi import UploadFile
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models import Card, Textbook, TextbookStatus
from app.services.textbook_importer import TextbookImporter


def build_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_importer_dedupes_and_keeps_partial_success_on_later_failure(monkeypatch) -> None:
    db = build_session()
    importer = TextbookImporter(db)

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

    upload = UploadFile(filename="sample.pdf", file=BytesIO(b"%PDF-1.4 fake"))

    try:
        anyio.run(importer.import_pdf, upload)
    except RuntimeError as exc:
        assert str(exc) == "mock batch failure"

    cards = list(db.scalars(select(Card)).all())
    assert len(cards) == 1

    textbooks = list(db.scalars(select(Textbook)).all())
    assert len(textbooks) == 1
    assert textbooks[0].status == TextbookStatus.failed
    assert textbooks[0].card_count == 0
    assert textbooks[0].error_message == "mock batch failure"
