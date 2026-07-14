"""SQLAlchemy ORM models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SourceChannel(Base):
    __tablename__ = "source_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    target_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    processing_profile: Mapped[str] = mapped_column(String(64), default="default", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ProcessedMessage(Base):
    __tablename__ = "processed_messages"
    __table_args__ = (
        UniqueConstraint("source_chat_id", "source_message_id", name="uq_source_message"),
        Index("ix_processed_content_hash", "content_hash"),
        Index("ix_processed_status", "status"),
        Index("ix_processed_grouped", "source_chat_id", "grouped_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    grouped_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="received")
    skip_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    processing_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    target_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    target_message_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    logs: Mapped[list[ProcessingLog]] = relationship(back_populates="message", cascade="all")


class ProcessingLog(Base):
    __tablename__ = "processing_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_record_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("processed_messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    processor_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    message: Mapped[ProcessedMessage] = relationship(back_populates="logs")


class AppSetting(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    value: Mapped[dict[str, Any] | str | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReviewTask(Base):
    __tablename__ = "review_tasks"
    __table_args__ = (
        Index("ix_review_tasks_status", "status"),
        Index("ix_review_tasks_source", "source_chat_id", "source_message_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    processed_message_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("processed_messages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    source_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    original_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    processed_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    final_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    media_type: Mapped[str] = mapped_column(String(32), nullable=False, default="text")
    media_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_rules: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    detected_keywords: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    assigned_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    published_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    media_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    publishing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReviewAction(Base):
    __tablename__ = "review_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("review_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    old_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ContentRevision(Base):
    __tablename__ = "content_revisions"
    __table_args__ = (
        UniqueConstraint("review_task_id", "revision_number", name="uq_review_revision"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("review_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RuleGroup(Base):
    __tablename__ = "rule_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class KeywordRule(Base):
    __tablename__ = "keyword_rules"
    __table_args__ = (Index("ix_keyword_rules_priority", "priority"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False, default="keyword")
    match_type: Mapped[str] = mapped_column(String(32), nullable=False, default="contains")
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    replacement: Mapped[str | None] = mapped_column(Text, nullable=True)
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    whole_word: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    use_regex: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_channel_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    target_channel_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    message_types: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False, default="flag")
    stop_processing: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    group_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("rule_groups.id"), nullable=True
    )
    hit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class RuleExecutionLog(Base):
    __tablename__ = "rule_execution_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    processed_message_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("processed_messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    review_task_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("review_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    rule_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("keyword_rules.id", ondelete="SET NULL"), nullable=True, index=True
    )
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    matched_text: Mapped[str | None] = mapped_column(String(512), nullable=True)
    replacement_text: Mapped[str | None] = mapped_column(String(512), nullable=True)
    match_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    match_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    before_excerpt: Mapped[str | None] = mapped_column(String(512), nullable=True)
    after_excerpt: Mapped[str | None] = mapped_column(String(512), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
