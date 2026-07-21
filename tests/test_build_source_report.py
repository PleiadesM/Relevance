"""Offline tests for the Source Report renderer (scripts/build_source_report.py).

The report page must be safe (no URLs — sources are keyed by id/name), escape
source-controlled text, and surface status via chip + label (not color alone).
"""

import json

import build_source_report as rep


def _report():
    return {
        "schema": "newsdash-source-report/v1",
        "summary": {"total": 3, "ok": 1, "empty": 1, "unhealthy": 0, "private": 1,
                    "api": 0, "capability": 0, "with_duplicates": 0},
        "sources": [
            {"id": "good", "name": "Good <b>hi</b>", "kind": "news", "section": "news",
             "category": "open", "type": "rss", "planned_weight": 0.5, "status": "ok",
             "probed": True, "recommendation": "healthy — keep (consider weight 0.8)",
             "duplicates": [],
             "health": {"count": 10, "cadence_per_week": 2.5, "newest": "2026-07-06",
                        "oldest": "2026-06-01", "recommended_weight": 0.8}},
            {"id": "empty", "name": "Empty", "kind": "news", "section": "news",
             "category": "open", "type": "rss", "planned_weight": 0.8, "status": "empty",
             "probed": True, "health": None, "duplicates": [],
             "recommendation": "parses but no fresh entries"},
            {"id": "priv", "name": "Secret feed", "kind": "private", "section": "private",
             "category": "private", "type": "rss", "planned_weight": None,
             "status": "private", "probed": False, "health": None, "duplicates": [],
             "recommendation": "private — add its secret"},
        ],
    }


def test_render_has_chips_bars_and_table():
    html = rep.render_report(_report(), "en")
    assert "Relevance — Source Report" in html
    # status shown via chip class + label (never color-alone)
    assert "chip-good" in html and "Healthy" in html
    assert "chip-warning" in html and "No fresh items" in html
    assert "chip-muted" in html and "Private" in html
    # a freshness bar with a computed width
    assert "width:100%" in html            # the healthiest feed anchors the scale
    # weight nudge rendered (0.5 -> 0.8)
    assert "0.5" in html and "<strong>0.8</strong>" in html


def test_render_escapes_source_names():
    html = rep.render_report(_report(), "en")
    assert "Good &lt;b&gt;hi&lt;/b&gt;" in html
    assert "<b>hi</b>" not in html          # raw markup never injected


def test_render_contains_no_urls():
    html = rep.render_report(_report(), "en")
    assert "http://" not in html and "https://" not in html


def test_render_chinese_brand():
    html = rep.render_report(_report(), "zh")
    assert "及君 — 信源报告" in html
    assert "健康" in html


def test_main_writes_html(tmp_path, monkeypatch, capsys):
    report_path = tmp_path / "source-report.json"
    out_path = tmp_path / "source-report.html"
    report_path.write_text(json.dumps(_report()), encoding="utf-8")
    monkeypatch.setattr(rep, "_site_lang", lambda: "en")
    monkeypatch.setattr("sys.argv", ["build_source_report.py",
                                     "--report", str(report_path), "--out", str(out_path)])
    rep.main()
    assert out_path.exists()
    assert out_path.read_text().lstrip().startswith("<!doctype html>")
    assert "3 sources" in capsys.readouterr().out
