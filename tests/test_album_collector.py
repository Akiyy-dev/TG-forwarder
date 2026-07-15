"""Album collector tests."""

from __future__ import annotations

import asyncio

from app.listeners.album_collector import AlbumCollector
from app.schemas.message import MediaItem, MediaType, NormalizedMessage


def _part(mid: int, grouped: int, text: str = "") -> NormalizedMessage:
    return NormalizedMessage(
        source_chat_id=-1001,
        source_message_id=mid,
        grouped_id=grouped,
        text=text,
        media_type=MediaType.PHOTO,
        media_items=[
            MediaItem(
                media_type=MediaType.PHOTO,
                source_message_id=mid,
                order=0,
                file_unique_id=str(mid),
            )
        ],
    )


async def test_album_aggregation_order_and_single_caption() -> None:
    completed: list[NormalizedMessage] = []

    async def on_complete(msg: NormalizedMessage) -> None:
        completed.append(msg)

    collector = AlbumCollector(wait_seconds=0.05, max_wait_seconds=1.0, on_complete=on_complete)
    assert await collector.add(_part(2, 99)) is None
    assert await collector.add(_part(1, 99, text="caption-here")) is None
    assert await collector.add(_part(3, 99)) is None
    await asyncio.sleep(0.2)
    assert len(completed) == 1
    album = completed[0]
    assert album.media_type == MediaType.ALBUM
    assert album.text == "caption-here"
    assert [i.source_message_id for i in album.media_items] == [1, 2, 3]


async def test_non_album_passes_through() -> None:
    collector = AlbumCollector(wait_seconds=0.05, max_wait_seconds=1.0)
    msg = NormalizedMessage(
        source_chat_id=-1001,
        source_message_id=5,
        text="hi",
        media_type=MediaType.TEXT,
    )
    ready = await collector.add(msg)
    assert ready is msg


async def test_late_part_does_not_spawn_second_album() -> None:
    completed: list[NormalizedMessage] = []

    async def on_complete(msg: NormalizedMessage) -> None:
        completed.append(msg)

    collector = AlbumCollector(
        wait_seconds=0.05,
        max_wait_seconds=1.0,
        late_grace_seconds=1.0,
        on_complete=on_complete,
    )
    assert await collector.add(_part(1, 42)) is None
    assert await collector.add(_part(2, 42)) is None
    await asyncio.sleep(0.15)
    assert len(completed) == 1
    assert len(completed[0].media_items) == 2

    # Late third part must not emit a separate incomplete album.
    assert await collector.add(_part(3, 42)) is None
    await asyncio.sleep(0.1)
    assert len(completed) == 1


async def test_merge_helper_builds_album() -> None:
    album = AlbumCollector.merge([_part(10, 7, "cap"), _part(11, 7), _part(12, 7)])
    assert album.media_type == MediaType.ALBUM
    assert album.album_message_ids == [10, 11, 12]
    assert album.text == "cap"
    assert len(album.media_items) == 3
