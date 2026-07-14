"""Link filtering using entities with regex cleanup fallback."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from app.schemas.message import MessageEntity, NormalizedMessage, ProcessingContext, ProcessResult
from app.utils.text import collapse_blank_lines

_URL_RE = re.compile(
    r"(https?://[^\s<>\"']+|t\.me/[^\s<>\"']+|telegram\.me/[^\s<>\"']+)",
    re.IGNORECASE,
)
_MENTION_RE = re.compile(r"@[A-Za-z0-9_]{5,}")
_INVITE_HOSTS = {"t.me", "telegram.me", "telegram.dog"}


def _domain_of(url: str) -> str:
    candidate = url if "://" in url else f"https://{url}"
    try:
        host = urlparse(candidate).netloc.lower()
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _is_invite_link(url: str) -> bool:
    candidate = url if "://" in url else f"https://{url}"
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return False
    host = (parsed.netloc or "").lower().removeprefix("www.")
    if host not in _INVITE_HOSTS:
        return False
    path = parsed.path or ""
    return path.startswith("/+") or path.startswith("/joinchat/")


class LinkFilterProcessor:
    name = "link_filter"

    def __init__(
        self,
        *,
        remove_all_links: bool = False,
        remove_telegram_invites: bool = True,
        remove_source_links: bool = True,
        blocked_domains: list[str] | None = None,
        allowed_domains: list[str] | None = None,
        enabled: bool = True,
    ) -> None:
        self.remove_all_links = remove_all_links
        self.remove_telegram_invites = remove_telegram_invites
        self.remove_source_links = remove_source_links
        self.blocked_domains = {d.lower().removeprefix("www.") for d in (blocked_domains or [])}
        self.allowed_domains = {d.lower().removeprefix("www.") for d in (allowed_domains or [])}
        self.enabled = enabled

    def _should_remove_url(self, url: str, source_username: str | None) -> bool:
        if self.remove_all_links:
            if self.allowed_domains:
                return _domain_of(url) not in self.allowed_domains
            return True
        if self.remove_telegram_invites and _is_invite_link(url):
            return True
        domain = _domain_of(url)
        if domain in self.blocked_domains:
            return True
        if self.allowed_domains and domain and domain not in self.allowed_domains:
            # Only enforce allow-list when explicitly configured and not remove_all
            if self.blocked_domains or self.remove_telegram_invites:
                pass
            else:
                return True
        if self.remove_source_links and source_username:
            uname = source_username.lstrip("@").lower()
            lower = url.lower()
            if uname and (f"t.me/{uname}" in lower or f"@{uname}" in lower):
                return True
        return False

    def _strip_by_entities(
        self,
        text: str,
        entities: list[MessageEntity],
        source_username: str | None,
    ) -> tuple[str, list[MessageEntity]]:
        if not entities:
            return text, entities

        removals: list[tuple[int, int]] = []
        kept: list[MessageEntity] = []
        link_types = {"url", "text_url", "mention", "email"}

        for ent in entities:
            if ent.type not in link_types:
                kept.append(ent)
                continue
            segment = text[ent.offset : ent.offset + ent.length]
            url = ent.url or segment
            if (
                ent.type == "mention"
                and self.remove_source_links
                and source_username
                and segment.lstrip("@").lower() == source_username.lstrip("@").lower()
            ):
                removals.append((ent.offset, ent.offset + ent.length))
                continue
            if ent.type in {"url", "text_url"} and self._should_remove_url(url, source_username):
                removals.append((ent.offset, ent.offset + ent.length))
                continue
            kept.append(ent)

        if not removals:
            return text, entities

        removals.sort(key=lambda x: x[0], reverse=True)
        chars = list(text)
        for start, end in removals:
            del chars[start:end]
        new_text = "".join(chars)

        # Rebuild kept entities with adjusted offsets
        adjusted: list[MessageEntity] = []
        for ent in kept:
            shift = sum((end - start) for start, end in removals if end <= ent.offset)
            # Drop if overlapping a removal
            overlaps = any(
                not (ent.offset + ent.length <= start or ent.offset >= end)
                for start, end in removals
            )
            if overlaps:
                continue
            adjusted.append(
                MessageEntity(
                    type=ent.type,
                    offset=ent.offset - shift,
                    length=ent.length,
                    url=ent.url,
                    user_id=ent.user_id,
                    language=ent.language,
                    custom_emoji_id=ent.custom_emoji_id,
                )
            )
        return new_text, adjusted

    def _strip_regex(self, text: str, source_username: str | None) -> str:
        def repl_url(match: re.Match[str]) -> str:
            url = match.group(0)
            return "" if self._should_remove_url(url, source_username) else url

        text = _URL_RE.sub(repl_url, text)
        if self.remove_source_links and source_username:
            uname = source_username.lstrip("@")
            text = re.sub(rf"@{re.escape(uname)}\b", "", text, flags=re.IGNORECASE)
        if self.remove_all_links and not self.allowed_domains:
            text = _MENTION_RE.sub("", text)
        return text

    async def process(
        self,
        message: NormalizedMessage,
        context: ProcessingContext,
    ) -> ProcessResult:
        if not self.enabled:
            return ProcessResult.cont(message, skipped=True)

        source_username = context.source_username or message.source_chat_username
        text, entities = self._strip_by_entities(message.text, message.entities, source_username)
        text = self._strip_regex(text, source_username)
        text = collapse_blank_lines(text)
        # Clean dangling punctuation after link removal
        text = re.sub(r"[ \t]*([,;:.]){2,}", r"\1", text)
        text = re.sub(r"\(\s*\)", "", text)
        text = collapse_blank_lines(text)

        message.text = text
        message.entities = entities
        return ProcessResult.cont(message)
