"""Offline tests for the source-discovery helper (scripts/discover_source.py)."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import discover_source as ds
from conftest import FIXED_NOW
from newsdash.config import Config, Ranking, SiteConfig, SourceConfig, Windows

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "discover"


def _config(*sources: SourceConfig) -> Config:
    site = SiteConfig(title="t", subtitle="", visibility="public",
                      languages=["en"], default_language="en", theme="bear",
                      timezone="UTC", windows=Windows(), ranking=Ranking())
    return Config(site=site, sources=list(sources), tag_rules={},
                  interests_keywords=[], interests_boost=0.15)


# --------------------------------------------------------------------------- #
# is_capability_url
# --------------------------------------------------------------------------- #

# Any of these must be REFUSED. A leaked fake secret in this list would show up
# in test output; FAKE_TOKENS (below) is asserted absent from all CLI output.
CAPABILITY_URLS = [
    # --- original regression set ---
    "https://example.com/calendar/ical/abcdefghijklmnopqrstuvwx/private/feed.ics",
    "https://feeds.example.com/rss?token=deadbeefdeadbeef",
    "https://feeds.example.com/rss?key=abc123",
    "https://feeds.example.com/rss?SIG=xyz",
    "https://site.example.com/private/feed.xml",
    "https://site.example.com/AbCdEf0123456789AbCdEf0123456789/feed",  # opaque token
    "https://calendar.google.com/calendar/ical/whatever/basic.ics",
    # --- FIX 2: broadened query-param NAME substring matching ---
    "https://feeds.example.com/rss?access_token=deadbeefdeadbeef",   # token substring
    "https://feeds.example.com/rss?api_key=abcdef123456",            # key substring
    "https://feeds.example.com/rss?apikey=abcdef123456",             # key substring
    "https://feeds.example.com/rss?hmac=abcdef123456",               # hmac
    "https://feeds.example.com/rss?credential=abcdef123456",         # credential
    # --- X-Amz presigned (name prefix) + S3 host ---
    "https://feeds.example.com/rss?X-Amz-Signature=abcdef&X-Amz-Credential=xyz",
    "https://bucket.s3.amazonaws.com/feed.xml?X-Amz-Expires=3600",
    "https://bucket.s3.us-east-1.amazonaws.com/feed.xml",
    "https://s3.eu-west-1.amazonaws.com/bucket/feed.xml",
    # --- CDN e+st style: opaque VALUE (>= 16) even with an innocuous name ---
    "https://cdn.example.com/video.m3u8?e=1699999999&st=aBcDeFgHiJkLmNoP1234",
    # --- ?feed=<32-char token>: opaque query VALUE ---
    "https://feeds.example.com/rss?feed=deadbeefdeadbeefdeadbeef1234abcd",
    # --- userinfo ---
    "https://alice:s3cr3tpasswordxx@feeds.example.com/rss",
    # --- JWT in a path segment ---
    "https://site.example.com/eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NX0.SflKxwRJSMeKKF2QT4fwpMeJ/feed",
    # --- 20-char MIXED-CASE path token (no digit) ---
    "https://site.example.com/AbCdEfGhIjKlMnOpQrSt/feed",
    # --- fragment #access_token= (OAuth implicit-flow shape) ---
    "https://feeds.example.com/rss#access_token=deadbeefdeadbeef",
    # --- bare opaque token in the fragment ---
    "https://feeds.example.com/rss#deadbeefdeadbeefdeadbeef",
    # --- new capability hosts ---
    "https://outlook.live.com/owa/somecalendarpath/feed",
    "https://hooks.slack.com/services/T00000000/B00000000/abcdefghijkl",
    "https://caldav.icloud.com/12345/calendars/home/",
    "https://p42-caldav.icloud.com/12345/calendars/home/",
    "https://caldav.fastmail.com/dav/calendars/user/feed/",
]

# Fake secret substrings that appear in CAPABILITY_URLS. NONE of these may ever
# reach any CLI output stream (stdout or stderr). Asserted in the CLI tests.
FAKE_TOKENS = [
    "deadbeef",
    "s3cr3tpasswordxx",
    "abcdefghijklmnopqrstuvwx",     # ical path token
    "AbCdEfGhIjKlMnOpQrSt",         # mixed-case path token
    "aBcDeFgHiJkLmNoP1234",         # CDN opaque value
    "eyJhbGci",                     # JWT
]

# Any of these must PASS the gate (false-positive guard).
SAFE_URLS = [
    "https://blog.example.org/feed",
    "https://karpathy.github.io/feed.xml",
    "https://www.example.com/index.xml",
    "https://example.com/rss.xml",
    # WordPress ?feed=rss2 — short, non-opaque value.
    "https://blog.example.org/?feed=rss2",
    # YouTube channel feed — channel_id is an opaque-but-PUBLIC id, allowlisted.
    "https://www.youtube.com/feeds/videos.xml?channel_id=UCabcdefghijklmnopqrstuv",
    # Scholarly API URLs — values carry ':'/'+'/spaces, so never opaque tokens.
    "http://export.arxiv.org/api/query?search_query=all:electron&start=0&max_results=1",
    "https://api.openalex.org/works?filter=from_publication_date:2026-01-01&per-page=25",
    "https://api.crossref.org/works?query=machine+learning&rows=5",
    # A long lowercase, digitless slug is a human slug, not a token.
    "https://blog.example.org/the-quick-brown-fox-jumps-over-lazy/feed",
]


@pytest.mark.parametrize("url", CAPABILITY_URLS)
def test_capability_url_detected(url):
    assert ds.is_capability_url(url) is True


@pytest.mark.parametrize("url", SAFE_URLS)
def test_safe_url_not_flagged(url):
    assert ds.is_capability_url(url) is False


def test_refusal_message_never_contains_url():
    # The refusal text is a constant and must not embed any URL.
    for url in CAPABILITY_URLS:
        assert url not in ds.CAPABILITY_REFUSAL


# --------------------------------------------------------------------------- #
# autodiscover_feeds
# --------------------------------------------------------------------------- #

def test_autodiscover_two_links_resolves_relative_and_absolute():
    html = (FIXTURES / "page_two_links.html").read_bytes()
    feeds = ds.autodiscover_feeds(html, "https://a.example.org/blog/")
    assert feeds == [
        "https://a.example.org/feed.xml",
        "https://cdn.example.org/atom.xml",
    ]


def test_autodiscover_none():
    html = (FIXTURES / "page_no_links.html").read_bytes()
    assert ds.autodiscover_feeds(html, "https://a.example.org/") == []


def test_common_path_candidates():
    cands = ds.common_path_candidates("https://blog.example.org/some/page")
    assert "https://blog.example.org/feed" in cands
    assert "https://blog.example.org/rss.xml" in cands


# --------------------------------------------------------------------------- #
# probe_feed
# --------------------------------------------------------------------------- #

def test_probe_feed_healthy():
    raw = (FIXTURES / "sample_feed.xml").read_bytes()
    stats = ds.probe_feed(raw, FIXED_NOW)
    assert stats["ok"] is True
    assert stats["title"] == "Example Research Blog"
    assert stats["count"] == 3
    assert stats["newest"] == datetime(2026, 7, 6, 8, 0, tzinfo=timezone.utc)
    assert stats["oldest"] == datetime(2026, 6, 22, 8, 0, tzinfo=timezone.utc)
    # 3 items across a 2-week span -> 1.5/week -> weight 0.8
    assert stats["cadence_per_week"] == 1.5
    assert stats["weight"] == 0.8


def test_probe_feed_dateless_flagged_no_crash():
    raw = (FIXTURES / "empty_feed.xml").read_bytes()
    stats = ds.probe_feed(raw, FIXED_NOW)
    assert stats["ok"] is False
    assert stats["count"] == 0
    assert "no dated entries" in stats["error"]


def test_probe_feed_garbage_no_crash():
    stats = ds.probe_feed(b"not xml at all <<<", FIXED_NOW)
    assert stats["ok"] is False


def test_recommend_weight():
    assert ds.recommend_weight(2.0) == 0.8
    assert ds.recommend_weight(1.0) == 0.8
    assert ds.recommend_weight(0.3) == 0.5
    assert ds.recommend_weight(None) == 0.5


# --------------------------------------------------------------------------- #
# opml_feeds
# --------------------------------------------------------------------------- #

def test_opml_feeds_list():
    feeds = ds.opml_feeds((FIXTURES / "sample.opml").read_bytes())
    assert {f["title"] for f in feeds} == {"Karpathy", "A New Blog", "Another New One"}
    assert feeds[0]["xmlUrl"] == "https://karpathy.github.io/feed.xml"


def test_opml_dedupe_against_config_drops_known():
    config = _config(SourceConfig(id="karpathy_blog", type="rss", section="news",
                                  url="https://karpathy.github.io/feed.xml"))
    feeds = ds.opml_feeds((FIXTURES / "sample.opml").read_bytes())
    new = [f for f in feeds
           if not ds.find_duplicates({"url": f["xmlUrl"]}, config)]
    assert [f["title"] for f in new] == ["A New Blog", "Another New One"]


# --------------------------------------------------------------------------- #
# find_duplicates
# --------------------------------------------------------------------------- #

def test_find_duplicates_host_collision():
    config = _config(SourceConfig(id="ex", type="rss", section="news",
                                  url="https://www.example.org/feed"))
    hits = ds.find_duplicates({"url": "https://blog.example.org/atom.xml"}, config)
    assert any(h["kind"] == "host" for h in hits)


def test_find_duplicates_issn_collision():
    config = _config(SourceConfig(id="tcq", type="crossref", section="papers",
                                  issn=["1057-2252", "0361-1434"]))
    hits = ds.find_duplicates({"issn": ["0361-1434"]}, config)
    assert hits and hits[0]["kind"] == "issn"


def test_find_duplicates_id_collision():
    config = _config(SourceConfig(id="karpathy_blog", type="rss", section="news",
                                  url="https://karpathy.github.io/feed.xml"))
    hits = ds.find_duplicates({"id": "karpathy_blog"}, config)
    assert any(h["kind"] == "id" for h in hits)


def test_find_duplicates_new_feed_no_collision():
    config = _config(SourceConfig(id="ex", type="rss", section="news",
                                  url="https://example.org/feed"))
    hits = ds.find_duplicates(
        {"url": "https://brandnew.example.net/rss", "id": "brandnew_example"}, config)
    assert hits == []


def test_slug_for_prefers_title_then_host():
    assert ds.slug_for(title="Dr. Fei-Fei Li") == "dr_fei_fei_li"
    # host slug uses the registrable domain (subdomain dropped)
    assert ds.slug_for(url="https://blog.example.org/feed") == "example"


def test_looks_like_issn():
    assert ds.looks_like_issn("0361-1434")
    assert ds.looks_like_issn("1234-567X")
    assert not ds.looks_like_issn("https://example.com")


# --------------------------------------------------------------------------- #
# CLI smoke
# --------------------------------------------------------------------------- #

def test_cli_probe_capability_url_exits_3_without_network(monkeypatch, capsys):
    def _boom():
        raise AssertionError("network must not be touched for a capability URL")
    monkeypatch.setattr(ds, "_session", _boom)

    url = CAPABILITY_URLS[0]
    rc = ds.main(["probe", url])
    assert rc == 3
    captured = capsys.readouterr()
    # The URL must never be echoed back, on stdout or stderr.
    assert url not in captured.out
    assert url not in captured.err


def test_cli_probe_injectable_network(monkeypatch, capsys):
    page = (FIXTURES / "page_two_links.html").read_bytes()
    feed = (FIXTURES / "sample_feed.xml").read_bytes()

    def fake_fetch(url):
        if url.endswith(".html") or url == "https://blog.example.org/":
            return page
        return feed

    monkeypatch.setattr(ds, "_fetch", fake_fetch)
    rc = ds.main(["probe", "https://blog.example.org/"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Example Research Blog" in out
    assert '"type": "rss"' in out


# --------------------------------------------------------------------------- #
# FIX 2 — YouTube false-positive decision (allowlist channel_id on youtube.com)
# --------------------------------------------------------------------------- #

def test_youtube_channel_feed_allowlisted():
    # channel_id is a 24-char opaque-but-public id; on youtube.com it is
    # allowlisted so a plain channel feed is NOT refused.
    assert ds.is_capability_url(
        "https://www.youtube.com/feeds/videos.xml?channel_id=UCabcdefghijklmnopqrstuv"
    ) is False


def test_youtube_allowlist_scoped_to_youtube_host():
    # The same opaque channel_id value on a NON-youtube host is still refused:
    # the allowlist is host-scoped, not a blanket exemption for the param name.
    assert ds.is_capability_url(
        "https://evil.example.com/feed?channel_id=UCabcdefghijklmnopqrstuv"
    ) is True


def test_youtube_non_allowlisted_param_still_refused():
    # A real token param on youtube.com is still refused.
    assert ds.is_capability_url(
        "https://www.youtube.com/feeds/videos.xml?token=deadbeefdeadbeef"
    ) is True


# --------------------------------------------------------------------------- #
# FIX 1 — structural gating: autodiscovered capability <link> not fetched/echoed
# --------------------------------------------------------------------------- #

def test_cli_probe_drops_autodiscovered_capability_link(monkeypatch, capsys):
    page = (FIXTURES / "page_capability_link.html").read_bytes()
    tokened = "https://feeds.example.com/rss?token=deadbeefdeadbeefdeadbeef"

    calls: list[str] = []

    def recording_fetch(url):
        calls.append(url)
        if url.endswith(".html") or url == "https://blog.example.org/":
            return page
        # A capability candidate must never reach here.
        raise AssertionError(f"capability candidate was fetched: {url!r}")

    monkeypatch.setattr(ds, "_fetch", recording_fetch)
    rc = ds.main(["probe", "https://blog.example.org/"])
    assert rc == 1  # only candidate was dropped -> no healthy feed

    # The tokened feed was gated out BEFORE any fetch.
    assert tokened not in calls
    assert calls == ["https://blog.example.org/"]

    cap = capsys.readouterr()
    combined = cap.out + cap.err
    # Neither the URL nor its token is echoed anywhere.
    assert tokened not in combined
    for tok in FAKE_TOKENS:
        assert tok not in combined
    # No "open"/paste entry for the dropped feed: no snippet was produced.
    assert "Ready-to-paste" not in cap.out
    # The drop is reported by placeholder + the fixed message, without the URL.
    assert "untitled #1" in cap.err
    assert "capability URL" in cap.err


def test_cli_probe_json_drops_capability_candidate_without_echo(monkeypatch, capsys):
    page = (FIXTURES / "page_capability_link.html").read_bytes()

    def fake_fetch(url):
        if url.endswith(".html") or url == "https://blog.example.org/":
            return page
        raise AssertionError("capability candidate must not be fetched")

    monkeypatch.setattr(ds, "_fetch", fake_fetch)
    rc = ds.main(["--json", "probe", "https://blog.example.org/"])
    assert rc == 1
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["dropped_capability"] == 1
    assert payload["candidates"] == []          # dropped url absent from candidates
    for tok in FAKE_TOKENS:
        assert tok not in out


# --------------------------------------------------------------------------- #
# FIX 1 — structural gating: OPML capability feeds dropped, never echoed
# --------------------------------------------------------------------------- #

def test_cli_probe_opml_drops_capability_feeds(monkeypatch, capsys):
    # No network is used by OPML probing; stub load_config to an empty config.
    monkeypatch.setattr(ds, "load_config", lambda root: _config())

    rc = ds.main(["probe", "--opml", str(FIXTURES / "capability.opml")])
    assert rc == 0

    cap = capsys.readouterr()
    combined = cap.out + cap.err

    # The two capability feeds never appear by URL or secret.
    assert "calendar.google.com" not in combined
    for tok in FAKE_TOKENS:
        assert tok not in combined

    # The safe feed IS emitted as a snippet.
    assert "newblog.example.net/rss" in cap.out
    assert '"id": "a_new_blog"' in cap.out

    # Drops are reported by title / placeholder + fixed message (no URL).
    assert "My Private Calendar" in cap.err
    assert "untitled #3" in cap.err          # titleless feed -> URL not used as label
    assert ds.CAPABILITY_DROP_MESSAGE in cap.err


def test_cli_probe_opml_json_reports_dropped_capability(monkeypatch, capsys):
    monkeypatch.setattr(ds, "load_config", lambda root: _config())
    rc = ds.main(["--json", "probe", "--opml", str(FIXTURES / "capability.opml")])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["dropped_capability"] == 2
    assert payload["emitted"] == 1
    for tok in FAKE_TOKENS:
        assert tok not in out
    assert "calendar.google.com" not in out


# --------------------------------------------------------------------------- #
# report — health-check a saved source plan (step 2)
# --------------------------------------------------------------------------- #

SAMPLE_FEED = (FIXTURES / "sample_feed.xml").read_bytes()
EMPTY_FEED = (FIXTURES / "empty_feed.xml").read_bytes()


def _plan(*sources):
    return {"schema": "newsdash-source-plan/v1", "sources": list(sources)}


def _by_id(report):
    return {r["id"]: r for r in report["sources"]}


def test_report_classifies_healthy_empty_and_unhealthy():
    plan = _plan(
        {"id": "good", "name": "Good", "category": "open", "type": "rss",
         "section": "news", "url": "https://good.example/feed", "weight": 0.5},
        {"id": "empty", "name": "Empty", "category": "open", "type": "rss",
         "section": "news", "url": "https://empty.example/feed", "weight": 0.8},
        {"id": "broken", "name": "Broken", "category": "open", "type": "rss",
         "section": "news", "url": "https://broken.example/feed", "weight": 0.8},
    )
    feeds = {"https://good.example/feed": SAMPLE_FEED,
             "https://empty.example/feed": EMPTY_FEED,
             "https://broken.example/feed": None}
    report = ds.build_report(plan, now=FIXED_NOW, fetch=lambda u: feeds[u])
    rows = _by_id(report)

    assert rows["good"]["status"] == "ok"
    assert rows["good"]["health"]["count"] == 3
    assert rows["good"]["health"]["recommended_weight"] == 0.8
    # planned 0.5 vs recommended 0.8 -> the recommendation nudges the weight
    assert "consider weight 0.8" in rows["good"]["recommendation"]
    assert rows["empty"]["status"] == "empty"
    assert rows["broken"]["status"] == "unhealthy"
    assert report["summary"] == {
        "total": 3, "ok": 1, "empty": 1, "unhealthy": 1, "private": 0,
        "api": 0, "capability": 0, "with_duplicates": 0,
    }


def test_report_private_source_not_probed():
    calls = []
    plan = _plan({"id": "priv", "name": "Secret feed", "category": "private",
                  "type": "rss", "section": "private", "enabled": "auto",
                  "secret_ref": ["SRC_PRIV_URL"]})

    def fetch(url):
        calls.append(url)
        return SAMPLE_FEED

    report = ds.build_report(plan, now=FIXED_NOW, fetch=fetch)
    row = report["sources"][0]
    assert row["status"] == "private"
    assert row["probed"] is False
    assert calls == []                        # a private source is never fetched


def test_report_capability_url_flagged_never_fetched_or_echoed(capsys):
    calls = []
    cap = "https://feeds.example.com/rss?token=deadbeefdeadbeef"
    plan = _plan({"id": "leak", "name": "Leaky", "category": "open",
                  "type": "rss", "section": "news", "url": cap, "weight": 0.8})

    def fetch(url):
        calls.append(url)
        return SAMPLE_FEED

    report = ds.build_report(plan, now=FIXED_NOW, fetch=fetch)
    row = report["sources"][0]
    assert row["status"] == "capability"
    assert calls == []                        # gated before any fetch
    # the capability URL/token appears nowhere in the serialized report
    blob = json.dumps(report)
    assert cap not in blob and "deadbeef" not in blob and "token=" not in blob


def test_report_scholarly_api_source_marked_not_probed():
    plan = _plan({"id": "arxiv_cl", "name": "arXiv cs.CL", "category": "optional",
                  "type": "arxiv", "section": "papers", "query": "cat:cs.CL"})
    report = ds.build_report(plan, now=FIXED_NOW, fetch=lambda u: SAMPLE_FEED)
    assert report["sources"][0]["status"] == "api"
    assert report["sources"][0]["probed"] is False


def test_report_flags_duplicate_within_plan():
    plan = _plan(
        {"id": "guardian_world", "name": "Guardian World", "category": "open",
         "type": "rss", "section": "news", "url": "https://theguardian.com/world/rss"},
        {"id": "guardian_tech", "name": "Guardian Tech", "category": "open",
         "type": "rss", "section": "news", "url": "https://www.theguardian.com/technology/rss"},
    )
    report = ds.build_report(plan, now=FIXED_NOW, fetch=lambda u: None)
    rows = _by_id(report)
    assert any(d["source_id"] == "guardian_tech" for d in rows["guardian_world"]["duplicates"])
    assert any(d["source_id"] == "guardian_world" for d in rows["guardian_tech"]["duplicates"])
    assert report["summary"]["with_duplicates"] == 2


def test_report_scrubs_credential_in_name():
    # A user pasting a URL/token into the NAME field must not surface it in the
    # (shareable) report — the name falls back to the schema-safe id.
    plan = _plan(
        {"id": "leaky_name", "name": "https://feeds.ex/rss?token=deadbeefsecret",
         "category": "open", "type": "rss", "section": "news",
         "url": "https://ok.example/feed", "weight": 0.8},
    )
    report = ds.build_report(plan, now=FIXED_NOW, fetch=lambda u: SAMPLE_FEED)
    row = report["sources"][0]
    assert row["name"] == "leaky_name"                 # scrubbed to the id
    assert "name hidden" in row["recommendation"]
    assert "deadbeef" not in json.dumps(report) and "token=" not in json.dumps(report)


def test_report_ordinary_long_name_not_scrubbed():
    plan = _plan(
        {"id": "ml", "name": "MachineLearningResearchWeekly", "category": "open",
         "type": "rss", "section": "news", "url": "https://ok.example/feed"},
    )
    report = ds.build_report(plan, now=FIXED_NOW, fetch=lambda u: SAMPLE_FEED)
    assert report["sources"][0]["name"] == "MachineLearningResearchWeekly"


def test_report_ignores_malformed_source_entry():
    plan = {"schema": "newsdash-source-plan/v1",
            "sources": ["not-a-dict", {"id": "good", "name": "Good", "category": "open",
                        "type": "rss", "section": "news", "url": "https://ok.example/feed"}]}
    report = ds.build_report(plan, now=FIXED_NOW, fetch=lambda u: SAMPLE_FEED)
    assert report["summary"]["total"] == 1               # the bad entry is dropped
    assert report["sources"][0]["id"] == "good"


def test_report_json_never_contains_a_url():
    plan = _plan(
        {"id": "good", "name": "Good", "category": "open", "type": "rss",
         "section": "news", "url": "https://good.example/feed", "weight": 0.8},
    )
    report = ds.build_report(plan, now=FIXED_NOW, fetch=lambda u: SAMPLE_FEED)
    blob = json.dumps(report)
    assert "http://" not in blob and "https://" not in blob


def test_cmd_report_writes_file_and_rejects_bad_schema(tmp_path, monkeypatch, capsys):
    plan_path = tmp_path / "sources.plan.json"
    out_path = tmp_path / "report.json"

    plan_path.write_text(json.dumps({"schema": "wrong/v9", "sources": []}))
    rc = ds.cmd_report(plan_path, out_path=out_path, now=FIXED_NOW, as_json=False)
    assert rc == 2 and not out_path.exists()

    plan_path.write_text(json.dumps(_plan(
        {"id": "good", "name": "Good", "category": "open", "type": "rss",
         "section": "news", "url": "https://good.example/feed", "weight": 0.8})))
    monkeypatch.setattr(ds, "_fetch", lambda u: SAMPLE_FEED)
    rc = ds.cmd_report(plan_path, out_path=out_path, now=FIXED_NOW, as_json=False)
    assert rc == 0 and out_path.exists()
    written = json.loads(out_path.read_text())
    assert written["schema"] == "newsdash-source-report/v1"
    assert written["sources"][0]["status"] == "ok"
