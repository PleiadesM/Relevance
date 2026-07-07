"""Heuristic scoring and tagging. Zero LLM calls by design: the score is
0.45·recency + 0.35·interest-keyword relevance + 0.20·source weight.
Papers whose source reports a citation count switch to a four-part blend
(0.35·recency + 0.25·relevance + 0.15·weight + 0.25·citation impact) so the
best-cited work surfaces first; log-scaled, saturating around 10³ citations.
Schedule events and course work are never scored — time orders them."""

from __future__ import annotations

import math
from datetime import datetime

from .config import TagRule
from .models import Item

HALF_LIFE_HOURS = {"news": 12.0, "paper": 84.0}
MAX_TAGS = 4
CITATION_SATURATION_LOG10 = 3.0  # log10(1+citations)/3 -> 1.0 at ~1000


def recency_score(published_at: datetime, now: datetime, half_life_hours: float) -> float:
    age_hours = (now - published_at).total_seconds() / 3600.0
    if age_hours <= 0:
        return 1.0
    return math.exp(-age_hours / half_life_hours)


def keyword_relevance(item: Item, keywords: list[str], boost: float) -> float:
    if not keywords:
        return 0.0
    text = f"{item.title} {item.summary}".casefold()
    matches = sum(1 for kw in keywords if kw.casefold() in text)
    if matches == 0:
        return 0.0
    return min(1.0, 0.4 * matches + boost)


def citation_score(citations: int) -> float:
    if citations <= 0:
        return 0.0
    return min(1.0, math.log10(1 + citations) / CITATION_SATURATION_LOG10)


def score_item(
    item: Item,
    now: datetime,
    interests_keywords: list[str],
    interests_boost: float,
) -> None:
    half_life = HALF_LIFE_HOURS.get(item.kind, 24.0)
    rec = recency_score(item.published_at, now, half_life)
    rel = keyword_relevance(item, interests_keywords, interests_boost)
    citations = item.extra.get("citations")
    if item.kind == "paper" and isinstance(citations, int):
        cit = citation_score(citations)
        item.score = round(0.35 * rec + 0.25 * rel + 0.15 * item.weight + 0.25 * cit, 4)
    else:
        item.score = round(0.45 * rec + 0.35 * rel + 0.20 * item.weight, 4)


def apply_tags(item: Item, rules: list[TagRule]) -> None:
    text = f"{item.title} {item.summary}".casefold()
    for rule in rules:
        if len(item.tags) >= MAX_TAGS:
            break
        if rule.tag in item.tags:
            continue
        if rule.source_ids is not None and item.source_id not in rule.source_ids:
            continue
        if any(kw.casefold() in text for kw in rule.any):
            item.tags.append(rule.tag)
