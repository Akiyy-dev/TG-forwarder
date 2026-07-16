"""Deployment topology smoke tests."""

from __future__ import annotations

from pathlib import Path

import yaml


def test_compose_has_independent_business_services() -> None:
    root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((root / "compose.yaml").read_text(encoding="utf-8"))
    services = config["services"]

    assert {"web", "sender", "telegram-receiver", "safew-receiver"} <= set(services)
    assert {"postgres", "redis", "migrate"} <= set(services)
    assert services["sender"]["command"][-1] == "app.entrypoints.sender"
    assert services["telegram-receiver"]["command"][-1] == ("app.entrypoints.telegram_receiver")
    assert services["safew-receiver"]["ports"][0].startswith("127.0.0.1:")


def test_safew_image_expects_versioned_archive_path() -> None:
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "docker" / "safew.Dockerfile").read_text(encoding="utf-8")
    assert "COPY image/tsetup.3.6.2.tar.xz" in dockerfile
