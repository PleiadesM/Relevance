"""Normalized data models and small text helpers shared by all fetchers."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from bs4 import BeautifulSoup

SUMMARY_MAX = 300
_CJK_RE = re.compile(r"[㐀-鿿豈-﫿]")


@dataclass
class Item:
    """One news item or paper, normalized across every source type."""

    id: str
    title: str
    url: str
    source: str
    source_id: str
    category: str
    section: str
    kind: str  # "news" | "paper"
    published_at: datetime  # timezone-aware
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    lang: str = "en"
    score: float = 0.0
    authors: list[str] = field(default_factory=list)
    venue: str | None = None
    extra: dict = field(default_factory=dict)
    full_text: str = ""  # transient; written to per-article files only
    full_text_file: str | None = None
    weight: float = 0.8  # transient (source weight); not serialized

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "source_id": self.source_id,
            "category": self.category,
            "section": self.section,
            "kind": self.kind,
            "published_at": iso_utc(self.published_at),
            "summary": self.summary,
            "tags": self.tags,
            "lang": self.lang,
            "score": self.score,
            "extra": self.extra,
        }
        if self.kind == "paper":
            d["authors"] = self.authors
            d["venue"] = self.venue
        if self.full_text_file:
            d["full_text_available"] = True
            d["full_text_file"] = self.full_text_file
        return d


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    return BeautifulSoup(text, "html.parser").get_text(" ", strip=True)


def clip(text: str, limit: int = SUMMARY_MAX) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    # break on the last space when one is reasonably close to the limit
    if " " in cut[limit - 40:]:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip() + "…"


def detect_lang(text: str) -> str:
    if not text:
        return "en"
    cjk = len(_CJK_RE.findall(text))
    return "zh" if cjk >= max(2, len(text) * 0.15) else "en"


def item_id(
    *,
    doi: str | None = None,
    arxiv_id: str | None = None,
    url: str | None = None,
    fallback: str | None = None,
) -> str:
    """Stable 16-hex id; identity preference: DOI > arXiv id > URL > fallback."""
    if doi:
        key = f"doi:{doi.strip().lower()}"
    elif arxiv_id:
        key = f"arxiv:{arxiv_id.strip().lower()}"
    elif url:
        key = f"url:{url.strip()}"
    elif fallback:
        key = f"fp:{fallback}"
    else:
        raise ValueError("item_id needs at least one identity")
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
