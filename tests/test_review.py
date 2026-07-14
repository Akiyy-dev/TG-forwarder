"""Review state machine and service tests."""

from __future__ import annotations

import pytest
from app.database.models import ProcessedMessage
from app.review.service import ReviewConflictError, ReviewService
from app.review.state_machine import (
    IllegalTransitionError,
    ReviewActionType,
    ReviewStatus,
    assert_transition,
)
from app.schemas.message import MediaType, NormalizedMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def test_legal_and_illegal_transitions() -> None:
    assert_transition(ReviewStatus.PENDING, ReviewStatus.APPROVED)
    assert_transition(ReviewStatus.APPROVED, ReviewStatus.PUBLISHING)
    with pytest.raises(IllegalTransitionError):
        assert_transition(ReviewStatus.PUBLISHED, ReviewStatus.APPROVED)
    with pytest.raises(IllegalTransitionError):
        assert_transition(ReviewStatus.PENDING, ReviewStatus.PUBLISHING)


async def test_create_edit_conflict_and_restore(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        processed = ProcessedMessage(
            source_chat_id=-1001,
            source_message_id=42,
            status="pending_review",
            target_chat_id=-1002,
        )
        session.add(processed)
        await session.commit()
        await session.refresh(processed)
        processed_id = processed.id

    svc = ReviewService(session_factory)
    msg = NormalizedMessage(
        source_chat_id=-1001,
        source_message_id=42,
        text="processed body",
        media_type=MediaType.TEXT,
        target_chat_id=-1002,
    )
    async with session_factory() as session:
        processed = await session.get(ProcessedMessage, processed_id)
        assert processed is not None
        task = await svc.create_from_message(
            processed=processed,
            original_text="original body",
            processed_message=msg,
            decision_reason="manual_review",
        )
    assert task.status == ReviewStatus.PENDING.value
    assert task.revision == 2
    assert task.original_text == "original body"
    assert task.final_text == "processed body"

    edited = await svc.edit_text(
        task.id,
        "edited by reviewer",
        user_id=1,
        expected_revision=task.revision,
    )
    assert edited.status == ReviewStatus.EDITING.value
    assert edited.final_text == "edited by reviewer"

    with pytest.raises(ReviewConflictError):
        await svc.edit_text(
            task.id,
            "stale edit",
            user_id=2,
            expected_revision=task.revision,
        )

    restored = await svc.restore_revision(
        edited.id,
        revision_number=1,
        user_id=1,
        expected_revision=edited.revision,
    )
    assert restored.final_text == "original body"

    approved = await svc.transition(
        restored.id,
        ReviewStatus.APPROVED,
        user_id=1,
        action=ReviewActionType.APPROVED,
        expected_revision=restored.revision,
    )
    claimed = await svc.claim_for_publish(
        approved.id,
        expected_revision=approved.revision,
        user_id=1,
    )
    assert claimed is not None
    assert claimed.status == ReviewStatus.PUBLISHING.value

    lost = await svc.claim_for_publish(
        approved.id,
        expected_revision=approved.revision,
        user_id=2,
    )
    assert lost is None
