import json
from datetime import datetime, timezone
from email.utils import format_datetime

import pytest
import responses

import build as build_mod
from newsdash import crypto

CHAT_URL = "https://api.openai.com/v1/chat/completions"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def llm_completion(**fields):
    payload = {
        "brief": "EN brief",
        "news_summary": "EN news",
        "papers_summary": "EN papers",
        "image_query": "clockwork automatons",
    }
    payload.update(fields)
    return {"choices": [{"message": {"content": json.dumps(payload)}}]}


def apropos_query_completion():
    return {"choices": [{"message": {"content": json.dumps({
        "topic": "competitive pumpkin growing",
        "search_terms": ["pumpkin championship", "giant pumpkin"],
        "why_irrelevant": "Far from this dashboard's usual feed.",
    })}}]}


def apropos_summary_completion():
    return {"choices": [{"message": {"content": json.dumps({
        "choice": 1,
        "summaries": {
            "en": {
                "summary": "A giant pumpkin contest picked a new winner.",
                "why_irrelevant": "A cheerful detour from the usual feed.",
            },
            "zh": {
                "summary": "一场巨型南瓜比赛选出了新冠军。",
                "why_irrelevant": "这是一条轻松的题外话。",
            },
        },
    })}}]}


def gdelt_apropos_response():
    return {"articles": [{
        "title": "Giant pumpkin champion breaks local record",
        "url": "https://example.org/pumpkin",
        "domain": "example.org",
        "seendate": "20260708100000",
    }]}


def rss_with_full_text(url="https://a.example/story"):
    pub = format_datetime(datetime.now(timezone.utc), usegmt=True)
    body = " ".join(f"fulltext-{i}" for i in range(140))
    return f"""<?xml version="1.0"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel><title>T</title>
<item><title>Full story</title><link>{url}</link>
<pubDate>{pub}</pubDate>
<description>Short summary</description>
<content:encoded><![CDATA[<article><p>{body}</p></article>]]></content:encoded>
</item></channel></rss>"""


def test_smoke_zero_secret(tmp_path, monkeypatch, repo_root):
    for var in ("NEWSDASH_PASSPHRASE", "LLM_API_KEY", "SMITHSONIAN_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    out = tmp_path / "data"
    build_mod.main(["--output-dir", str(out), "--smoke"])

    manifest = read(out / "manifest.json")
    assert manifest["status"] == "ok"
    assert manifest["site"]["visibility"] == "public"
    assert "crypto" not in manifest

    by_id = {s["id"]: s for s in manifest["sections"]}
    assert by_id["news"]["file"] == "news.json"
    assert by_id["news"]["encrypted"] is False

    news = read(out / "news.json")
    assert news["items"] == []
    assert (out / "source-status.json").exists()
    assert (out / "archive.json").exists()
    assert manifest["insights_file"] is None
    assert manifest["ai_summary"] == {"enabled": False}


def test_smoke_never_calls_llm_or_smithsonian_even_with_keys_set(tmp_path, monkeypatch):
    # --smoke promises "skip all network fetches" — this must hold even when
    # both optional enrichment secrets are present in the environment.
    monkeypatch.setenv("LLM_API_KEY", "sk-should-not-be-used")
    monkeypatch.setenv("SMITHSONIAN_API_KEY", "dg-should-not-be-used")
    out = tmp_path / "data"
    build_mod.main(["--output-dir", str(out), "--smoke"])

    manifest = read(out / "manifest.json")
    assert manifest["insights_file"] is None
    assert manifest["ai_summary"] == {"enabled": True}  # key present -> "configured"
    assert not (out / "insights.json").exists()
    assert not (out / "insights.enc.json").exists()


def test_smoke_with_private_secrets(tmp_path, monkeypatch, make_repo):
    monkeypatch.setenv("NEWSDASH_PASSPHRASE", "correct horse battery staple")
    monkeypatch.setenv("PRIVATE_FEED_TOKEN", "dummy")
    root = make_repo(sources={"schema_version": 1, "presets": [], "sources": [
        {"id": "private_papers", "category": "private", "type": "openalex",
         "section": "research", "name": "Private", "query": "cat:cs.HC",
         "secret_ref": ["PRIVATE_FEED_TOKEN"], "enabled": "auto"},
    ]})
    out = tmp_path / "data"
    build_mod.main(["--output-dir", str(out), "--smoke", "--repo-root", str(root)])

    manifest = read(out / "manifest.json")
    assert manifest["crypto"]["kdf"]["iterations"] == crypto.PBKDF2_ITERATIONS
    by_id = {s["id"]: s for s in manifest["sections"]}
    assert by_id["research"]["file"] == "research.enc.json"
    assert by_id["research"]["encrypted"] is True
    assert "count" not in by_id["research"]
    assert not (out / "research.json").exists(), "plaintext private file must never exist"

    env = read(out / "research.enc.json")
    payload = crypto.decrypt_json(env, "correct horse battery staple", "research")
    assert payload["items"] == []

    check = manifest["crypto"]["check"]
    full = {"v": 1, "alg": crypto.ALG, "kdf": manifest["crypto"]["kdf"], **check}
    assert crypto.decrypt_envelope(full, "correct horse battery staple", "check") \
        == crypto.CHECK_PLAINTEXT


PRIVATE_CAP_URL = "https://feeds.example/cap/deadbeef0123"


def _private_rss_repo(make_repo):
    return make_repo(sources={"schema_version": 1, "presets": [], "sources": [
        {"id": "src_x", "category": "private", "type": "rss",
         "section": "private", "name": "X",
         "secret_ref": ["SRC_X_URL"], "enabled": "auto"},
    ]})


def _assert_url_absent_from_output(out):
    """Byte-scan every file under the output dir for the capability URL."""
    needle = PRIVATE_CAP_URL.encode("utf-8")
    scanned = 0
    for path in out.rglob("*"):
        if path.is_file():
            assert needle not in path.read_bytes(), f"URL leaked into {path.name}"
            scanned += 1
    assert scanned > 0


def test_smoke_private_rss_encrypts_and_never_leaks_url(tmp_path, monkeypatch, make_repo):
    monkeypatch.setenv("NEWSDASH_PASSPHRASE", "correct horse battery staple")
    monkeypatch.setenv("SRC_X_URL", PRIVATE_CAP_URL)
    out = tmp_path / "data"
    build_mod.main(["--output-dir", str(out), "--smoke",
                    "--repo-root", str(_private_rss_repo(make_repo))])

    manifest = read(out / "manifest.json")
    by_id = {s["id"]: s for s in manifest["sections"]}
    assert by_id["private"]["file"] == "private.enc.json"
    assert by_id["private"]["encrypted"] is True
    assert (out / "private.enc.json").exists()
    assert not (out / "private.json").exists()
    # The resolved capability URL lives only in build-process memory; --smoke
    # never fetches it and nothing may write it to any output file.
    _assert_url_absent_from_output(out)


def test_smoke_private_rss_zero_secret_skips_green(tmp_path, monkeypatch, make_repo):
    # Same config, but the SRC_X_URL secret is absent: the build must stay green
    # (exit 0) with the source skipped, not fail.
    monkeypatch.delenv("SRC_X_URL", raising=False)
    monkeypatch.delenv("NEWSDASH_PASSPHRASE", raising=False)
    out = tmp_path / "data"
    build_mod.main(["--output-dir", str(out), "--smoke",
                    "--repo-root", str(_private_rss_repo(make_repo))])

    manifest = read(out / "manifest.json")
    by_id = {s["id"]: s for s in manifest["sections"]}
    assert by_id["private"]["status"] == "not_configured"
    # no passphrase needed because no private source is active
    assert not (out / "private.enc.json").exists()
    status = read(out / "source-status.json")
    assert status["private_summary"] == {"total": 1, "configured": 0}


def test_private_visibility_requires_passphrase(tmp_path, monkeypatch, make_repo):
    monkeypatch.delenv("NEWSDASH_PASSPHRASE", raising=False)
    root = make_repo(site={
        "schema_version": 1, "title": "T", "visibility": "private",
        "languages": ["en"], "default_language": "en",
        "theme": "bear", "timezone": "UTC",
    })
    with pytest.raises(SystemExit):
        build_mod.main(["--output-dir", str(tmp_path / "d"), "--smoke",
                        "--repo-root", str(root)])


def test_private_visibility_encrypts_everything(tmp_path, monkeypatch, make_repo):
    monkeypatch.setenv("NEWSDASH_PASSPHRASE", "four random words here")
    root = make_repo(
        site={"schema_version": 1, "title": "T", "visibility": "private",
              "languages": ["en"], "default_language": "en",
              "theme": "bear", "timezone": "UTC"},
        sources={"schema_version": 1, "presets": [], "sources": [
            {"id": "feed_a", "type": "rss", "section": "news",
             "name": "A", "url": "https://a.example/feed.xml"}]},
    )
    out = tmp_path / "d"
    build_mod.main(["--output-dir", str(out), "--smoke", "--repo-root", str(root)])
    manifest = read(out / "manifest.json")
    by_id = {s["id"]: s for s in manifest["sections"]}
    assert by_id["news"]["file"] == "news.enc.json"
    assert manifest["source_status_file"] == "source-status.enc.json"
    assert not (out / "news.json").exists()
    assert (out / "archive.enc.json").exists()


@responses.activate
def test_build_writes_bilingual_insights(tmp_path, monkeypatch, make_repo):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.delenv("SMITHSONIAN_API_KEY", raising=False)
    responses.get(
        "https://a.example/feed.xml",
        body=rss_with_full_text("https://a.example/en-story"),
    )
    responses.get(
        "https://b.example/feed.xml",
        body=rss_with_full_text("https://b.example/zh-story"),
    )
    responses.post(CHAT_URL, json=llm_completion())
    responses.post(CHAT_URL, json=llm_completion(
        brief="中文简报",
        news_summary="中文新闻",
        papers_summary="中文论文",
        image_query="compass clock",
    ))
    responses.post(CHAT_URL, json=apropos_query_completion())
    responses.get("https://api.gdeltproject.org/api/v2/doc/doc",
                  json=gdelt_apropos_response())
    responses.post(CHAT_URL, json=apropos_summary_completion())
    root = make_repo(sources={"schema_version": 1, "presets": [], "sources": [
        {"id": "feed_en", "type": "rss", "section": "news",
         "name": "A", "url": "https://a.example/feed.xml", "lang": "en"},
        {"id": "feed_zh", "type": "rss", "section": "news",
         "name": "B", "url": "https://b.example/feed.xml", "lang": "zh"},
    ]})
    out = tmp_path / "d"
    build_mod.main(["--output-dir", str(out), "--repo-root", str(root)])

    manifest = read(out / "manifest.json")
    assert manifest["insights_file"] == "insights.json"
    insights = read(out / "insights.json")
    assert insights["summaries"]["en"] == {
        "brief": "EN brief", "news_summary": "EN news", "papers_summary": "EN papers",
    }
    assert insights["summaries"]["zh"] == {
        "brief": "中文简报", "news_summary": "中文新闻", "papers_summary": "中文论文",
    }
    assert insights["brief"] == "EN brief"
    assert "image_query" not in insights
    assert insights["apropos_of_nothing"]["source"]["url"] == "https://example.org/pumpkin"
    assert insights["apropos_of_nothing"]["summaries"]["zh"]["summary"].startswith("一场")


@responses.activate
def test_rss_full_text_generates_article_file_and_status(tmp_path, monkeypatch, make_repo):
    monkeypatch.delenv("NEWSDASH_PASSPHRASE", raising=False)
    responses.get("https://a.example/feed.xml", body=rss_with_full_text())
    root = make_repo(sources={"schema_version": 1, "presets": [], "sources": [
        {"id": "feed_a", "type": "rss", "section": "news",
         "name": "A", "url": "https://a.example/feed.xml"},
    ]})
    out = tmp_path / "d"
    build_mod.main(["--output-dir", str(out), "--repo-root", str(root)])

    news = read(out / "news.json")
    item = news["items"][0]
    assert item["full_text_available"] is True
    assert item["full_text_file"].startswith("articles/news/")
    assert item["full_text_file"].endswith(".json")
    article = read(out / item["full_text_file"])
    assert article["item"]["id"] == item["id"]
    assert article["full_text"].startswith("fulltext-0")

    status = read(out / "source-status.json")
    assert status["sources"][0]["full_text_count"] == 1

    archive = read(out / "archive.json")
    archived = archive["items"][0]
    assert "full_text_available" not in archived
    assert "full_text_file" not in archived


@responses.activate
def test_private_visibility_encrypts_article_files(tmp_path, monkeypatch, make_repo):
    passphrase = "four random words here"
    monkeypatch.setenv("NEWSDASH_PASSPHRASE", passphrase)
    responses.get("https://a.example/feed.xml", body=rss_with_full_text())
    root = make_repo(
        site={"schema_version": 1, "title": "T", "visibility": "private",
              "languages": ["en"], "default_language": "en",
              "theme": "bear", "timezone": "UTC"},
        sources={"schema_version": 1, "presets": [], "sources": [
            {"id": "feed_a", "type": "rss", "section": "news",
             "name": "A", "url": "https://a.example/feed.xml"},
        ]},
    )
    out = tmp_path / "d"
    build_mod.main(["--output-dir", str(out), "--repo-root", str(root)])

    news = crypto.decrypt_json(read(out / "news.enc.json"), passphrase, "news")
    item = news["items"][0]
    assert item["full_text_available"] is True
    assert item["full_text_file"].startswith("articles/news/")
    assert item["full_text_file"].endswith(".enc.json")

    article = crypto.decrypt_json(
        read(out / item["full_text_file"]),
        passphrase,
        f"article:news:{item['id']}",
    )
    assert article["item"]["id"] == item["id"]
    assert article["full_text"].startswith("fulltext-0")

    status = crypto.decrypt_json(
        read(out / "source-status.enc.json"), passphrase, "source-status")
    assert status["sources"][0]["full_text_count"] == 1
