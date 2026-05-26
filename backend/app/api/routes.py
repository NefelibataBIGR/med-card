from __future__ import annotations

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models import Card, CardStatus, ReviewAction, ReviewLog, Textbook
from ..schemas import CardRead, CardUpdate, DrawResponse, PoolResponse, TextbookImportResponse, TextbookRead
from ..services.llm import MissingLLMConfigurationError
from ..services.review import ReviewService
from ..services.textbook_importer import ImportErrorWithMessage, TextbookImporter

router = APIRouter(prefix="/api")


def get_card_or_404(db: Session, card_id: int) -> Card:
    card = db.get(Card, card_id)
    if not card or card.is_deleted:
        raise HTTPException(status_code=404, detail="Card not found.")
    return card


@router.post("/textbooks/import", response_model=TextbookImportResponse)
async def import_textbook(file: UploadFile = File(...), db: Session = Depends(get_db)) -> TextbookImportResponse:
    importer = TextbookImporter(db)
    try:
        result = await importer.import_pdf(file)
    except MissingLLMConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ImportErrorWithMessage as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to import textbook: {exc}") from exc

    return TextbookImportResponse(
        textbook=result.textbook,
        imported_cards=result.imported_cards,
        skipped_cards=result.skipped_cards,
    )


@router.get("/textbooks", response_model=list[TextbookRead])
def list_textbooks(db: Session = Depends(get_db)) -> list[Textbook]:
    return list(db.scalars(select(Textbook).order_by(Textbook.imported_at.desc())).all())


@router.get("/cards/draw", response_model=DrawResponse)
def draw_card(db: Session = Depends(get_db), x_session_id: str | None = Header(default=None)) -> DrawResponse:
    session_id, card, round_complete = ReviewService(db).draw_card(x_session_id)
    if round_complete:
        return DrawResponse(
            session_id=session_id,
            card=None,
            round_complete=True,
            message="No more drawable cards in this round. Reset the round to start again.",
        )
    return DrawResponse(
        session_id=session_id,
        card=card,
        round_complete=False,
        message="Drew the next card.",
    )


@router.post("/sessions/{session_id}/reset", status_code=204)
def reset_session(session_id: str, db: Session = Depends(get_db)) -> Response:
    ReviewService(db).reset_session(session_id)
    return Response(status_code=204)


@router.patch("/cards/{card_id}", response_model=CardRead)
def update_card(
    card_id: int,
    payload: CardUpdate,
    db: Session = Depends(get_db),
    x_session_id: str | None = Header(default="manual"),
) -> Card:
    card = get_card_or_404(db, card_id)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(card, field, value)
    db.add(ReviewLog(card_id=card.id, session_id=x_session_id or "manual", action=ReviewAction.edit))
    db.commit()
    db.refresh(card)
    return card


@router.post("/cards/{card_id}/mark-familiar", response_model=CardRead)
def mark_familiar(
    card_id: int,
    db: Session = Depends(get_db),
    x_session_id: str | None = Header(default="manual"),
) -> Card:
    card = get_card_or_404(db, card_id)
    return ReviewService(db).mark_status(card, x_session_id or "manual", ReviewAction.mark_familiar, CardStatus.familiar)


@router.post("/cards/{card_id}/mark-uncertain", response_model=CardRead)
def mark_uncertain(
    card_id: int,
    db: Session = Depends(get_db),
    x_session_id: str | None = Header(default="manual"),
) -> Card:
    card = get_card_or_404(db, card_id)
    return ReviewService(db).mark_status(
        card, x_session_id or "manual", ReviewAction.mark_uncertain, CardStatus.uncertain
    )


@router.post("/cards/{card_id}/ignore", response_model=CardRead)
def ignore_card(
    card_id: int,
    db: Session = Depends(get_db),
    x_session_id: str | None = Header(default="manual"),
) -> Card:
    card = get_card_or_404(db, card_id)
    return ReviewService(db).mark_status(card, x_session_id or "manual", ReviewAction.ignore, CardStatus.ignored)


@router.delete("/cards/{card_id}", status_code=204)
def delete_card(
    card_id: int,
    db: Session = Depends(get_db),
    x_session_id: str | None = Header(default="manual"),
) -> Response:
    card = get_card_or_404(db, card_id)
    card.is_deleted = True
    db.add(ReviewLog(card_id=card.id, session_id=x_session_id or "manual", action=ReviewAction.delete))
    db.commit()
    return Response(status_code=204)


@router.get("/pools/familiar", response_model=PoolResponse)
def familiar_pool(q: str = Query(default=""), db: Session = Depends(get_db)) -> PoolResponse:
    items = ReviewService(db).list_pool(CardStatus.familiar, q)
    return PoolResponse(items=items, total=len(items), query=q)


@router.get("/pools/uncertain", response_model=PoolResponse)
def uncertain_pool(q: str = Query(default=""), db: Session = Depends(get_db)) -> PoolResponse:
    items = ReviewService(db).list_pool(CardStatus.uncertain, q)
    return PoolResponse(items=items, total=len(items), query=q)
