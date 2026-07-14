"""Review task status machine."""

from __future__ import annotations

from enum import StrEnum


class ReviewStatus(StrEnum):
    PENDING = "pending"
    EDITING = "editing"
    APPROVED = "approved"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    REJECTED = "rejected"
    FAILED = "failed"
    EXPIRED = "expired"


class ReviewActionType(StrEnum):
    CREATED = "created"
    OPENED = "opened"
    EDITED = "edited"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISH_STARTED = "publish_started"
    PUBLISHED = "published"
    PUBLISH_FAILED = "publish_failed"
    RETRIED = "retried"
    RULES_REAPPLIED = "rules_reapplied"
    RESTORED_ORIGINAL = "restored_original"
    ASSIGNED = "assigned"
    UNASSIGNED = "unassigned"


ALLOWED_TRANSITIONS: dict[ReviewStatus, set[ReviewStatus]] = {
    ReviewStatus.PENDING: {
        ReviewStatus.EDITING,
        ReviewStatus.APPROVED,
        ReviewStatus.REJECTED,
        ReviewStatus.EXPIRED,
    },
    ReviewStatus.EDITING: {
        ReviewStatus.PENDING,
        ReviewStatus.APPROVED,
        ReviewStatus.REJECTED,
    },
    ReviewStatus.APPROVED: {ReviewStatus.PUBLISHING},
    ReviewStatus.PUBLISHING: {ReviewStatus.PUBLISHED, ReviewStatus.FAILED},
    ReviewStatus.FAILED: {
        ReviewStatus.PENDING,
        ReviewStatus.REJECTED,
        ReviewStatus.APPROVED,
    },
    ReviewStatus.PUBLISHED: set(),
    ReviewStatus.REJECTED: set(),
    ReviewStatus.EXPIRED: set(),
}


class IllegalTransitionError(Exception):
    def __init__(self, old: ReviewStatus, new: ReviewStatus) -> None:
        self.old = old
        self.new = new
        super().__init__(f"Illegal review transition: {old.value} -> {new.value}")


def assert_transition(old: ReviewStatus | str, new: ReviewStatus | str) -> None:
    current = ReviewStatus(old)
    target = ReviewStatus(new)
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise IllegalTransitionError(current, target)
