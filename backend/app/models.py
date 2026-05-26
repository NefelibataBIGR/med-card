from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .core.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class TextbookStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class CardStatus(str, Enum):
    new = "new"
    familiar = "familiar"
    uncertain = "uncertain"
    ignored = "ignored"


class ReviewAction(str, Enum):
    drawn = "drawn"
    mark_familiar = "mark_familiar"
    mark_uncertain = "mark_uncertain"
    ignore = "ignore"
    edit = "edit"
    delete = "delete"
    reset_session = "reset_session"


class Textbook(Base):
    __tablename__ = "textbooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[TextbookStatus] = mapped_column(
        SqlEnum(TextbookStatus), default=TextbookStatus.pending, nullable=False
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    card_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    cards: Mapped[list["Card"]] = relationship(back_populates="textbook", cascade="all, delete-orphan")


class Card(Base):
    __tablename__ = "cards"
    __table_args__ = (
        UniqueConstraint("textbook_id", "chapter", "concept_name", name="uq_card_textbook_chapter_concept"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    textbook_id: Mapped[int] = mapped_column(ForeignKey("textbooks.id"), nullable=False, index=True)
    concept_name: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    chapter: Mapped[str] = mapped_column(String(255), nullable=False)
    source_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[CardStatus] = mapped_column(SqlEnum(CardStatus), default=CardStatus.new, nullable=False, index=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )

    textbook: Mapped["Textbook"] = relationship(back_populates="cards")
    review_logs: Mapped[list["ReviewLog"]] = relationship(back_populates="card", cascade="all, delete-orphan")


class ReviewLog(Base):
    __tablename__ = "review_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_id: Mapped[int | None] = mapped_column(ForeignKey("cards.id"), nullable=True, index=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[ReviewAction] = mapped_column(SqlEnum(ReviewAction), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    card: Mapped["Card | None"] = relationship(back_populates="review_logs")


class SessionState(Base):
    __tablename__ = "session_state"
    __table_args__ = (UniqueConstraint("session_id", "card_id", name="uq_session_card"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id"), nullable=False, index=True)
    drawn_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
