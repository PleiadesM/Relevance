"""Offline tests for the Source Studio generator (scripts/build_source_studio.py).

The Studio must be safe to hand a deployer: it reads only the (secret-free)
config, and a private source must never surface a capability URL — in the
embedded data or the generated HTML.
"""

import json
from pathlib import Path

import pytest

import build_source_studio as studio


def _write_config(config_dir: Path, sources, *, presets=None, with_site=True,
                  with_presets_dir=True):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "sources.json").write_text(json.dumps({
        "$schema": "./schema/sources.schema.json",
        "schema_version": 1,
        "presets": presets or [],
        "interests": {"keywords": ["ai"], "boost": 0.2},
        "sources": sources,
        "tag_rules": [],
    }), encoding="utf-8")
    if with_site:
        (config_dir / "site.json").write_text(json.dumps({
            "title": "Relevance", "default_language": "zh",
        }), encoding="utf-8")
    if with_presets_dir:
        pdir = config_dir / "presets"
        pdir.mkdir(exist_ok=True)
        (pdir / "ai-news.json").write_text(json.dumps({
            "id": "ai-news", "name": {"en": "AI news", "zh": "AI 资讯"},
            "category": "open", "section": "news",
            "sources": [{"id": "a"}, {"id": "b"}],
        }), encoding="utf-8")


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    monkeypatch.setattr(studio, "CONFIG_DIR", config_dir)
    return config_dir


# --------------------------------------------------------------------------- #
# build_data

def test_build_data_shape_and_passthrough(tmp_config):
    _write_config(tmp_config, [
        {"id": "feifei", "category": "open", "type": "rss", "section": "news",
         "name": "Fei-Fei", "url": "https://example.com/feed", "weight": 1.0},
    ], presets=["ai-news"])
    data = studio.build_data()

    assert data["site"] == {"title": "Relevance", "lang": "zh"}
    assert data["sources"][0]["url"] == "https://example.com/feed"
    assert data["presets"]["active"] == ["ai-news"]
    assert [p["id"] for p in data["presets"]["available"]] == ["ai-news"]
    assert data["presets"]["available"][0]["count"] == 2
    # defaults always present and first, custom sections appended
    assert data["sections"][:4] == ["news", "papers", "following", "private"]


def test_custom_section_appended(tmp_config):
    _write_config(tmp_config, [
        {"id": "x", "category": "open", "type": "rss", "section": "design",
         "name": "X", "url": "https://e.com/f"},
    ])
    data = studio.build_data()
    assert "design" in data["sections"]
    assert data["sections"].index("design") >= 4  # after the defaults


def test_missing_site_and_presets_dir_are_tolerated(tmp_config):
    _write_config(tmp_config, [
        {"id": "x", "category": "open", "type": "rss", "section": "news",
         "name": "X", "url": "https://e.com/f"},
    ], with_site=False, with_presets_dir=False)
    data = studio.build_data()
    assert data["site"]["title"] == "Relevance"   # fallback default
    assert data["site"]["lang"] == "en"
    assert data["presets"]["available"] == []


# --------------------------------------------------------------------------- #
# security: private sources never carry a URL

def test_private_source_has_no_url_in_data_or_html(tmp_config):
    _write_config(tmp_config, [
        {"id": "my_priv", "category": "private", "type": "rss",
         "section": "private", "name": "My private feed",
         "enabled": "auto", "secret_ref": ["SRC_MY_PRIV_URL"]},
    ])
    data = studio.build_data()
    priv = data["sources"][0]
    assert "url" not in priv and "path" not in priv
    assert priv["secret_ref"] == ["SRC_MY_PRIV_URL"]

    html = studio.render_html(data)
    # The embedded data block round-trips, and the private entry stays url-free.
    block = html.split('id="studio-data"', 1)[1].split(">", 1)[1].split("</script>", 1)[0]
    embedded = json.loads(block.replace("\\u003c", "<"))
    assert not any("url" in s or "path" in s for s in embedded["sources"]
                   if s["category"] == "private")


def test_generator_strips_url_from_malformed_private_source(tmp_config):
    # Defense-in-depth: even if a (schema-invalid) config smuggles a url onto a
    # private source, the generator must not surface that capability URL.
    _write_config(tmp_config, [
        {"id": "bad_priv", "category": "private", "type": "rss",
         "section": "private", "name": "Bad", "secret_ref": ["SRC_BAD_URL"],
         "url": "https://cap.example/secret-token-abc123"},
    ])
    data = studio.build_data()
    assert "url" not in data["sources"][0]
    assert "cap.example" not in studio.render_html(data)


# --------------------------------------------------------------------------- #
# render_html

def test_render_html_escapes_angle_brackets(tmp_config):
    # A name with markup must not break out of the <script> data island.
    _write_config(tmp_config, [
        {"id": "x", "category": "open", "type": "rss", "section": "news",
         "name": "</script><b>hi</b>", "url": "https://e.com/f"},
    ])
    html = studio.render_html(studio.build_data())
    # No raw closing tag from the payload — every "<" is escaped inside the data.
    head = html.split('type="application/json">', 1)[1].split("</script>", 1)[0]
    assert "</script>" not in head
    assert "\\u003c" in head


def test_main_writes_studio_html(tmp_config, tmp_path, monkeypatch, capsys):
    _write_config(tmp_config, [
        {"id": "x", "category": "open", "type": "rss", "section": "news",
         "name": "X", "url": "https://e.com/f"},
    ])
    out = tmp_path / "studio-out"
    monkeypatch.setattr("sys.argv", ["build_source_studio.py", "--output-dir", str(out)])
    studio.main()
    written = out / "source-studio.html"
    assert written.exists()
    assert written.read_text().lstrip().startswith("<!doctype html>")
    assert "sources.plan.json" in capsys.readouterr().out
