from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="MED_CARD_",
        extra="ignore",
    )

    app_name: str = "Med Card"
    app_version: str = "0.1.0"
    database_url: str = "sqlite:///./backend/data/med_card.db"
    uploads_dir: str = "backend/data/uploads"
    llm_provider: str = "deepseek"
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"]
    )
    extraction_chunk_size: int = 5_000
    extraction_paragraph_limit: int = 1_200
    extraction_summary_limit: int = 180
    source_excerpt_limit: int = 2_000

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
