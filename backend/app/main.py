from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .api.routes import router
from .core.config import get_settings
from .core.database import SessionLocal, ensure_schema
from .models import Textbook, TextbookStatus, utc_now


def mark_interrupted_imports() -> None:
    db = SessionLocal()
    try:
        items = list(
            db.scalars(
                select(Textbook).where(
                    Textbook.status.in_([TextbookStatus.pending, TextbookStatus.processing])
                )
            ).all()
        )
        for item in items:
            item.status = TextbookStatus.failed
            item.processed_at = utc_now()
            item.error_message = "导入在完成前被中断；如有需要，请重新导入该 PDF。"
            if item.total_chunks:
                item.summary = (
                    f"导入在处理完 {item.processed_chunks}/{item.total_chunks} 个文本块后中断。"
                    f"关闭前已生成 {item.card_count} 张卡片。"
                )
            else:
                item.summary = "导入在文本块处理开始前被中断。"
        if items:
            db.commit()
    finally:
        db.close()


def create_app() -> FastAPI:
    settings = get_settings()
    Path(settings.uploads_dir).mkdir(parents=True, exist_ok=True)
    ensure_schema()
    mark_interrupted_imports()

    app = FastAPI(title=settings.app_name, version=settings.app_version)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(router)
    return app


app = create_app()
