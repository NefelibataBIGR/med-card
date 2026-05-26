from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models import Card, CardStatus, ReviewAction, Textbook, TextbookStatus
from app.services.review import ReviewService


def build_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def seed_cards(db: Session) -> None:
    textbook = Textbook(
        filename="sample.pdf",
        stored_path="sample.pdf",
        status=TextbookStatus.completed,
        card_count=3,
    )
    db.add(textbook)
    db.commit()
    db.refresh(textbook)

    db.add_all(
        [
            Card(
                textbook_id=textbook.id,
                concept_name="Cardiac output",
                summary="Volume of blood pumped by one ventricle per minute.",
                chapter="Circulation",
                source_excerpt="Cardiac output is the volume pumped by one ventricle each minute.",
                status=CardStatus.new,
            ),
            Card(
                textbook_id=textbook.id,
                concept_name="Lung compliance",
                summary="How easily the lung expands under force.",
                chapter="Respiration",
                source_excerpt="Lung compliance describes the ease of lung expansion.",
                status=CardStatus.uncertain,
            ),
            Card(
                textbook_id=textbook.id,
                concept_name="Ignored card",
                summary="This card should not be drawn.",
                chapter="Misc",
                source_excerpt="ignored",
                status=CardStatus.ignored,
            ),
        ]
    )
    db.commit()


def test_draw_prioritizes_uncertain_without_repeating() -> None:
    db = build_session()
    seed_cards(db)
    service = ReviewService(db)

    session_id, first_card, complete = service.draw_card(None)
    assert not complete
    assert first_card is not None
    assert first_card.status == CardStatus.uncertain

    same_session, second_card, complete = service.draw_card(session_id)
    assert same_session == session_id
    assert not complete
    assert second_card is not None
    assert second_card.status == CardStatus.new
    assert second_card.id != first_card.id

    _, no_card, complete = service.draw_card(session_id)
    assert complete
    assert no_card is None


def test_mark_status_moves_card_between_pools() -> None:
    db = build_session()
    seed_cards(db)
    service = ReviewService(db)

    card = db.query(Card).filter(Card.status == CardStatus.uncertain).one()
    updated = service.mark_status(card, "session-a", ReviewAction.mark_familiar, CardStatus.familiar)

    assert updated.status == CardStatus.familiar
    assert any(item.id == updated.id for item in service.list_pool(CardStatus.familiar, ""))
    assert all(item.id != updated.id for item in service.list_pool(CardStatus.uncertain, ""))
