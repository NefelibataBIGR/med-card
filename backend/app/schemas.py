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
    cancel_requested: bool
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
    english_name: str | None
    summary: str
    chapter: str
    page_number: int | None
    source_excerpt: str
    status: CardStatus
    created_at: datetime
    updated_at: datetime


class CardUpdate(BaseModel):
    concept_name: str | None = Field(default=None, min_length=1, max_length=255)
    english_name: str | None = Field(default=None, max_length=255)
    summary: str | None = Field(default=None, min_length=1, max_length=500)
    chapter: str | None = Field(default=None, min_length=1, max_length=255)
    page_number: int | None = Field(default=None, ge=1)
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


class ImportChunkFailureRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    textbook_id: int
    chunk_index: int
    page_number: int | None
    section_path: str | None
    chunk_excerpt: str
    error_message: str
    retry_count: int
    resolved: bool
    created_at: datetime
    updated_at: datetime


class ImportChunkRetryResponse(BaseModel):
    textbook: TextbookRead
    failure: ImportChunkFailureRead
    imported_cards: int
    skipped_cards: int


class ImportChunkRetryBatchResponse(BaseModel):
    textbook: TextbookRead
    retried_count: int
    resolved_count: int
    remaining_failures: int
