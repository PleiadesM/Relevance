import json
from datetime import datetime, timezone

import responses

from newsdash.http import make_session
from newsdash.threads import (THREADS_MAX_TOKENS, TIMELINE_LABEL_ZH_CLIP,
                              WHY_NOW_CLIP, generate_threads)

CHAT_URL = "https://api.openai.com/v1/chat/completions"

# Fixed build clock so timeline validation ("no future dates") is deterministic.
NOW = datetime(2026, 7, 24, 9, 0, tzinfo=timezone.utc)


# ---- fixtures / builders ------------------------------------------------

def item(i, *, source_id="s1", source="Source One", section="news",
         kind="news", score=None, title=None, url=None, summary="a summary",
         full_text_file=None, published_at=None):
    d = {
        "id": f"item{i}",
        "title": title if title is not None else f"Title {i}",
        "url": url or f"https://ex.test/{i}",
        "source": source,
        "source_id": source_id,
        "section": section,
        "kind": kind,
        "score": (1.0 - i * 0.001) if score is None else score,
        "summary": summary,
    }
    if full_text_file:
        d["full_text_file"] = full_text_file
    if published_at:
        d["published_at"] = published_at
    return d


def payloads(items, *, kind="news", section="news"):
    return {section: {"meta": {"kind": kind, "section": section}, "items": items}}


def angle(n, en="an angle here", zh="角度"):
    return {"item": n, "phrase": {"en": en, "zh": zh}}


def point(date, en="a milestone", zh="里程碑", n=None):
    p = {"date": date, "label": {"en": en, "zh": zh}}
    if n is not None:
        p["item"] = n
    return p


def thread(angles, *, keyword=None, gloss=None, why_now=None,
           convergence="convergent", relates_to=None, timeline=None):
    t = {
        "keyword": keyword or {"en": "keyword", "zh": "关键词"},
        "gloss": gloss or {"en": "a gloss", "zh": "一段释义"},
        "why_now": why_now or {"en": "why now", "zh": "此刻"},
        "convergence": convergence,
        "angles": angles,
    }
    if relates_to is not None:
        t["relates_to"] = relates_to
    if timeline is not None:
        t["timeline"] = timeline
    return t


def completion(threads):
    return {"choices": [{"message":
            {"content": json.dumps({"threads": threads})}}]}


def two_source_payload(**item_kwargs):
    """Three news items across two sources (s1, s2), item1 first by score."""
    return payloads([
        item(1, source_id="s1", source="Alpha", **item_kwargs),
        item(2, source_id="s2", source="Beta"),
        item(3, source_id="s1", source="Alpha"),
    ])


ENV = {"LLM_API_KEY": "sk-test", "LLM_MODEL": "gpt-4o-mini"}


# ---- gates (zero HTTP) --------------------------------------------------

def test_no_api_key_makes_no_call():
    assert generate_threads(
        two_source_payload(), {}, make_session(), scope="public") is None


@responses.activate
def test_kill_switch_makes_no_call():
    env = {**ENV, "LLM_THREADS_ENABLED": "0"}
    assert generate_threads(
        two_source_payload(), env, make_session(), scope="public") is None
    assert len(responses.calls) == 0


@responses.activate
def test_empty_pool_makes_no_call():
    assert generate_threads(
        payloads([]), ENV, make_session(), scope="public") is None
    assert len(responses.calls) == 0


@responses.activate
def test_single_source_pool_makes_no_call():
    single = payloads([
        item(1, source_id="s1"), item(2, source_id="s1"), item(3, source_id="s1"),
    ])
    assert generate_threads(
        single, ENV, make_session(), scope="public") is None
    assert len(responses.calls) == 0


# ---- happy path ---------------------------------------------------------

@responses.activate
def test_happy_path_resolves_angles_and_ids():
    responses.post(CHAT_URL, json=completion([
        thread([angle(1), angle(2)]),
        thread([angle(1), angle(2)]),
    ]))
    pay = two_source_payload(full_text_file="articles/news/item1.json")
    result = generate_threads(pay, ENV, make_session(), scope="public")

    assert result["scope"] == "public"
    assert len(result["threads"]) == 2
    assert [t["id"] for t in result["threads"]] == ["t1", "t2"]

    # exactly one POST, JSON mode, the wide token budget
    assert len(responses.calls) == 1
    body = json.loads(responses.calls[0].request.body)
    assert body["response_format"] == {"type": "json_object"}
    assert body["max_tokens"] == THREADS_MAX_TOKENS
    assert body["model"] == "gpt-4o-mini"

    t1 = result["threads"][0]
    assert set(t1["keyword"]) == {"en", "zh"}
    assert set(t1["gloss"]) == {"en", "zh"}
    assert set(t1["why_now"]) == {"en", "zh"}
    # angle ground truth is embedded from the resolved item, not the model
    a0, a1 = t1["angles"]
    assert a0["item_id"] == "item1"
    assert a0["section"] == "news"
    assert a0["source"] == "Alpha"
    assert a0["url"] == "https://ex.test/1"
    assert a0["full_text_file"] == "articles/news/item1.json"
    # item2 has no full-text file -> the key is simply absent
    assert "full_text_file" not in a1
    assert a1["item_id"] == "item2"


@responses.activate
def test_private_scope_assigns_p_ids():
    responses.post(CHAT_URL, json=completion([
        thread([angle(1), angle(2)]),
        thread([angle(1), angle(2)]),
    ]))
    pay = payloads([
        item(1, source_id="s1", section="career"),
        item(2, source_id="s2", section="career"),
    ], section="career")
    result = generate_threads(pay, ENV, make_session(), scope="private")
    assert result["scope"] == "private"
    assert [t["id"] for t in result["threads"]] == ["p1", "p2"]


# ---- input caps ---------------------------------------------------------

@responses.activate
def test_input_caps_news_and_papers_separately():
    responses.post(CHAT_URL, json=completion([
        thread([angle(1), angle(2)]), thread([angle(1), angle(2)]),
    ]))
    news = [item(i, source_id=f"s{i % 2}", source=f"N{i}", title=f"News {i}")
            for i in range(35)]
    papers = [item(100 + i, source_id="p", source=f"P{i}", kind="paper",
                   title=f"Paper {i}", score=0.5 - i * 0.001)
              for i in range(20)]
    pay = {
        "news": {"meta": {"kind": "news"}, "items": news},
        "papers": {"meta": {"kind": "papers"}, "items": papers},
    }
    generate_threads(pay, ENV, make_session(), scope="public")
    prompt = json.loads(responses.calls[0].request.body)["messages"][1]["content"]
    # 30 news kept, 31st dropped
    assert "News 29" in prompt and "News 30" not in prompt
    # 12 papers kept, 13th dropped
    assert "Paper 11" in prompt and "Paper 12" not in prompt


@responses.activate
def test_private_pool_flat_cap():
    responses.post(CHAT_URL, json=completion([
        thread([angle(1), angle(2)]), thread([angle(1), angle(2)]),
    ]))
    items = [item(i, source_id=f"s{i % 2}", title=f"Priv {i}",
                  score=1.0 - i * 0.001) for i in range(40)]
    generate_threads(payloads(items), ENV, make_session(), scope="private")
    prompt = json.loads(responses.calls[0].request.body)["messages"][1]["content"]
    assert "Priv 29" in prompt and "Priv 30" not in prompt


# ---- normalization / anti-hallucination --------------------------------

@responses.activate
def test_single_source_thread_dropped_others_kept():
    # thread B references two items from the SAME source -> < 2 distinct
    # sources -> dropped; the two valid threads survive.
    responses.post(CHAT_URL, json=completion([
        thread([angle(1), angle(2)]),
        thread([angle(1), angle(3)], keyword={"en": "SOLO", "zh": "独"}),
        thread([angle(1), angle(2)]),
    ]))
    result = generate_threads(
        two_source_payload(), ENV, make_session(), scope="public")
    assert len(result["threads"]) == 2
    assert all(t["keyword"]["en"] != "SOLO" for t in result["threads"])


@responses.activate
def test_out_of_range_ref_dropped():
    responses.post(CHAT_URL, json=completion([
        thread([angle(1), angle(2), angle(99)]),
        thread([angle(1), angle(2), angle(99)]),
    ]))
    result = generate_threads(
        two_source_payload(), ENV, make_session(), scope="public")
    for t in result["threads"]:
        assert len(t["angles"]) == 2
        assert {a["item_id"] for a in t["angles"]} == {"item1", "item2"}


@responses.activate
def test_duplicate_item_ref_deduped():
    responses.post(CHAT_URL, json=completion([
        thread([angle(1), angle(1), angle(2)]),
        thread([angle(1), angle(2)]),
    ]))
    result = generate_threads(
        two_source_payload(), ENV, make_session(), scope="public")
    assert [a["item_id"] for a in result["threads"][0]["angles"]] == ["item1", "item2"]


@responses.activate
def test_cap_at_max_threads():
    responses.post(CHAT_URL, json=completion(
        [thread([angle(1), angle(2)]) for _ in range(5)]))
    result = generate_threads(
        two_source_payload(), ENV, make_session(), scope="public", max_threads=2)
    assert len(result["threads"]) == 2


@responses.activate
def test_phrase_clipped_to_eight_words():
    long_en = "one two three four five six seven eight nine ten eleven"
    responses.post(CHAT_URL, json=completion([
        thread([angle(1, en=long_en), angle(2)]),
        thread([angle(1), angle(2)]),
    ]))
    result = generate_threads(
        two_source_payload(), ENV, make_session(), scope="public")
    phrase = result["threads"][0]["angles"][0]["phrase"]["en"]
    assert phrase == "one two three four five six seven eight…"


@responses.activate
def test_bad_convergence_coerced_to_mixed():
    responses.post(CHAT_URL, json=completion([
        thread([angle(1), angle(2)], convergence="wildly-off"),
        thread([angle(1), angle(2)], convergence="divergent"),
    ]))
    result = generate_threads(
        two_source_payload(), ENV, make_session(), scope="public")
    assert result["threads"][0]["convergence"] == "mixed"
    assert result["threads"][1]["convergence"] == "divergent"


@responses.activate
def test_relates_to_resolved_self_and_dangling_dropped():
    responses.post(CHAT_URL, json=completion([
        thread([angle(1), angle(2)], relates_to=[2, 1, 99]),
        thread([angle(1), angle(2)]),
    ]))
    result = generate_threads(
        two_source_payload(), ENV, make_session(), scope="public")
    # position 2 -> t2 kept; self (1) and dangling (99) dropped
    assert result["threads"][0]["relates_to"] == ["t2"]
    assert result["threads"][1]["relates_to"] == []


@responses.activate
def test_html_stripped_from_llm_strings():
    responses.post(CHAT_URL, json=completion([
        thread([angle(1, en="<b>bold</b> plain"), angle(2)],
               gloss={"en": "<i>italic</i> text", "zh": "释义"}),
        thread([angle(1), angle(2)]),
    ]))
    result = generate_threads(
        two_source_payload(), ENV, make_session(), scope="public")
    t0 = result["threads"][0]
    assert t0["gloss"]["en"] == "italic text"
    assert "<" not in t0["angles"][0]["phrase"]["en"]
    assert t0["angles"][0]["phrase"]["en"] == "bold plain"


@responses.activate
def test_why_now_clipped_at_160():
    long_en = "x" * 300
    responses.post(CHAT_URL, json=completion([
        thread([angle(1), angle(2)], why_now={"en": long_en, "zh": "此刻"}),
        thread([angle(1), angle(2)]),
    ]))
    result = generate_threads(
        two_source_payload(), ENV, make_session(), scope="public")
    assert WHY_NOW_CLIP == 160
    why_now = result["threads"][0]["why_now"]["en"]
    # clip() keeps WHY_NOW_CLIP chars and marks the cut with an ellipsis
    assert why_now == "x" * WHY_NOW_CLIP + "…"


# ---- prompt: item dates + reader interests ------------------------------

@responses.activate
def test_prompt_carries_item_dates_when_present():
    responses.post(CHAT_URL, json=completion([
        thread([angle(1), angle(2)]), thread([angle(1), angle(2)]),
    ]))
    pay = payloads([
        item(1, source_id="s1", published_at="2026-07-22T10:00:00Z"),
        item(2, source_id="s2"),
    ])
    generate_threads(pay, ENV, make_session(), scope="public", now=NOW)
    prompt = json.loads(responses.calls[0].request.body)["messages"][1]["content"]
    assert "[1] (2026-07-22) Title 1 (Source One) [news]:" in prompt
    # an item without published_at simply omits the parenthesized date
    assert "[2] Title 2 (Source One) [news]:" in prompt


@responses.activate
def test_prompt_reader_interests_line_and_today():
    responses.post(CHAT_URL, json=completion([
        thread([angle(1), angle(2)]), thread([angle(1), angle(2)]),
    ]))
    generate_threads(two_source_payload(), ENV, make_session(), scope="public",
                     interests=["chips", "  ", "urban design"], now=NOW)
    system = json.loads(responses.calls[0].request.body)["messages"][0]["content"]
    assert "The reader's declared interests: chips, urban design." in system
    assert "2026-07-24" in system
    assert "__READER__" not in system and "__TODAY__" not in system


@responses.activate
def test_prompt_falls_back_without_interests():
    responses.post(CHAT_URL, json=completion([
        thread([angle(1), angle(2)]), thread([angle(1), angle(2)]),
    ]))
    generate_threads(two_source_payload(), ENV, make_session(), scope="public",
                     interests=[], now=NOW)
    system = json.loads(responses.calls[0].request.body)["messages"][0]["content"]
    assert "No reader interests are configured" in system
    assert "declared interests:" not in system


# ---- timeline -----------------------------------------------------------

@responses.activate
def test_timeline_sorted_and_ref_resolved():
    responses.post(CHAT_URL, json=completion([
        thread([angle(1), angle(2)], timeline=[
            point("2026-07-22", en="rules land", n=1),
            point("2026-03", en="first curbs"),
        ]),
        thread([angle(1), angle(2)]),
    ]))
    pay = two_source_payload(full_text_file="articles/news/item1.json")
    result = generate_threads(pay, ENV, make_session(), scope="public", now=NOW)

    tl = result["threads"][0]["timeline"]
    assert [p["date"] for p in tl] == ["2026-03", "2026-07-22"]
    # unreferenced point carries no ground truth at all
    assert "item_id" not in tl[0] and "url" not in tl[0]
    assert tl[1]["item_id"] == "item1"
    assert tl[1]["section"] == "news"
    assert tl[1]["source"] == "Alpha"
    assert tl[1]["url"] == "https://ex.test/1"
    assert tl[1]["full_text_file"] == "articles/news/item1.json"
    # the second thread emitted no timeline -> the key is simply absent
    assert "timeline" not in result["threads"][1]


@responses.activate
def test_timeline_drops_invalid_and_future_dates():
    responses.post(CHAT_URL, json=completion([
        thread([angle(1), angle(2)], timeline=[
            point("2026-03-01", en="kept one"),
            point("last week", en="relative"),
            point("2026-02-31", en="impossible"),
            point("1975-01-01", en="prehistoric"),
            point("2026-08-01", en="future"),
            point("2026-04-01", en="kept two"),
        ]),
        thread([angle(1), angle(2)], timeline=[
            point("2026-13-01", en="only bad"),
            point("2026-04-02", en="lone survivor"),
        ]),
    ]))
    result = generate_threads(
        two_source_payload(), ENV, make_session(), scope="public", now=NOW)
    assert [p["label"]["en"] for p in result["threads"][0]["timeline"]] == [
        "kept one", "kept two"]
    # a single survivor is below TIMELINE_MIN_POINTS -> no key, thread kept
    assert "timeline" not in result["threads"][1]


@responses.activate
def test_timeline_cap_keeps_origin_and_latest():
    responses.post(CHAT_URL, json=completion([
        thread([angle(1), angle(2)], timeline=[
            point(f"2026-01-{d:02d}", en=f"day {d}") for d in range(1, 10)
        ]),
        thread([angle(1), angle(2)]),
    ]))
    result = generate_threads(
        two_source_payload(), ENV, make_session(), scope="public", now=NOW)
    labels = [p["label"]["en"] for p in result["threads"][0]["timeline"]]
    assert labels == ["day 1", "day 5", "day 6", "day 7", "day 8", "day 9"]


@responses.activate
def test_timeline_dedupes_identical_points():
    responses.post(CHAT_URL, json=completion([
        thread([angle(1), angle(2)], timeline=[
            point("2026-03-01", en="same", zh="同"),
            point("2026-03-01", en="same", zh="同"),
            point("2026-04-01", en="other"),
        ]),
        thread([angle(1), angle(2)]),
    ]))
    result = generate_threads(
        two_source_payload(), ENV, make_session(), scope="public", now=NOW)
    tl = result["threads"][0]["timeline"]
    assert [p["label"]["en"] for p in tl] == ["same", "other"]


@responses.activate
def test_timeline_labels_clipped_and_html_stripped():
    responses.post(CHAT_URL, json=completion([
        thread([angle(1), angle(2)], timeline=[
            point("2026-03-01", en="<b>one</b> two three four five six seven",
                  zh="字" * 40),
            point("2026-04-01"),
        ]),
        thread([angle(1), angle(2)]),
    ]))
    result = generate_threads(
        two_source_payload(), ENV, make_session(), scope="public", now=NOW)
    label = result["threads"][0]["timeline"][0]["label"]
    assert label["en"] == "one two three four five six…"
    assert len(label["zh"]) <= TIMELINE_LABEL_ZH_CLIP + 1


@responses.activate
def test_timeline_bad_item_ref_keeps_the_point():
    responses.post(CHAT_URL, json=completion([
        thread([angle(1), angle(2)], timeline=[
            point("2026-03-01", en="dangling", n=99),
            point("2026-04-01", en="fine"),
        ]),
        thread([angle(1), angle(2)]),
    ]))
    result = generate_threads(
        two_source_payload(), ENV, make_session(), scope="public", now=NOW)
    tl = result["threads"][0]["timeline"]
    assert [p["label"]["en"] for p in tl] == ["dangling", "fine"]
    assert "item_id" not in tl[0]


@responses.activate
def test_malformed_timeline_never_drops_the_thread():
    # Every shape the schema does NOT police: the thread must still survive,
    # just without a timeline key.
    for bad in ("not a list", [], [{"date": 5}], [{"nope": 1}], 42,
                [{"date": "2026-03-01", "label": {"en": "", "zh": ""}},
                 {"date": "2026-04-01", "label": "not a dict"}]):
        responses.reset()
        responses.post(CHAT_URL, json=completion([
            thread([angle(1), angle(2)], timeline=bad),
            thread([angle(1), angle(2)]),
        ]))
        result = generate_threads(
            two_source_payload(), ENV, make_session(), scope="public", now=NOW)
        assert len(result["threads"]) == 2
        assert "timeline" not in result["threads"][0]


@responses.activate
def test_absent_timeline_field_is_backcompat():
    responses.post(CHAT_URL, json=completion([
        thread([angle(1), angle(2)]), thread([angle(1), angle(2)]),
    ]))
    result = generate_threads(
        two_source_payload(), ENV, make_session(), scope="public", now=NOW)
    assert all("timeline" not in t for t in result["threads"])


# ---- failure modes ------------------------------------------------------

@responses.activate
def test_malformed_json_returns_none():
    responses.post(CHAT_URL, json={
        "choices": [{"message": {"content": "not json at all"}}]})
    assert generate_threads(
        two_source_payload(), ENV, make_session(), scope="public") is None


@responses.activate
def test_below_min_threads_returns_none():
    responses.post(CHAT_URL, json=completion([thread([angle(1), angle(2)])]))
    assert generate_threads(
        two_source_payload(), ENV, make_session(), scope="public") is None


@responses.activate
def test_http_error_public_returns_none():
    responses.post(CHAT_URL, status=500)
    assert generate_threads(
        two_source_payload(), ENV, make_session(), scope="public") is None


@responses.activate
def test_private_scope_error_withholds_detail(capsys):
    # A 500 body carrying a private marker title must never reach stdout on
    # the private path — public Actions logs. The public path may echo (masked)
    # detail, but the private path prints only the type name.
    marker = "ZZ_SECRET_PRIVATE_TITLE_ZZ"
    responses.post(CHAT_URL, status=500, body=marker)
    pay = payloads([
        item(1, source_id="s1", section="career", title=marker),
        item(2, source_id="s2", section="career"),
    ], section="career")
    result = generate_threads(pay, ENV, make_session(), scope="private")
    assert result is None
    out = capsys.readouterr().out
    assert marker not in out
    assert "[threads:private] error:" in out
    assert "(detail withheld)" in out
