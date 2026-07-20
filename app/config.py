"""Application configuration via Pydantic Settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

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
    app_role: Literal["all", "web", "sender", "telegram-receiver", "safew-receiver"] = "all"
    log_level: str = "INFO"

    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_phone: str = ""
    telegram_session_path: str = "./data/sessions/listener"

    bot_token: str = ""
    bot_admin_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    bot_polling_enabled: bool = True
    database_url: str = "sqlite+aiosqlite:///./data/database/app.db"
    redis_url: str = "redis://redis:6379/0"
    redis_incoming_stream: str = "forwarder:incoming"
    redis_command_stream: str = "forwarder:commands"
    redis_sender_group: str = "forwarder-sender"
    redis_consumer_name: str = "sender-1"
    redis_stream_maxlen: int = 0
    redis_block_ms: int = 5000
    redis_claim_idle_ms: int = 300000
    rules_config_path: str = "./config/rules.yaml"

    download_dir: str = "./data/downloads"
    max_download_size_mb: int = 100
    temp_file_ttl_minutes: int = 60

    # SafeW desktop notification receiver
    safew_app_names: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["SafeW"])
    safew_allowed_chats: Annotated[list[str], NoDecode] = Field(default_factory=list)
    safew_capture_all_apps: bool = False
    safew_auto_register_sources: bool = True

    # SafeW Bot API publisher. The token is optional until a SafeW target is used.
    safew_bot_token: str = ""
    safew_bot_api_base_url: str = "https://api.safew.bot"
    safew_bot_timeout_seconds: float = 30.0

    album_wait_seconds: float = 2.5
    album_max_wait_seconds: float = 20.0
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

    # Web admin panel
    web_enabled: bool = True
    web_host: str = "0.0.0.0"
    web_port: int = 8000
    web_admin_username: str = "admin"
    web_admin_password_hash: str = ""
    web_secret_key: str = ""
    web_access_token_expire_minutes: int = 60
    web_refresh_token_expire_days: int = 7
    web_allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    web_secure_cookies: bool = False
    web_trust_proxy: bool = False
    web_docs_enabled: bool = True
    web_login_rate_limit: int = 10
    web_login_rate_window_seconds: int = 60

    @field_validator(
        "blocked_keywords",
        "allowed_keywords",
        "blocked_link_domains",
        "allowed_link_domains",
        "web_allowed_origins",
        "safew_app_names",
        "safew_allowed_chats",
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

    @field_validator("telegram_api_hash", "bot_token", "safew_bot_token")
    @classmethod
    def strip_secrets(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_required(self) -> Settings:
        if self.app_role in {"all", "telegram-receiver"} and (
            self.telegram_api_id <= 0 or not self.telegram_api_hash
        ):
            msg = "TELEGRAM_API_ID and TELEGRAM_API_HASH are required for telegram-receiver"
            raise ValueError(msg)
        if self.app_role in {"all", "sender"} and not self.bot_token:
            msg = "BOT_TOKEN is required for sender"
            raise ValueError(msg)
        if (
            self.app_role in {"all", "sender"}
            and self.bot_polling_enabled
            and not self.bot_admin_ids
        ):
            msg = "BOT_ADMIN_IDS must contain at least one Telegram user id"
            raise ValueError(msg)
        if self.max_download_size_mb <= 0:
            msg = "MAX_DOWNLOAD_SIZE_MB must be positive"
            raise ValueError(msg)
        if self.safew_bot_timeout_seconds <= 0:
            msg = "SAFEW_BOT_TIMEOUT_SECONDS must be positive"
            raise ValueError(msg)
        if self.album_wait_seconds <= 0 or self.album_max_wait_seconds < self.album_wait_seconds:
            msg = "ALBUM wait times are invalid"
            raise ValueError(msg)
        if self.app_role in {"all", "web"} and self.web_enabled and not self.web_secret_key.strip():
            msg = "WEB_SECRET_KEY is required when WEB_ENABLED=true"
            raise ValueError(msg)
        return self

    @property
    def max_download_size_bytes(self) -> int:
        return self.max_download_size_mb * 1024 * 1024

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.bot_admin_ids

    def __repr__(self) -> str:
        return (
            f"Settings(app_env={self.app_env!r}, app_role={self.app_role!r}, "
            f"log_level={self.log_level!r}, "
            f"telegram_api_id=***, telegram_api_hash=***, telegram_phone=***, "
            f"bot_token=***, bot_polling_enabled={self.bot_polling_enabled}, "
            f"web_enabled={self.web_enabled})"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
