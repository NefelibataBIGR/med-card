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

    if "cards" in inspector.get_table_names():
        card_columns = {column["name"] for column in inspector.get_columns("cards")}
        card_required_columns = {
            "english_name": "ALTER TABLE cards ADD COLUMN english_name VARCHAR(255)",
            "page_number": "ALTER TABLE cards ADD COLUMN page_number INTEGER",
        }
        with engine.begin() as connection:
            for column_name, ddl in card_required_columns.items():
                if column_name not in card_columns:
                    connection.execute(text(ddl))

    if "import_chunk_failures" in inspector.get_table_names():
        failure_columns = {column["name"] for column in inspector.get_columns("import_chunk_failures")}
        failure_required_columns = {
            "chunk_text": "ALTER TABLE import_chunk_failures ADD COLUMN chunk_text TEXT",
            "retry_count": "ALTER TABLE import_chunk_failures ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0",
            "resolved": "ALTER TABLE import_chunk_failures ADD COLUMN resolved BOOLEAN NOT NULL DEFAULT 0",
            "updated_at": "ALTER TABLE import_chunk_failures ADD COLUMN updated_at DATETIME",
            "page_number": "ALTER TABLE import_chunk_failures ADD COLUMN page_number INTEGER",
            "section_path": "ALTER TABLE import_chunk_failures ADD COLUMN section_path VARCHAR(255)",
        }
        with engine.begin() as connection:
            for column_name, ddl in failure_required_columns.items():
                if column_name not in failure_columns:
                    connection.execute(text(ddl))
