from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema() -> None:
    Base.metadata.create_all(bind=engine)
    if not settings.database_url.startswith("sqlite"):
        return

    inspector = inspect(engine)
    textbook_columns = {column["name"] for column in inspector.get_columns("textbooks")}
    required_columns = {
        "skipped_cards": "ALTER TABLE textbooks ADD COLUMN skipped_cards INTEGER NOT NULL DEFAULT 0",
        "total_chunks": "ALTER TABLE textbooks ADD COLUMN total_chunks INTEGER NOT NULL DEFAULT 0",
        "processed_chunks": "ALTER TABLE textbooks ADD COLUMN processed_chunks INTEGER NOT NULL DEFAULT 0",
        "failed_chunks": "ALTER TABLE textbooks ADD COLUMN failed_chunks INTEGER NOT NULL DEFAULT 0",
    }

    with engine.begin() as connection:
        for column_name, ddl in required_columns.items():
            if column_name not in textbook_columns:
                connection.execute(text(ddl))
