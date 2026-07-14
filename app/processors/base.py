"""Processor protocol and shared types."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.schemas.message import NormalizedMessage, ProcessingContext, ProcessResult


@runtime_checkable
class MessageProcessor(Protocol):
    name: str

    async def process(
        self,
        message: NormalizedMessage,
        context: ProcessingContext,
    ) -> ProcessResult: ...
