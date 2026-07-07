from datetime import datetime, timedelta, timezone

from newsdash.config import TagRule
from newsdash.models import Item
from newsdash.scoring import (
    apply_tags,
    citation_score,
    keyword_relevance,
    recency_score,
    score_item,
)

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)


def make_item(title="Title", summary="", hours_ago=1.0, weight=0.8, kind="news"):
    return Item(
        id="x", title=title, url="https://e.com", source="S", source_id="s",
        category="open", section="news", kind=kind,
        published_at=NOW - timedelta(hours=hours_ago),
        summary=summary, weight=weight,
    )


def test_recency_monotonic():
    older = recency_score(NOW - timedelta(hours=24), NOW, 12)
    newer = recency_score(NOW - timedelta(hours=1), NOW, 12)
    assert newer > older > 0


def test_future_dates_score_full():
    assert recency_score(NOW + timedelta(hours=1), NOW, 12) == 1.0


def test_keyword_relevance():
    item = make_item(title="LLM visualization toolkit", summary="a study")
    assert keyword_relevance(item, [], 0.15) == 0.0
    one = keyword_relevance(item, ["visualization"], 0.15)
    two = keyword_relevance(item, ["visualization", "llm"], 0.15)
    assert 0 < one < two <= 1.0


def test_score_item_combination():
    hot = make_item(title="data visualization news", hours_ago=0.5, weight=1.0)
    cold = make_item(title="unrelated", hours_ago=40, weight=0.4)
    score_item(hot, NOW, ["data visualization"], 0.15)
    score_item(cold, NOW, ["data visualization"], 0.15)
    assert hot.score > cold.score
    assert 0 <= cold.score <= 1 and 0 <= hot.score <= 1


def test_citation_score_log_scaled():
    assert citation_score(0) == 0.0
    assert citation_score(-1) == 0.0
    assert 0 < citation_score(5) < citation_score(100) < citation_score(999)
    assert citation_score(10_000) == 1.0


def test_highly_cited_paper_outranks_uncited_peer():
    cited = make_item(kind="paper", hours_ago=48)
    cited.extra["citations"] = 250
    uncited = make_item(kind="paper", hours_ago=48)
    uncited.extra["citations"] = 0
    score_item(cited, NOW, [], 0.15)
    score_item(uncited, NOW, [], 0.15)
    assert cited.score > uncited.score


def test_citationless_paper_keeps_default_formula():
    # arXiv papers carry no citation data; they must not be penalized by
    # the four-part blend's citation term.
    with_data = make_item(kind="paper", hours_ago=2)
    with_data.extra["citations"] = 0
    without_data = make_item(kind="paper", hours_ago=2)
    score_item(with_data, NOW, [], 0.15)
    score_item(without_data, NOW, [], 0.15)
    assert without_data.score > with_data.score  # 0.45/0.35/0.20 vs 0.35/…+0·cit


def test_news_ignores_citations():
    item = make_item(kind="news", hours_ago=2)
    item.extra["citations"] = 9999
    twin = make_item(kind="news", hours_ago=2)
    score_item(item, NOW, [], 0.15)
    score_item(twin, NOW, [], 0.15)
    assert item.score == twin.score


def test_apply_tags_max_and_match():
    item = make_item(title="Introducing our new API release",
                     summary="open source developer tools")
    rules = [
        TagRule("model-release", ["introducing", "release"]),
        TagRule("dev-tools", ["api", "sdk"]),
        TagRule("nope", ["quantum bagel"]),
    ]
    apply_tags(item, rules)
    assert item.tags == ["model-release", "dev-tools"]
