"""Application configuration via Pydantic Settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _split_csv(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    parts: list[str] = []
    for chunk in value.split(","):
        item = chunk.strip()
        if item:
            parts.append(item)
    return parts


def _parse_replacements(value: str | list[tuple[str, str]] | None) -> list[tuple[str, str]]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [(str(a), str(b)) for a, b in value]
    pairs: list[tuple[str, str]] = []
    for chunk in value.split("|"):
        part = chunk.strip()
        if not part:
            continue
        if "=>" not in part:
            msg = f"Invalid TEXT_REPLACEMENTS entry (expected old=>new): {part!r}"
            raise ValueError(msg)
        old, new = part.split("=>", 1)
        pairs.append((old, new))
    return pairs


def _parse_int_list(value: str | list[int] | None) -> list[int]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [int(item) for item in value]
    result: list[int] = []
    for chunk in value.split(","):
        item = chunk.strip()
        if item:
            result.append(int(item))
    return result


class Settings(BaseSettings):
    """Runtime settings loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "production"
    log_level: str = "INFO"

    telegram_api_id: int
    telegram_api_hash: str
    telegram_phone: str = ""
    telegram_session_path: str = "./data/sessions/listener"

    bot_token: str
    bot_admin_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    target_channel_id: int

    source_channels: Annotated[list[str], NoDecode] = Field(default_factory=list)
    database_url: str = "sqlite+aiosqlite:///./data/database/app.db"

    download_dir: str = "./data/downloads"
    max_download_size_mb: int = 100
    temp_file_ttl_minutes: int = 60

    album_wait_seconds: float = 1.5
    album_max_wait_seconds: float = 8.0
    queue_maxsize: int = 1000
    max_concurrency: int = 3

    enable_keyword_filter: bool = True
    enable_text_replace: bool = True
    enable_link_filter: bool = True
    enable_footer: bool = True
    enable_duplicate_filter: bool = True

    blocked_keywords: Annotated[list[str], NoDecode] = Field(default_factory=list)
    allowed_keywords: Annotated[list[str], NoDecode] = Field(default_factory=list)
    keyword_case_sensitive: bool = False
    allow_empty_text: bool = True

    text_replacements: Annotated[list[tuple[str, str]], NoDecode] = Field(default_factory=list)
    remove_source_links: bool = True
    remove_all_links: bool = False
    remove_telegram_invites: bool = True
    blocked_link_domains: Annotated[list[str], NoDecode] = Field(default_factory=list)
    allowed_link_domains: Annotated[list[str], NoDecode] = Field(default_factory=list)
    message_footer: str = ""

    duplicate_content_window_hours: int = 24

    max_retries: int = 3
    retry_base_delay_seconds: float = 2.0

    @field_validator(
        "blocked_keywords",
        "allowed_keywords",
        "source_channels",
        "blocked_link_domains",
        "allowed_link_domains",
        mode="before",
    )
    @classmethod
    def parse_csv_lists(cls, value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return _split_csv(str(value) if value is not None else "")

    @field_validator("bot_admin_ids", mode="before")
    @classmethod
    def parse_admins(cls, value: object) -> list[int]:
        if isinstance(value, list):
            return [int(item) for item in value]
        return _parse_int_list(str(value) if value is not None else "")

    @field_validator("text_replacements", mode="before")
    @classmethod
    def parse_replacements(cls, value: object) -> list[tuple[str, str]]:
        if isinstance(value, list):
            return [(str(a), str(b)) for a, b in value]
        return _parse_replacements(str(value) if value is not None else "")

    @field_validator("telegram_api_hash", "bot_token")
    @classmethod
    def non_empty_secrets(cls, value: str) -> str:
        if not value or not value.strip():
            msg = "must not be empty"
            raise ValueError(msg)
        return value.strip()

    @model_validator(mode="after")
    def validate_required(self) -> Settings:
        if not self.source_channels:
            msg = "SOURCE_CHANNELS must contain at least one channel username or id"
            raise ValueError(msg)
        if not self.bot_admin_ids:
            msg = "BOT_ADMIN_IDS must contain at least one Telegram user id"
            raise ValueError(msg)
        if self.max_download_size_mb <= 0:
            msg = "MAX_DOWNLOAD_SIZE_MB must be positive"
            raise ValueError(msg)
        if self.album_wait_seconds <= 0 or self.album_max_wait_seconds < self.album_wait_seconds:
            msg = "ALBUM wait times are invalid"
            raise ValueError(msg)
        return self

    @property
    def max_download_size_bytes(self) -> int:
        return self.max_download_size_mb * 1024 * 1024

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.bot_admin_ids

    def __repr__(self) -> str:
        return (
            f"Settings(app_env={self.app_env!r}, log_level={self.log_level!r}, "
            f"telegram_api_id=***, telegram_api_hash=***, telegram_phone=***, "
            f"bot_token=***, target_channel_id={self.target_channel_id}, "
            f"source_channels={self.source_channels!r})"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def clear_settings_cache() -> None:
    get_settings.cache_clear()
