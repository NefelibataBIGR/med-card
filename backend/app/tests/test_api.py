from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.database import Base, get_db
from app.main import create_app
from app.models import Card, CardStatus, Textbook, TextbookStatus


def build_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def seed_cards(db: Session) -> None:
    textbook = Textbook(
        filename="sample.pdf",
        stored_path="sample.pdf",
        status=TextbookStatus.completed,
        card_count=2,
    )
    db.add(textbook)
    db.commit()
    db.refresh(textbook)

    db.add_all(
        [
            Card(
                textbook_id=textbook.id,
                concept_name="Volume pressure loop",
                summary="A loop showing ventricular pressure and volume changes.",
                chapter="Cardiology",
                source_excerpt="The loop maps one full cardiac cycle.",
                status=CardStatus.uncertain,
            ),
            Card(
                textbook_id=textbook.id,
                concept_name="Tidal volume",
                summary="The air moved in or out during a normal breath.",
                chapter="Respiration",
                source_excerpt="Tidal volume is measured during quiet breathing.",
                status=CardStatus.new,
            ),
        ]
    )
    db.commit()


def build_client(db: Session) -> TestClient:
    app = create_app()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_draw_mark_and_pool_flow() -> None:
    db = build_session()
    seed_cards(db)
    client = build_client(db)

    draw_response = client.get("/api/cards/draw")
    assert draw_response.status_code == 200
    payload = draw_response.json()
    assert payload["card"]["status"] == "uncertain"
    session_id = payload["session_id"]
    card_id = payload["card"]["id"]

    mark_response = client.post(
        f"/api/cards/{card_id}/mark-familiar",
        headers={"X-Session-Id": session_id},
    )
    assert mark_response.status_code == 200
    assert mark_response.json()["status"] == "familiar"

    pool_response = client.get("/api/pools/familiar")
    assert pool_response.status_code == 200
    pool_payload = pool_response.json()
    assert pool_payload["total"] == 1
    assert pool_payload["items"][0]["id"] == card_id


def test_delete_card_excludes_it_from_draws() -> None:
    db = build_session()
    seed_cards(db)
    client = build_client(db)

    first_draw = client.get("/api/cards/draw").json()
    session_id = first_draw["session_id"]
    first_card_id = first_draw["card"]["id"]

    delete_response = client.delete(
        f"/api/cards/{first_card_id}",
        headers={"X-Session-Id": session_id},
    )
    assert delete_response.status_code == 204

    second_draw = client.get("/api/cards/draw", headers={"X-Session-Id": session_id})
    assert second_draw.status_code == 200
    assert second_draw.json()["card"]["id"] != first_card_id


def test_draw_with_empty_pool_returns_empty_pool_message() -> None:
    db = build_session()
    client = build_client(db)

    response = client.get("/api/cards/draw")

    assert response.status_code == 200
    payload = response.json()
    assert payload["card"] is None
    assert payload["round_complete"] is False
    assert payload["message"] == "卡池没有卡片，请先导入教材。"


def test_draw_with_only_non_drawable_cards_returns_specific_message() -> None:
    db = build_session()
    textbook = Textbook(
        filename="sample.pdf",
        stored_path="sample.pdf",
        status=TextbookStatus.completed,
        card_count=1,
    )
    db.add(textbook)
    db.commit()
    db.refresh(textbook)
    db.add(
        Card(
            textbook_id=textbook.id,
            concept_name="Stable concept",
            summary="This card exists but is not drawable in the review queue.",
            chapter="General",
            source_excerpt="Already reviewed.",
            status=CardStatus.familiar,
        )
    )
    db.commit()

    client = build_client(db)
    response = client.get("/api/cards/draw")

    assert response.status_code == 200
    payload = response.json()
    assert payload["card"] is None
    assert payload["round_complete"] is False
    assert payload["message"] == "当前没有可抽取的卡片。"


def test_import_endpoint_validates_missing_configuration(monkeypatch) -> None:
    monkeypatch.setenv("MED_CARD_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("MED_CARD_LLM_API_KEY", "")
    get_settings.cache_clear()

    db = build_session()
    client = build_client(db)

    response = client.post(
        "/api/textbooks/import",
        files={"file": ("sample.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )

    assert response.status_code == 400
    assert "MED_CARD_LLM_API_KEY" in response.json()["detail"]
    get_settings.cache_clear()


def test_list_textbook_failures_returns_records() -> None:
    db = build_session()
    textbook = Textbook(
        filename="sample.pdf",
        stored_path="sample.pdf",
        status=TextbookStatus.failed,
        summary="failed",
        failed_chunks=1,
    )
    db.add(textbook)
    db.commit()
    db.refresh(textbook)

    from app.models import ImportChunkFailure

    db.add(
        ImportChunkFailure(
            textbook_id=textbook.id,
            chunk_index=2,
            chunk_excerpt="chunk text",
            error_message="failure",
        )
    )
    db.commit()

    client = build_client(db)
    response = client.get(f"/api/textbooks/{textbook.id}/failures")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["chunk_index"] == 2


def test_retry_all_textbook_failures_for_missing_textbook_returns_404() -> None:
    db = build_session()
    client = build_client(db)

    response = client.post("/api/textbooks/999/failures/retry-all")

    assert response.status_code == 404
