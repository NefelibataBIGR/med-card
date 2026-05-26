from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import CardStatus, TextbookStatus


class TextbookRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    imported_at: datetime
    processed_at: datetime | None
    status: TextbookStatus
    summary: str | None
    error_message: str | None
    card_count: int
    skipped_cards: int
    total_chunks: int
    processed_chunks: int
    failed_chunks: int


class CardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    textbook_id: int
    concept_name: str
    summary: str
    chapter: str
    source_excerpt: str
    status: CardStatus
    created_at: datetime
    updated_at: datetime


class CardUpdate(BaseModel):
    concept_name: str | None = Field(default=None, min_length=1, max_length=255)
    summary: str | None = Field(default=None, min_length=1, max_length=500)
    chapter: str | None = Field(default=None, min_length=1, max_length=255)
    source_excerpt: str | None = Field(default=None, min_length=1, max_length=2_000)


class DrawResponse(BaseModel):
    session_id: str
    card: CardRead | None
    round_complete: bool
    message: str


class PoolResponse(BaseModel):
    items: list[CardRead]
    total: int
    query: str = ""


class TextbookImportResponse(BaseModel):
    textbook: TextbookRead
    imported_cards: int
    skipped_cards: int


class TextbookEnqueueResponse(BaseModel):
    textbook: TextbookRead
    message: str
