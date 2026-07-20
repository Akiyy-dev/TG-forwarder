"""SafeW Bot API publisher."""

from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import httpx

from app.logging import get_logger
from app.schemas.message import MediaItem, MediaType, NormalizedMessage
from app.services.retry_service import classify_exception, should_retry, sleep_for_retry
from app.utils.text import TELEGRAM_CAPTION_LIMIT, TELEGRAM_TEXT_LIMIT, truncate_text

logger = get_logger(__name__)


class SafeWApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        self.status_code = status_code
        self.error_code = error_code
        self.retry_after = retry_after
        super().__init__(message)


class SafeWRateLimitError(SafeWApiError):
    pass


class SafeWServerError(SafeWApiError):
    pass


class SafeWBadRequest(SafeWApiError):
    pass


class SafeWUnauthorizedError(SafeWApiError):
    pass


class SafeWForbiddenError(SafeWApiError):
    pass


class SafeWNotFoundError(SafeWApiError):
    pass


class SafeWPublisher:
    """Send normalized messages through the documented SafeW Bot API."""

    def __init__(
        self,
        token: str,
        *,
        api_base_url: str = "https://api.safew.bot",
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        base_delay: float = 2.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.token = token.strip()
        self.api_base_url = api_base_url.rstrip("/")
        self.max_retries = max_retries
        self.base_delay = base_delay
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(timeout=timeout_seconds)

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def _url(self, method: str) -> str:
        if not self.configured:
            raise SafeWUnauthorizedError("SAFEW_BOT_TOKEN is not configured")
        return f"{self.api_base_url}/bot{self.token}/{method}"

    @staticmethod
    def _error_type(status_code: int, error_code: int | None) -> type[SafeWApiError]:
        code = error_code or status_code
        if code == 429:
            return SafeWRateLimitError
        if code >= 500:
            return SafeWServerError
        if code == 401:
            return SafeWUnauthorizedError
        if code == 403:
            return SafeWForbiddenError
        if code == 404:
            return SafeWNotFoundError
        return SafeWBadRequest

    async def _request(
        self,
        method: str,
        *,
        json_body: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> Any:
        response = await self.client.post(
            self._url(method),
            json=json_body,
            data=data,
            files=files,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if response.is_success and isinstance(payload, dict) and payload.get("ok") is True:
            return payload.get("result")

        error_code: int | None = None
        description = response.reason_phrase or "SafeW Bot API request failed"
        retry_after: float | None = None
        if isinstance(payload, dict):
            raw_code = payload.get("error_code")
            if isinstance(raw_code, int):
                error_code = raw_code
            description = str(payload.get("description") or description)
            parameters = payload.get("parameters")
            if isinstance(parameters, dict) and parameters.get("retry_after") is not None:
                retry_after = float(parameters["retry_after"])
        if retry_after is None and response.headers.get("Retry-After"):
            try:
                retry_after = float(response.headers["Retry-After"])
            except ValueError:
                retry_after = None
        exc_type = self._error_type(response.status_code, error_code)
        raise exc_type(
            description,
            status_code=response.status_code,
            error_code=error_code,
            retry_after=retry_after,
        )

    @staticmethod
    def _message_ids(result: Any) -> list[int]:
        rows = result if isinstance(result, list) else [result]
        ids: list[int] = []
        for row in rows:
            if isinstance(row, dict) and row.get("message_id") is not None:
                ids.append(int(row["message_id"]))
        if not ids:
            raise SafeWBadRequest("SafeW response did not contain a message_id")
        return ids

    @staticmethod
    def _path(item: MediaItem) -> Path:
        if not item.local_path:
            raise FileNotFoundError("SafeW media item has no local path")
        path = Path(item.local_path)
        if not path.is_file():
            raise FileNotFoundError(f"SafeW media file missing: {item.local_path}")
        return path

    async def _send_item(
        self,
        chat_id: int,
        item: MediaItem,
        caption: str | None,
    ) -> list[int]:
        method_and_field = {
            MediaType.PHOTO: ("sendPhoto", "photo"),
            MediaType.VIDEO: ("sendVideo", "video"),
            MediaType.AUDIO: ("sendAudio", "audio"),
            MediaType.VOICE: ("sendVoice", "voice"),
            MediaType.DOCUMENT: ("sendDocument", "document"),
            MediaType.ANIMATION: ("sendDocument", "document"),
        }
        method, field = method_and_field.get(
            item.media_type,
            ("sendDocument", "document"),
        )
        path = self._path(item)
        data: dict[str, Any] = {"chat_id": str(chat_id)}
        if caption:
            data["caption"] = caption
        if item.duration is not None and method in {"sendVideo", "sendAudio", "sendVoice"}:
            data["duration"] = str(item.duration)
        if item.width is not None and method == "sendVideo":
            data["width"] = str(item.width)
        if item.height is not None and method == "sendVideo":
            data["height"] = str(item.height)
        with path.open("rb") as handle:
            result = await self._request(
                method,
                data=data,
                files={
                    field: (
                        item.original_filename or path.name,
                        handle,
                        item.mime_type or "application/octet-stream",
                    )
                },
            )
        return self._message_ids(result)

    async def _send_album(
        self,
        chat_id: int,
        items: list[MediaItem],
        caption: str | None,
    ) -> list[int]:
        if not items:
            raise SafeWBadRequest("SafeW media group is empty")
        if not all(item.media_type in {MediaType.PHOTO, MediaType.VIDEO} for item in items):
            fallback_ids: list[int] = []
            for index, item in enumerate(items):
                fallback_ids.extend(
                    await self._send_item(chat_id, item, caption if index == 0 else None)
                )
            return fallback_ids

        ids: list[int] = []
        for offset in range(0, len(items), 10):
            chunk = items[offset : offset + 10]
            media: list[dict[str, Any]] = []
            with ExitStack() as stack:
                files: dict[str, Any] = {}
                for index, item in enumerate(chunk):
                    path = self._path(item)
                    key = f"media_{index}"
                    handle = stack.enter_context(path.open("rb"))
                    files[key] = (
                        item.original_filename or path.name,
                        handle,
                        item.mime_type or "application/octet-stream",
                    )
                    entry: dict[str, Any] = {
                        "type": "photo" if item.media_type == MediaType.PHOTO else "video",
                        "media": f"attach://{key}",
                    }
                    if offset == 0 and index == 0 and caption:
                        entry["caption"] = caption
                    media.append(entry)
                result = await self._request(
                    "sendMediaGroup",
                    data={"chat_id": str(chat_id), "media": json.dumps(media)},
                    files=files,
                )
            ids.extend(self._message_ids(result))
        return ids

    async def _send(self, message: NormalizedMessage, target_chat_id: int) -> list[int]:
        text = message.text or ""
        if message.media_type == MediaType.TEXT:
            result = await self._request(
                "sendMessage",
                json_body={
                    "chat_id": target_chat_id,
                    "text": truncate_text(text, TELEGRAM_TEXT_LIMIT),
                },
            )
            return self._message_ids(result)

        caption = truncate_text(text, TELEGRAM_CAPTION_LIMIT) if text else None
        items = sorted(message.media_items, key=lambda item: item.order)
        if message.media_type == MediaType.ALBUM:
            return await self._send_album(target_chat_id, items, caption)
        if not items:
            raise SafeWBadRequest("SafeW media message has no media item")
        return await self._send_item(target_chat_id, items[0], caption)

    async def publish(self, message: NormalizedMessage, target_chat_id: int) -> list[int]:
        attempt = 0
        while attempt < self.max_retries:
            attempt += 1
            try:
                ids = await self._send(message, target_chat_id)
                logger.info(
                    "safew_publish_success",
                    source_chat_id=message.source_chat_id,
                    source_message_id=message.source_message_id,
                    target_chat_id=target_chat_id,
                    target_message_ids=ids,
                    retry_count=attempt - 1,
                )
                return ids
            except Exception as exc:
                logger.warning(
                    "safew_publish_error",
                    exception_type=type(exc).__name__,
                    retry_class=classify_exception(exc).value,
                    target_chat_id=target_chat_id,
                    retry_count=attempt,
                )
                if not should_retry(exc, attempt, self.max_retries):
                    raise
                await sleep_for_retry(exc, attempt, self.base_delay)
        raise RuntimeError("SafeW publish retry loop exited unexpectedly")

    async def get_chat(self, chat_id: int) -> dict[str, Any]:
        result = await self._request("getChat", json_body={"chat_id": chat_id})
        if not isinstance(result, dict):
            raise SafeWBadRequest("SafeW getChat returned an invalid response")
        return result

    async def send_test_message(self, chat_id: int, text: str) -> int:
        result = await self._request(
            "sendMessage",
            json_body={"chat_id": chat_id, "text": text},
        )
        return self._message_ids(result)[0]

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()
