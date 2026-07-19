"""Private-source capability-URL resolution and redaction (offline).

Convention under test: a private feed source carries no url in config; its
capability URL lives in ONE GitHub Secret named SRC_<ID>_URL and is referenced
via secret_ref: ["SRC_<ID>_URL"]. The URL is read into src.url in process
memory at load time and must never appear in any message, status, or output.
"""

import json

from newsdash.config import load_config, overlay_source_secrets
from newsdash.status import StatusAccumulator

CAP_URL = "https://example.com/cap/abc123"

PRIVATE_RSS = {
    "id": "src_x", "category": "private", "type": "rss", "section": "private",
    "name": "X", "secret_ref": ["SRC_X_URL"], "enabled": "auto",
}


def _private_repo(make_repo):
    return make_repo(sources={
        "schema_version": 1, "presets": [], "sources": [PRIVATE_RSS]})


def test_private_rss_waits_without_secret(make_repo):
    cfg = load_config(_private_repo(make_repo), env={})
    src = next(s for s in cfg.sources if s.id == "src_x")
    assert not src.active
    assert src.skip_reason == "not_configured"
    assert src.url is None


def test_private_rss_resolves_url_from_secret(make_repo):
    cfg = load_config(_private_repo(make_repo), env={"SRC_X_URL": CAP_URL})
    src = next(s for s in cfg.sources if s.id == "src_x")
    assert src.active
    assert src.skip_reason is None
    assert src.url == CAP_URL


def test_private_rss_rejects_non_url_value_without_leaking(make_repo):
    bad = "not a url"
    try:
        cfg = load_config(_private_repo(make_repo), env={"SRC_X_URL": bad})
    except Exception as exc:  # pragma: no cover — must not raise, but if it does,
        assert bad not in str(exc)  # the value must not surface in the message
        raise
    src = next(s for s in cfg.sources if s.id == "src_x")
    assert not src.active
    assert src.skip_reason == "not_configured"
    assert src.url is None  # invalid value never stored


def test_source_secrets_blob_overlay(make_repo):
    blob = json.dumps({"SRC_X_URL": CAP_URL, "OTHER_KEY": "nope"})
    cfg = load_config(_private_repo(make_repo),
                      env={"NEWSDASH_SOURCE_SECRETS": blob})
    src = next(s for s in cfg.sources if s.id == "src_x")
    assert src.active and src.url == CAP_URL


def test_overlay_only_lifts_src_keys_and_env_wins():
    real = "https://env.example/real"
    blob = json.dumps({"SRC_X_URL": "https://blob.example/blob", "OTHER_KEY": "x"})
    merged = overlay_source_secrets(
        {"SRC_X_URL": real, "NEWSDASH_SOURCE_SECRETS": blob})
    # a pre-existing env var always beats the blob value
    assert merged["SRC_X_URL"] == real
    # non-SRC_ keys from the blob are never lifted in
    assert "OTHER_KEY" not in merged
    # the blob key itself is dropped from the returned copy
    assert "NEWSDASH_SOURCE_SECRETS" not in merged


def test_overlay_tolerates_bad_json():
    merged = overlay_source_secrets({"NEWSDASH_SOURCE_SECRETS": "{not json"})
    assert "NEWSDASH_SOURCE_SECRETS" not in merged
    assert merged == {}


def test_failing_private_source_redacted_in_public_status(make_source):
    """A private fetch error is aggregate-only in the public status dict: no
    per-source entry, and the capability URL never appears anywhere in it."""
    src = make_source(id="src_x", category="private", type="rss",
                      section="private", secret_ref=["SRC_X_URL"], url=CAP_URL)
    acc = StatusAccumulator()
    # simulate a fetcher raising an error whose message embeds the URL
    acc.record(src, ok=False, error=RuntimeError(f"connect failed: {CAP_URL}"))
    public = acc.public_dict("2026-07-18T00:00:00Z")

    assert public["sources"] == []  # no per-source private entry
    assert public["private_summary"] == {"total": 1, "configured": 1}
    blob = json.dumps(public)
    assert CAP_URL not in blob
    assert "src_x" not in blob  # not even the id surfaces publicly
