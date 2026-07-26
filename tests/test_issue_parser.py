import json
import shutil
from pathlib import Path

import pytest

import apply_issue_setup as ios
from conftest import REPO_ROOT

FIX = Path(__file__).parent / "fixtures" / "issues"


@pytest.fixture
def issue_repo(tmp_path):
    """Throwaway repo with the real config tree (schemas + presets)."""
    root = tmp_path / "repo"
    root.mkdir()
    shutil.copytree(REPO_ROOT / "config", root / "config")
    return root


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_full_form_applies(issue_repo):
    body = (FIX / "setup_full.md").read_text(encoding="utf-8")
    summary, warnings = ios.apply(body, issue_repo, passphrase_set=True)

    site = read_json(issue_repo / "config" / "site.json")
    assert site["default_language"] == "zh"
    assert site["visibility"] == "private"
    assert site["theme"] == "papermod"
    assert site["title"] == "道成的新闻台"
    assert site["timezone"] == "America/Chicago"

    sources = read_json(issue_repo / "config" / "sources.json")
    assert sources["presets"] == ["ai-news", "academic-datavis", "academic-techcomm"]
    ids = [s["id"] for s in sources["sources"]]
    assert "feifei_li_substack" in ids  # non-custom entries preserved
    customs = [s for s in sources["sources"] if s["id"].startswith("custom_rss_")]
    assert len(customs) == 2
    assert {c["url"] for c in customs} == {
        "https://simonwillison.net/atom/everything/",
        "https://lab.example.edu/feed.xml",
    }
    # Chinese comma splits too
    assert sources["interests"]["keywords"] == [
        "data visualization", "technical communication", "LLM"]
    assert summary["visibility"] == "private"
    assert warnings == []


def test_full_form_is_idempotent(issue_repo):
    body = (FIX / "setup_full.md").read_text(encoding="utf-8")
    ios.apply(body, issue_repo, passphrase_set=True)
    ios.apply(body, issue_repo, passphrase_set=True)
    sources = read_json(issue_repo / "config" / "sources.json")
    customs = [s for s in sources["sources"] if s["id"].startswith("custom_rss_")]
    assert len(customs) == 2  # re-applying replaces, never duplicates


def test_minimal_form_keeps_defaults(issue_repo):
    before = read_json(issue_repo / "config" / "site.json")
    body = (FIX / "setup_minimal.md").read_text(encoding="utf-8")
    summary, warnings = ios.apply(body, issue_repo)
    site = read_json(issue_repo / "config" / "site.json")
    assert site["title"] == before["title"]  # _No response_ keeps existing
    assert site["timezone"] == before["timezone"]  # untouched fields survive
    assert site["theme"] == "blowfish"
    sources = read_json(issue_repo / "config" / "sources.json")
    assert sources["presets"] == ["ai-news", "general-news"]  # fallback
    assert any("no packs selected" in w for w in warnings)


def test_theme_alias_in_issue_normalized(issue_repo):
    """A deprecated theme key submitted through the setup issue (nyt) is
    normalized to its new name (papermod) with no warning."""
    body = (FIX / "setup_minimal.md").read_text(encoding="utf-8").replace(
        "blowfish — lowkey violet, blurred nav · 河豚",
        "nyt — newspaper front page · 报纸")
    summary, warnings = ios.apply(body, issue_repo)
    site = read_json(issue_repo / "config" / "site.json")
    assert site["theme"] == "papermod"
    assert not any("theme" in w.lower() for w in warnings)


def test_malformed_body_with_credential_rejected(issue_repo):
    body = (FIX / "setup_malformed.md").read_text(encoding="utf-8")
    before = (issue_repo / "config" / "site.json").read_text()
    with pytest.raises(ValueError, match="credential"):
        ios.apply(body, issue_repo)
    assert (issue_repo / "config" / "site.json").read_text() == before


def test_missing_ack_rejected(issue_repo):
    body = (FIX / "setup_minimal.md").read_text(encoding="utf-8") \
        .replace("- [x] I understand", "- [ ] I understand")
    with pytest.raises(ValueError, match="[Aa]cknowledgement"):
        ios.apply(body, issue_repo)


def test_success_comment_private_mentions_passphrase():
    summary = {"language": "zh", "visibility": "private", "theme": "papermod",
               "title": "T", "timezone": "UTC", "presets": ["ai-news"],
               "extra_feeds": [], "interests": []}
    comment = ios.success_comment(summary, [], "alice/my-dash")
    assert "NEWSDASH_PASSPHRASE" in comment
    assert "https://alice.github.io/my-dash/" in comment
    assert "settings/secrets/actions/new" in comment
    assert "Page Skill" in comment


def test_form_labels_match_template():
    """The issue form and the parser share heading constants — keep in sync."""
    template = (REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "setup.yml") \
        .read_text(encoding="utf-8")
    for label in (ios.FIELD_LANGUAGE, ios.FIELD_VISIBILITY, ios.FIELD_THEME,
                  ios.FIELD_TITLE, ios.FIELD_TIMEZONE, ios.FIELD_UPDATE_FREQ,
                  ios.FIELD_OPEN_PACKS, ios.FIELD_ACADEMIC_PACKS,
                  ios.FIELD_EXTRA_RSS, ios.FIELD_INTERESTS, ios.FIELD_ACK):
        assert f'label: "{label} ·' in template, f"form label drifted: {label}"


# --- passphrase precondition gate ------------------------------------------
#
# Private visibility / private sources make scripts/build.py hard-fail when
# NEWSDASH_PASSPHRASE is absent. The bot must refuse up front and leave config
# untouched — and must NEVER downgrade the request to public.

def test_private_visibility_without_passphrase_refused(issue_repo):
    site_before = (issue_repo / "config" / "site.json").read_text()
    sources_before = (issue_repo / "config" / "sources.json").read_text()
    body = (FIX / "setup_full.md").read_text(encoding="utf-8")

    with pytest.raises(ios.PassphraseRequired) as ei:
        ios.apply(body, issue_repo)  # fail-safe default: passphrase_set=False

    # byte-identical: not a single field applied, and no silent public downgrade
    assert (issue_repo / "config" / "site.json").read_text() == site_before
    assert (issue_repo / "config" / "sources.json").read_text() == sources_before
    assert "NEWSDASH_PASSPHRASE" in str(ei.value)


def test_private_visibility_with_passphrase_applies(issue_repo):
    """Regression guard: the gate must not block the legitimate private path."""
    body = (FIX / "setup_full.md").read_text(encoding="utf-8")
    summary, _ = ios.apply(body, issue_repo, passphrase_set=True)
    assert summary["visibility"] == "private"
    site = read_json(issue_repo / "config" / "site.json")
    assert site["visibility"] == "private"


def test_public_visibility_without_passphrase_applies(issue_repo):
    """The zero-keys fast lane keeps working with no passphrase at all."""
    body = (FIX / "setup_minimal.md").read_text(encoding="utf-8")
    summary, _ = ios.apply(body, issue_repo)
    assert summary["visibility"] == "public"
    assert read_json(issue_repo / "config" / "site.json")["visibility"] == "public"


def test_already_private_site_with_blank_visibility_is_refused(issue_repo):
    """The gate keys off the EFFECTIVE visibility, not just what was submitted.

    A site already configured `private` whose form leaves visibility blank used
    to slip through, earn a success comment, and get its issue closed — while
    every build hard-failed for want of the passphrase.
    """
    site_path = issue_repo / "config" / "site.json"
    site = read_json(site_path)
    site["visibility"] = "private"
    site_path.write_text(json.dumps(site, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    before = site_path.read_text()
    sources_before = (issue_repo / "config" / "sources.json").read_text()

    # Drop the visibility answer, leaving the rest of the form intact.
    body = (FIX / "setup_minimal.md").read_text(encoding="utf-8").replace(
        "Public — open sections readable by anyone · 公开", "_No response_")

    with pytest.raises(ios.PassphraseRequired):
        ios.apply(body, issue_repo, passphrase_set=False)

    assert site_path.read_text() == before
    assert (issue_repo / "config" / "sources.json").read_text() == sources_before


def test_already_private_site_can_always_switch_back_to_public(issue_repo):
    """Choosing Public must never be trapped by the gate — it's the escape hatch."""
    site_path = issue_repo / "config" / "site.json"
    site = read_json(site_path)
    site["visibility"] = "private"
    site_path.write_text(json.dumps(site, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")

    body = (FIX / "setup_minimal.md").read_text(encoding="utf-8")
    summary, _ = ios.apply(body, issue_repo, passphrase_set=False)

    assert summary["visibility"] == "public"
    assert read_json(site_path)["visibility"] == "public"


def test_private_source_without_passphrase_refused(issue_repo):
    before = (issue_repo / "config" / "sources.json").read_text()
    body = (FIX / "source_add_private.md").read_text(encoding="utf-8")

    with pytest.raises(ios.PassphraseRequired) as ei:
        ios.apply_any(body, issue_repo)

    assert (issue_repo / "config" / "sources.json").read_text() == before
    assert "NEWSDASH_PASSPHRASE" in str(ei.value)


def test_passphrase_required_is_a_valueerror():
    """main() catches ValueError broadly; the dedicated handler must be able to
    sit in front of it, so the subclass relationship is part of the contract."""
    assert issubclass(ios.PassphraseRequired, ValueError)


def test_passphrase_required_comment_names_the_secret():
    comment = ios.passphrase_required_comment(
        ios.PASSPHRASE_REQUIRED_VISIBILITY, "alice/my-dash")
    assert "NEWSDASH_PASSPHRASE" in comment
    assert "settings/secrets/actions/new" in comment
    assert "Secrets and variables" in comment
    assert "edit this issue" in comment.lower()


@pytest.mark.parametrize("raw,expected", [
    ("true", True), ("TRUE", True), ("True", True), (" true ", True),
    ("false", False), ("", False), (None, False), ("1", False),
    ("yes", False), ("truthy", False), ("${{ secrets.X != '' }}", False),
])
def test_passphrase_flag_parsing_is_fail_safe(raw, expected):
    assert ios._passphrase_set_from_flag(raw) is expected


# --- update-frequency knob (NEWSDASH_UPDATE_FREQ repo Variable) ------------

def _with_update_freq(value: str) -> str:
    """A minimal valid setup body with an Update frequency selection appended."""
    base = (FIX / "setup_minimal.md").read_text(encoding="utf-8")
    return base + f"\n### {ios.FIELD_UPDATE_FREQ} · 更新频率\n\n{value}\n"


def test_update_freq_valid_option_maps_to_variable(issue_repo):
    body = _with_update_freq("3 times a day · 每天3次")
    summary, warnings = ios.apply(body, issue_repo)
    assert summary["update_freq"] == "3x"
    assert not any("update frequency" in w.lower() for w in warnings)
    # the knob is a repo Variable, never written into config files
    site = read_json(issue_repo / "config" / "site.json")
    assert "update_freq" not in site and "update_frequency" not in site


def test_update_freq_absent_yields_no_output(issue_repo):
    body = (FIX / "setup_minimal.md").read_text(encoding="utf-8")
    summary, warnings = ios.apply(body, issue_repo)
    assert summary["update_freq"] == ""  # falsy -> workflow skips the var step


def test_update_freq_junk_ignored_with_warning(issue_repo):
    body = _with_update_freq("Every 5 minutes turbo · 涡轮")
    summary, warnings = ios.apply(body, issue_repo)
    assert summary["update_freq"] == ""  # not on the whitelist -> ignored
    assert any("update frequency" in w.lower() for w in warnings)


# --- add-source flow ------------------------------------------------------

def custom_by_id(sources, sid):
    return next((s for s in sources["sources"] if s.get("id") == sid), None)


def test_source_form_labels_match_template():
    """add-source.yml labels are the parser contract — keep them in sync."""
    template = (REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "add-source.yml") \
        .read_text(encoding="utf-8")
    for label in (ios.FIELD_ACTION, ios.FIELD_SOURCE_ID, ios.FIELD_CATEGORY,
                  ios.FIELD_TYPE, ios.FIELD_SECTION, ios.FIELD_NAME,
                  ios.FIELD_URL_QUERY, ios.FIELD_ISSN, ios.FIELD_SECRET_NAME,
                  ios.FIELD_ACK):
        assert f'label: "{label} ·' in template, f"source label drifted: {label}"


def test_add_open_rss_writes_entry(issue_repo):
    body = (FIX / "source_add_open_rss.md").read_text(encoding="utf-8")
    summary, warnings = ios.apply_any(body, issue_repo)
    sources = read_json(issue_repo / "config" / "sources.json")
    # id auto-derived from Name "Simon Willison"
    assert summary["id"] == "simon_willison"
    entry = custom_by_id(sources, "simon_willison")
    assert entry is not None
    assert entry["url"] == "https://simonwillison.net/atom/everything/"
    assert entry["category"] == "open"
    assert entry["section"] == "news"
    assert entry["type"] == "rss"
    assert summary["kind"] == "source"


def test_add_private_defaults(issue_repo):
    body = (FIX / "source_add_private.md").read_text(encoding="utf-8")
    summary, warnings = ios.apply_any(body, issue_repo, passphrase_set=True)
    sources = read_json(issue_repo / "config" / "sources.json")
    entry = custom_by_id(sources, "my_secret")
    assert entry is not None
    assert entry["category"] == "private"
    assert entry["enabled"] == "auto"
    assert entry["secret_ref"] == ["SRC_MY_SECRET_URL"]
    assert entry["section"] == "private"
    assert "url" not in entry and "query" not in entry and "path" not in entry
    assert summary["private"] is True


def test_add_private_with_url_rejected_and_unchanged(issue_repo):
    before = (issue_repo / "config" / "sources.json").read_text()
    body = (FIX / "source_add_private_leak.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="LEAKED"):
        ios.apply_any(body, issue_repo)
    after = (issue_repo / "config" / "sources.json").read_text()
    assert after == before  # config untouched
    # the rejected URL value is never echoed back
    try:
        ios.apply_any(body, issue_repo)
    except ValueError as exc:
        assert "private.example.com" not in str(exc)


def test_update_changes_section(issue_repo):
    body = (FIX / "source_update_section.md").read_text(encoding="utf-8")
    ios.apply_any(body, issue_repo)
    sources = read_json(issue_repo / "config" / "sources.json")
    entry = custom_by_id(sources, "feifei_li_substack")
    assert entry["section"] == "following"
    # untouched fields survive the patch
    assert entry["url"] == "https://drfeifei.substack.com/feed"
    assert entry["type"] == "rss"


def test_remove_custom_deletes_entry(issue_repo):
    body = (FIX / "source_remove_custom.md").read_text(encoding="utf-8")
    ios.apply_any(body, issue_repo)
    sources = read_json(issue_repo / "config" / "sources.json")
    assert custom_by_id(sources, "karpathy_blog") is None


def test_remove_preset_writes_override(issue_repo):
    body = (FIX / "source_remove_preset.md").read_text(encoding="utf-8")
    ios.apply_any(body, issue_repo)
    sources = read_json(issue_repo / "config" / "sources.json")
    override = custom_by_id(sources, "openai_blog")
    assert override is not None
    assert override["enabled"] is False


def test_source_missing_ack_rejected(issue_repo):
    body = (FIX / "source_missing_ack.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="[Aa]cknowledgement"):
        ios.apply_any(body, issue_repo)


def test_secret_name_invalid_rejected(issue_repo):
    before = (issue_repo / "config" / "sources.json").read_text()
    body = (FIX / "source_secret_name_invalid.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="SRC_"):
        ios.apply_any(body, issue_repo, passphrase_set=True)
    assert (issue_repo / "config" / "sources.json").read_text() == before


def test_body_with_token_param_rejected(issue_repo):
    before = (issue_repo / "config" / "sources.json").read_text()
    body = (FIX / "source_body_token.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="credential"):
        ios.apply_any(body, issue_repo)
    assert (issue_repo / "config" / "sources.json").read_text() == before


def test_success_comment_source_private_lists_secret_steps():
    summary = {"kind": "source", "action": "add", "id": "my_secret",
               "private": True, "change": "private source",
               "secret_ref": ["SRC_MY_SECRET_URL"], "entry": {}}
    comment = ios.success_comment_source(summary, [], "alice/my-dash")
    assert "SRC_MY_SECRET_URL" in comment
    assert "settings/secrets/actions/new" in comment
    assert "NEWSDASH_PASSPHRASE" in comment


def test_success_comment_source_public_echoes_entry():
    entry = {"id": "my_feed", "category": "open", "type": "rss",
             "section": "news", "url": "https://example.com/feed.xml"}
    summary = {"kind": "source", "action": "add", "id": "my_feed",
               "private": False, "change": "added source",
               "secret_ref": [], "entry": entry}
    comment = ios.success_comment_source(summary, [], "alice/my-dash")
    assert "https://example.com/feed.xml" in comment


# --- category-transition guard for EXISTING private sources ----------------

LEAK_SENTINEL = "leaked-cap.example.net"  # host in the update-*-url fixtures


def _seed_private_source(issue_repo):
    """Create the existing private source `my_secret` (custom, secret_ref only),
    the way the verifier seeded config, before running an Update against it."""
    body = (FIX / "source_add_private.md").read_text(encoding="utf-8")
    ios.apply_any(body, issue_repo, passphrase_set=True)
    entry = custom_by_id(read_json(issue_repo / "config" / "sources.json"),
                         "my_secret")
    assert entry is not None and entry["category"] == "private"
    assert "url" not in entry


def test_update_private_with_open_category_and_url_rejected(issue_repo):
    """CASE 1: Update an existing private id with Category=open + a capability
    URL. Must be rejected keying off the EXISTING category, config untouched,
    and the URL value never echoed (no silent private->open flip + persist)."""
    _seed_private_source(issue_repo)
    before = (issue_repo / "config" / "sources.json").read_text()
    body = (FIX / "source_update_private_open_url.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="LEAKED") as ei:
        ios.apply_any(body, issue_repo)
    assert (issue_repo / "config" / "sources.json").read_text() == before
    assert LEAK_SENTINEL not in str(ei.value)


def test_update_private_with_blank_category_and_url_hits_leak_guard(issue_repo):
    """CASE 2: Update an existing private id with Category BLANK + a capability
    URL. Must hit the leak guard (1a) BEFORE the schema-validation gate, so the
    jsonschema message (which embeds the value) can never surface."""
    _seed_private_source(issue_repo)
    before = (issue_repo / "config" / "sources.json").read_text()
    body = (FIX / "source_update_private_blank_url.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="LEAKED") as ei:
        ios.apply_any(body, issue_repo)
    assert (issue_repo / "config" / "sources.json").read_text() == before
    msg = str(ei.value)
    assert LEAK_SENTINEL not in msg
    # proves the leak guard fired, not the validation gate
    assert "did not pass validation" not in msg


def test_update_private_category_change_off_private_rejected(issue_repo):
    """1b: Update an existing private id with Category=open and NO url. Must be
    rejected with the category-lock message (no de-privatization via issues)."""
    _seed_private_source(issue_repo)
    before = (issue_repo / "config" / "sources.json").read_text()
    body = (FIX / "source_update_private_to_open.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="category cannot be changed") as ei:
        ios.apply_any(body, issue_repo)
    assert (issue_repo / "config" / "sources.json").read_text() == before
    # still no value echoed
    assert LEAK_SENTINEL not in str(ei.value)


def test_source_validation_failure_message_is_sanitized(issue_repo):
    """A submission that passes the guards but fails schema validation (invalid
    type) must raise the STATIC message — no submitted field value in it, and
    config restored."""
    before = (issue_repo / "config" / "sources.json").read_text()
    body = (FIX / "source_add_invalid_type.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError) as ei:
        ios.apply_any(body, issue_repo)
    assert (issue_repo / "config" / "sources.json").read_text() == before
    msg = str(ei.value)
    assert "notatype_zzz" not in msg  # the offending submitted value
    assert "weird_src" not in msg     # the submitted source id
    assert "did not pass validation" in msg  # the static sanitized message
