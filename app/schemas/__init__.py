"""Internal schema models (framework-agnostic)."""

from app.schemas.channel import SourceChannelConfig
from app.schemas.message import (
    ForwardInfo,
    MediaItem,
    MediaType,
    MessageEntity,
    NormalizedMessage,
    ProcessAction,
    ProcessingContext,
    ProcessResult,
)

__all__ = [
    "ForwardInfo",
    "MediaItem",
    "MediaType",
    "MessageEntity",
    "NormalizedMessage",
    "ProcessAction",
    "ProcessResult",
    "ProcessingContext",
    "SourceChannelConfig",
]
