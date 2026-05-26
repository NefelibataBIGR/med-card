from __future__ import annotations

import uuid

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from ..models import Card, CardStatus, ReviewAction, ReviewLog, SessionState


class ReviewService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def draw_card(self, session_id: str | None) -> tuple[str, Card | None, bool]:
        current_session = session_id or uuid.uuid4().hex
        drawn_ids = set(
            self.db.scalars(select(SessionState.card_id).where(SessionState.session_id == current_session)).all()
        )
        card = self.db.scalar(self._candidate_query(CardStatus.uncertain, drawn_ids))
        if card is None:
            card = self.db.scalar(self._candidate_query(CardStatus.new, drawn_ids))
        if card is None:
            return current_session, None, True

        self.db.add(SessionState(session_id=current_session, card_id=card.id))
        self.db.add(ReviewLog(card_id=card.id, session_id=current_session, action=ReviewAction.drawn))
        self.db.commit()
        self.db.refresh(card)
        return current_session, card, False

    def mark_status(self, card: Card, session_id: str, action: ReviewAction, status: CardStatus) -> Card:
        card.status = status
        self.db.add(ReviewLog(card_id=card.id, session_id=session_id, action=action))
        self.db.commit()
        self.db.refresh(card)
        return card

    def reset_session(self, session_id: str) -> None:
        self.db.execute(delete(SessionState).where(SessionState.session_id == session_id))
        self.db.add(ReviewLog(card_id=None, session_id=session_id, action=ReviewAction.reset_session))
        self.db.commit()

    def list_pool(self, status: CardStatus, query: str | None) -> list[Card]:
        stmt = select(Card).where(Card.status == status, Card.is_deleted.is_(False))
        if query:
            needle = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(
                    Card.concept_name.ilike(needle),
                    Card.summary.ilike(needle),
                    Card.chapter.ilike(needle),
                )
            )
        return list(self.db.scalars(stmt.order_by(Card.updated_at.desc(), Card.id.desc())).all())

    def _candidate_query(self, status: CardStatus, drawn_ids: set[int]):
        stmt = select(Card).where(Card.status == status, Card.is_deleted.is_(False))
        if drawn_ids:
            stmt = stmt.where(Card.id.not_in(drawn_ids))
        return stmt.order_by(Card.updated_at.asc(), Card.id.asc()).limit(1)
