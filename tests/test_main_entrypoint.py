"""Legacy monolith entrypoint tests."""

from __future__ import annotations

from typing import Any, cast

from app import main
from app.config import Settings


def test_monolith_does_not_create_dispatcher_when_polling_disabled(
    settings_env: Settings,
) -> None:
    settings_env.bot_polling_enabled = False

    dispatcher = main._create_bot_dispatcher(
        settings_env,
        message_service=cast(Any, object()),
        channel_service=cast(Any, object()),
        listener=cast(Any, object()),
    )

    assert dispatcher is None
