"""Threads · 线索 — LLM keyword aggregation across sources.

One bilingual LLM call per scope surfaces up to ``max_threads`` keyword-themes
that at least two *different* sources touched today. Each thread carries a
cognitively-light bilingual gloss, a "why now" occasion line, a convergence
verdict, and per-source *angles* that the pipeline resolves back to ground
truth (item id / section / source / url / full-text file) so the model can
never fabricate a link — out-of-range refs and single-source threads are
dropped here, not trusted from the model.

Two fully separated scopes:

- ``scope="public"``  — reads only non-private-category payloads.
- ``scope="private"`` — reads only ``category:"private"`` payloads; its output
  is always encrypted by the caller and NEVER written as plaintext. Failure
  logging on this path is detail-free (public Actions logs): exactly
  ``[threads:private] error: <ExceptionTypeName> (detail withheld)``.

Off by default the same way summarize.py is: no ``LLM_API_KEY``,
``LLM_THREADS_ENABLED=0``, an empty pool, or a single-source pool all return
``None`` before any HTTP call.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Mapping

import jsonschema
import requests

from .llm import extract_json, post_chat, resolve_endpoint, resolve_extra_body
from .models import clip, strip_html

# Input caps (per bilingual call). News/papers are capped separately for the
# public scope so a busy news day can't crowd papers out of the pool; the
# private pool is a single flat cap.
MAX_INPUT_NEWS = 30
MAX_INPUT_PAPERS = 12
MAX_INPUT_PRIVATE = 30
MAX_INTERESTS = 12  # prompt-size bound on interests.keywords
SUMMARY_CLIP = 200

# Reasoning-capable models spend part of this same budget on hidden
# chain-of-thought before emitting visible content; in production
# deepseek-v4-flash (thinking on by default) exhausted the whole 4000 on
# reasoning and returned finish_reason="length" with empty content on every
# scheduled run. 16000 gives real headroom while staying under the smallest
# common completion cap among default endpoints (gpt-4o-mini's 16384);
# max_tokens is a cap, not spend. Where the provider supports it, prefer
# disabling thinking via LLM_EXTRA_BODY (docs/CONFIG_REFERENCE.md §4a).
THREADS_MAX_TOKENS = 16000

MIN_THREADS = 2  # fewer than this and we fall back to Highlights, not a thin block

KEYWORD_CLIP = 40
GLOSS_CLIP = 240
WHY_NOW_CLIP = 160  # a relevance line carries two clauses, not just an occasion
PHRASE_MAX_WORDS = 8
PHRASE_ZH_CLIP = 32  # safety clip for the zh angle phrase (prompt asks for ≤16字)

# Per-thread event timeline (optional). The model may emit dated milestones;
# everything below is validated here, never trusted from the model.
TIMELINE_MAX_POINTS = 6
TIMELINE_MIN_POINTS = 2  # fewer surviving points and we emit no timeline at all
TIMELINE_LABEL_MAX_WORDS = 6
TIMELINE_LABEL_ZH_CLIP = 24  # safety clip for the zh label (prompt asks for ≤12字)
TIMELINE_MIN_YEAR = 1990
TIMELINE_DATE_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")

CONVERGENCE_VALUES = {"convergent", "mixed", "divergent"}

_BILINGUAL_SCHEMA = {
    "type": "object",
    "required": ["en", "zh"],
    "properties": {
        "en": {"type": "string"},
        "zh": {"type": "string"},
    },
}

# Validated per-thread (invalid threads are dropped individually, valid ones
# kept) rather than validating the whole response as a unit.
THREAD_SCHEMA = {
    "type": "object",
    "required": ["keyword", "gloss", "why_now", "convergence", "angles"],
    "properties": {
        "keyword": _BILINGUAL_SCHEMA,
        "gloss": _BILINGUAL_SCHEMA,
        "why_now": _BILINGUAL_SCHEMA,
        "convergence": {"type": "string"},
        "relates_to": {"type": "array", "items": {"type": "integer"}},
        "angles": {
            "type": "array",
            "minItems": 2,
            "items": {
                "type": "object",
                "required": ["item", "phrase"],
                "properties": {
                    "item": {"type": "integer"},
                    "phrase": _BILINGUAL_SCHEMA,
                },
            },
        },
    },
}

RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["threads"],
    "properties": {
        "threads": {"type": "array", "items": THREAD_SCHEMA},
    },
}

# JSON-mode requirement (same pattern as summarize.py): the literal word
# "json" plus a shown example of the exact shape. "__MAX_THREADS__",
# "__READER__" and "__TODAY__" are substituted per call.
SYSTEM_PROMPT = (
    "You are the thread editor for a personal news dashboard. You are given a "
    "numbered list of today's items across several sources; an item may carry "
    "its publication date in parentheses before the title. __READER__ Find up "
    "to __MAX_THREADS__ keyword-themes where AT LEAST TWO DIFFERENT SOURCES "
    "land on the same topic today — a theme only one source touches is not a "
    "thread. For each thread write: a short bilingual keyword (en + zh); a "
    "cognitively light gloss of 1-2 sentences, plain and possibly a little "
    "poetic, that a tired reader can absorb at a glance (en + zh); a one-line "
    "'why_now' note telling the reader why this theme is relevant to THEM "
    "today — tie it to a declared interest when one genuinely fits, otherwise "
    "to what concretely changed today; address the reader as 'you', name the "
    "hook, never flatter (en + zh); and, for "
    "every supporting item, an angle {\"item\": <the number from the list>, "
    "\"phrase\": {\"en\": \"how THAT source frames the theme, <=8 words\", "
    "\"zh\": \"<=16 characters\"}}. Reference items only by their number; do "
    "not invent items. Give each thread a convergence verdict: 'convergent' "
    "when the sources agree, 'mixed' when they partly diverge, 'divergent' "
    "when they clash. Optionally add relates_to: the numbers of OTHER threads "
    "in this same answer that connect to this one. Where a thread's story "
    "clearly unfolds over time, also add \"timeline\": 3-6 dated milestones, "
    "oldest first, tracing how the theme arose and where it stands as of "
    "__TODAY__; each milestone is {\"date\": \"YYYY-MM-DD\" or \"YYYY-MM\", "
    "\"label\": {\"en\": \"<=6 words\", \"zh\": \"<=12 characters\"}, "
    "\"item\": <optional item number>}. Use only dates the items carry or "
    "state — never guess one, never a date after __TODAY__ — and omit "
    "timeline entirely when the theme has no real history. Respond with a "
    "single json object shaped exactly like this example (same keys, your own "
    "values):\n"
    '{"threads": [{"keyword": {"en": "compute sovereignty", "zh": "算力主权"}, '
    '"gloss": {"en": "Nations race to own the chips that own the future.", '
    '"zh": "各国竞相掌握决定未来的芯片。"}, "why_now": {"en": "You follow chip '
    'policy: today two new export rules redraw it.", "zh": "你关注芯片政策，'
    '今日两项新出口规定重划版图。"}, "convergence": "mixed", "relates_to": [2], '
    '"timeline": [{"date": "2026-03", "label": {"en": "first export curbs", '
    '"zh": "首轮出口管制"}}, {"date": "2026-06-18", "label": {"en": "allies '
    'join the rules", "zh": "盟友加入规则"}}, {"date": "2026-07-22", "label": '
    '{"en": "two new rules land", "zh": "两项新规落地"}, "item": 1}], '
    '"angles": [{"item": 1, "phrase": {"en": '
    '"frames it as security", "zh": "视为安全议题"}}, {"item": 4, "phrase": '
    '{"en": "frames it as trade", "zh": "视为贸易议题"}}]}]}'
)

# Substituted for "__READER__" per call (see generate_threads).
READER_NO_INTERESTS = (
    "No reader interests are configured; infer what matters to this reader "
    "from the mix of sources and sections."
)


def _pool_items(payloads: dict[str, dict], scope: str) -> list[dict]:
    """Flatten payload items, sort by score desc, cap, and return an ordered
    list whose position (index + 1) is the number the prompt shows the model."""
    pooled: list[tuple[str, dict]] = []
    for payload in payloads.values():
        kind = (payload.get("meta") or {}).get("kind", "news")
        for it in payload.get("items", []):
            pooled.append((kind, it))
    pooled.sort(key=lambda pair: pair[1].get("score") or 0, reverse=True)

    if scope == "private":
        return [it for _, it in pooled][:MAX_INPUT_PRIVATE]

    items: list[dict] = []
    counts = {"news": 0, "papers": 0}
    for kind, it in pooled:
        bucket = "papers" if kind == "papers" else "news"
        cap = MAX_INPUT_PAPERS if bucket == "papers" else MAX_INPUT_NEWS
        if counts[bucket] < cap:
            items.append(it)
            counts[bucket] += 1
    return items


def _prompt_lines(items: list[dict]) -> str:
    lines = []
    for i, it in enumerate(items, start=1):
        title = strip_html(it.get("title") or "").strip()
        source = strip_html(it.get("source") or "").strip()
        kind = it.get("kind") or "news"
        summary = clip(strip_html(it.get("summary") or ""), SUMMARY_CLIP)
        # Dates anchor the timeline ask; items without one simply omit it.
        published = str(it.get("published_at") or "")[:10]
        stamp = f"({published}) " if published else ""
        lines.append(f"[{i}] {stamp}{title} ({source}) [{kind}]: {summary}")
    return "\n".join(lines)


def _clip_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "…"


def _bilingual(raw, clip_len: int) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "en": clip(strip_html(str(raw.get("en") or "")), clip_len),
        "zh": clip(strip_html(str(raw.get("zh") or "")), clip_len),
    }


def _parse_timeline_date(value) -> date | None:
    """Accept ``YYYY-MM-DD`` or ``YYYY-MM`` (day 1) and return a real date, or
    ``None`` for anything malformed, impossible, or prehistoric."""
    if not isinstance(value, str) or not TIMELINE_DATE_RE.match(value):
        return None
    try:
        parsed = datetime.strptime(
            value if len(value) == 10 else f"{value}-01", "%Y-%m-%d").date()
    except ValueError:  # e.g. 2026-02-31
        return None
    if parsed.year < TIMELINE_MIN_YEAR:
        return None
    return parsed


def _normalize_timeline(raw, items: list[dict], today: date) -> list[dict] | None:
    """Validate the model's optional timeline against ground truth: real past
    dates only, sanitized bilingual labels, and item refs resolved exactly like
    angles (a bad ref drops the ref, never the point). Returns ``None`` when
    fewer than ``TIMELINE_MIN_POINTS`` survive — the field is then simply
    absent, so a malformed timeline never costs an otherwise-valid thread."""
    if not isinstance(raw, list):
        return None
    n = len(items)
    dated: list[tuple[date, dict]] = []
    seen: set[tuple[str, str, str]] = set()
    for p in raw:
        if not isinstance(p, dict):
            continue
        when = _parse_timeline_date(p.get("date"))
        # A timeline traces how a theme arose and where it stands today;
        # anything dated after today belongs in why_now, not here.
        if when is None or when > today:
            continue
        raw_label = p.get("label") if isinstance(p.get("label"), dict) else {}
        label = {
            "en": _clip_words(
                strip_html(str(raw_label.get("en") or "")).strip(),
                TIMELINE_LABEL_MAX_WORDS),
            "zh": clip(strip_html(str(raw_label.get("zh") or "")).strip(),
                       TIMELINE_LABEL_ZH_CLIP),
        }
        if not label["en"] and not label["zh"]:
            continue
        key = (p["date"], label["en"], label["zh"])
        if key in seen:
            continue
        seen.add(key)
        point = {"date": p["date"], "label": label}
        ref = p.get("item")
        if isinstance(ref, int) and not isinstance(ref, bool) and 1 <= ref <= n:
            item = items[ref - 1]
            point["item_id"] = item.get("id") or ""
            point["section"] = item.get("section") or ""
            point["source"] = strip_html(str(item.get("source") or "")).strip()
            point["url"] = item.get("url") or ""
            # Same rule as angles: an in-app reader link only when the resolved
            # item actually has a full-text file.
            if item.get("full_text_file"):
                point["full_text_file"] = item["full_text_file"]
        dated.append((when, point))

    dated.sort(key=lambda pair: pair[0])
    points = [point for _, point in dated]
    if len(points) > TIMELINE_MAX_POINTS:
        # Keep the origin plus the most recent stretch — the two anchors that
        # make "how it arose → where it stands" legible.
        points = points[:1] + points[-(TIMELINE_MAX_POINTS - 1):]
    if len(points) < TIMELINE_MIN_POINTS:
        return None
    return points


def _normalize_thread(raw: dict, items: list[dict], today: date) -> dict | None:
    """Resolve the model's numeric refs against ground truth and sanitize
    every model-authored string. Returns ``None`` for a thread that, after
    dropping out-of-range refs and deduping by resolved item, does not link
    at least two distinct sources."""
    n = len(items)
    seen_item_ids: set[str] = set()
    source_ids: set[str] = set()
    angles: list[dict] = []
    for a in raw.get("angles", []):
        if not isinstance(a, dict):
            continue
        ref = a.get("item")
        if not isinstance(ref, int) or isinstance(ref, bool) or ref < 1 or ref > n:
            continue
        item = items[ref - 1]
        item_id = item.get("id") or ""
        if item_id in seen_item_ids:
            continue
        seen_item_ids.add(item_id)
        source_ids.add(item.get("source_id") or item.get("source") or "")
        phrase = a.get("phrase") if isinstance(a.get("phrase"), dict) else {}
        angle = {
            "item_id": item_id,
            "section": item.get("section") or "",
            "source": strip_html(str(item.get("source") or "")).strip(),
            "phrase": {
                "en": _clip_words(
                    strip_html(str(phrase.get("en") or "")).strip(),
                    PHRASE_MAX_WORDS),
                "zh": clip(strip_html(str(phrase.get("zh") or "")).strip(),
                           PHRASE_ZH_CLIP),
            },
            "url": item.get("url") or "",
        }
        # Only carry an in-app reader link when the resolved item actually has
        # a full-text file — never fabricated from model output.
        if item.get("full_text_file"):
            angle["full_text_file"] = item["full_text_file"]
        angles.append(angle)

    if len(source_ids) < 2:
        return None

    convergence = raw.get("convergence")
    if convergence not in CONVERGENCE_VALUES:
        convergence = "mixed"

    out = {
        "keyword": _bilingual(raw.get("keyword"), KEYWORD_CLIP),
        "gloss": _bilingual(raw.get("gloss"), GLOSS_CLIP),
        "why_now": _bilingual(raw.get("why_now"), WHY_NOW_CLIP),
        "convergence": convergence,
        "angles": angles,
        # 1-based response positions of related threads; resolved to ids by
        # _link_relates once every surviving thread has an id.
        "_relates": [r for r in (raw.get("relates_to") or [])
                     if isinstance(r, int) and not isinstance(r, bool)],
    }
    timeline = _normalize_timeline(raw.get("timeline"), items, today)
    if timeline is not None:
        out["timeline"] = timeline
    return out


def _link_relates(threads: list[dict], positions: list[int]) -> None:
    """Map each surviving thread's 1-based response positions to assigned ids,
    dropping self-references and dangling refs (positions that did not
    survive)."""
    pos_to_id = {pos: t["id"] for t, pos in zip(threads, positions)}
    for t in threads:
        linked: list[str] = []
        seen: set[str] = set()
        for r in t.pop("_relates", []):
            target = pos_to_id.get(r)
            if target and target != t["id"] and target not in seen:
                seen.add(target)
                linked.append(target)
        t["relates_to"] = linked


def _log_error(scope: str, exc: Exception, api_key: str) -> None:
    if scope == "private":
        # Public Actions logs: never a title, count, status, or body.
        print(f"[threads:private] error: {type(exc).__name__} (detail withheld)")
        return
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        status = exc.response.status_code
        detail = exc.response.text.strip().replace(api_key, "***")[:200]
        print(f"[threads:public] error: HTTPError ({status}) {detail}")
    else:
        detail = str(exc)[:200].replace(api_key, "***")
        print(f"[threads:public] error: {type(exc).__name__}: {detail}")


def generate_threads(payloads: dict[str, dict], env: Mapping[str, str],
                     session: requests.Session, *, scope: str,
                     max_threads: int = 6,
                     interests: list[str] | None = None,
                     now: datetime | None = None) -> dict | None:
    api_key = env.get("LLM_API_KEY", "").strip()
    if not api_key:
        return None
    if env.get("LLM_THREADS_ENABLED") == "0":
        return None

    items = _pool_items(payloads, scope)
    if not items:
        return None
    distinct = {(it.get("source_id") or it.get("source") or "") for it in items}
    if len(distinct) < 2:
        # A thread needs two different sources; a single-source pool can't
        # produce one, so skip the call entirely (zero HTTP).
        return None

    today = (now or datetime.now(timezone.utc)).date()
    # Owner-authored config, but sanitized like every other prompt input.
    keywords = [clip(strip_html(str(k)).strip(), KEYWORD_CLIP)
                for k in (interests or [])]
    keywords = [k for k in keywords if k][:MAX_INTERESTS]
    reader = (
        f"The reader's declared interests: {', '.join(keywords)}. Weigh what "
        "matters to them against these."
    ) if keywords else READER_NO_INTERESTS
    system = (SYSTEM_PROMPT
              .replace("__MAX_THREADS__", str(max_threads))
              .replace("__READER__", reader)
              .replace("__TODAY__", today.isoformat()))

    base_url, model = resolve_endpoint(env)
    try:
        content = post_chat(
            base_url, api_key, model,
            [{"role": "system", "content": system},
             {"role": "user", "content": _prompt_lines(items)}],
            session, json_mode=True, max_tokens=THREADS_MAX_TOKENS,
            extra_body=resolve_extra_body(env),
        )
        data = extract_json(content)
    except Exception as exc:  # noqa: BLE001 — enrichment must not fail builds
        _log_error(scope, exc, api_key)
        return None

    raw_threads = data.get("threads") if isinstance(data, dict) else None
    if not isinstance(raw_threads, list):
        return None

    validator = jsonschema.Draft202012Validator(THREAD_SCHEMA)
    threads: list[dict] = []
    positions: list[int] = []
    for pos, raw in enumerate(raw_threads, start=1):
        if not isinstance(raw, dict) or not validator.is_valid(raw):
            continue
        thread = _normalize_thread(raw, items, today)
        if thread is None:
            continue
        threads.append(thread)
        positions.append(pos)
        if len(threads) >= max_threads:
            break

    if len(threads) < MIN_THREADS:
        return None

    prefix = "p" if scope == "private" else "t"
    for i, thread in enumerate(threads, start=1):
        thread["id"] = f"{prefix}{i}"
    _link_relates(threads, positions)
    return {"scope": scope, "threads": threads}
