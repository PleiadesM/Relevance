"""RSS/Atom fetcher. Optional ``keywords`` on the source act as a title
filter (e.g. the Hacker News firehose narrowed to AI terms)."""

from __future__ import annotations

import calendar
from datetime import datetime, timezone

import feedparser

from ..http import get
from ..models import Item, clip, detect_lang, item_id, strip_html

FULL_TEXT_MIN_CHARS = 500
FULL_TEXT_MIN_EXTRA_CHARS = 200
FULL_TEXT_MAX_CHARS = 50_000


def _entry_datetime(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        parsed = entry.get(attr)
        if parsed:
            return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    return None


def _content_candidates(entry) -> list[str]:
    candidates: list[str] = []
    content = entry.get("content") or []
    if isinstance(content, dict):
        content = [content]
    for part in content:
        if isinstance(part, dict):
            value = part.get("value") or part.get("content") or ""
        else:
            value = str(part or "")
        if value:
            candidates.append(value)
    for key in ("content_encoded", "content:encoded", "encoded"):
        value = entry.get(key)
        if value:
            candidates.append(str(value))
    return candidates


def _entry_full_text(entry, summary: str) -> str:
    """Return substantial RSS/Atom embedded content as sanitized plaintext."""
    texts = [strip_html(candidate) for candidate in _content_candidates(entry)]
    texts = [text for text in texts if text]
    if not texts:
        return ""
    full_text = max(texts, key=len)
    if len(full_text) < FULL_TEXT_MIN_CHARS:
        return ""
    if summary and len(full_text) < len(summary) + FULL_TEXT_MIN_EXTRA_CHARS:
        return ""
    return full_text[:FULL_TEXT_MAX_CHARS].rstrip()


def parse_feed_bytes(raw: bytes, source, now: datetime) -> list[Item]:
    feed = feedparser.parse(raw)
    items: list[Item] = []
    for entry in feed.entries[: source.max_results]:
        title = strip_html(entry.get("title", "")).strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        published = _entry_datetime(entry)
        if published is None:
            continue  # undated entries would churn in the 24h window every run
        if source.keywords:
            hay = title.casefold()
            if not any(kw.casefold() in hay for kw in source.keywords):
                continue
        summary = clip(strip_html(entry.get("summary") or entry.get("description") or ""))
        full_text = _entry_full_text(entry, summary)
        items.append(Item(
            id=item_id(url=link),
            title=title,
            url=link,
            source=source.name,
            source_id=source.id,
            category=source.category,
            section=source.section,
            kind="news",
            published_at=published,
            summary=summary,
            lang=detect_lang(title),
            full_text=full_text,
            weight=source.weight,
        ))
    return items


def fetch(source, ctx) -> list[Item]:
    resp = get(ctx.session, source.url)
    return parse_feed_bytes(resp.content, source, ctx.now)
