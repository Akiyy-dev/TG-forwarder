"""Media rematerialize and TTL retain tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.schemas.message import MediaItem, MediaType, NormalizedMessage
from app.services.media_service import MediaService
from app.utils.files import cleanup_expired_files


def test_cleanup_retains_protected_paths(tmp_path: Path) -> None:
    keep = tmp_path / "keep.jpg"
    drop = tmp_path / "drop.jpg"
    keep.write_bytes(b"keep")
    drop.write_bytes(b"drop")
    # Force both to look expired
    import os
    import time

    old = time.time() - 3600
    os.utime(keep, (old, old))
    os.utime(drop, (old, old))

    deleted = cleanup_expired_files(
        tmp_path,
        ttl_minutes=1,
        retain_paths={str(keep.resolve())},
    )
    assert deleted == 1
    assert keep.exists()
    assert not drop.exists()


@pytest.mark.asyncio
async def test_ensure_materialized_redownloads_missing(tmp_path: Path) -> None:
    download = tmp_path / "dl"
    download.mkdir()
    dest = download / "photo.jpg"

    raw = MagicMock()
    raw.id = 12811

    async def _download(_msg: object, file_path: str) -> str:
        Path(file_path).write_bytes(b"img")
        return file_path

    downloader = MagicMock()
    downloader.fetch_messages = AsyncMock(return_value=[raw])
    downloader.download_media = AsyncMock(side_effect=_download)

    media = MediaService(
        str(download),
        max_size_bytes=1024 * 1024,
        ttl_minutes=60,
        downloader=downloader,
    )
    message = NormalizedMessage(
        source_chat_id=-1001,
        source_message_id=12811,
        text="caption",
        media_type=MediaType.PHOTO,
        media_items=[
            MediaItem(
                media_type=MediaType.PHOTO,
                local_path=str(tmp_path / "missing.jpg"),
                source_message_id=12811,
                order=0,
            )
        ],
    )
    assert media.media_missing(message)
    out = await media.ensure_materialized(message)
    assert not media.media_missing(out)
    assert out.media_items[0].local_path
    assert Path(out.media_items[0].local_path).is_file()
    assert dest.exists() or Path(out.media_items[0].local_path).exists()
