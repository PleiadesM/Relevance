#!/usr/bin/env python3
"""Render the **Source Report** HTML from a `source-report.json`.

Step 2 of the guided setup: after `discover_source.py report --plan …` writes
`newsdash-studio/source-report.json`, this renders a self-contained, gitignored
page — a freshness bar chart colored by health status (status palette: icon +
label + legend, never color alone) and a full per-source table with
recommendations.

Safe by construction: the report JSON carries no URLs (sources are keyed by
id/name), so neither does this page.

Usage:
    python scripts/build_source_report.py [--report PATH] [--out PATH]
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"
STUDIO_DIR = REPO_ROOT / "newsdash-studio"

# status -> (palette role, icon). Roles map to the validated status palette
# (good/warning/serious/critical) plus a neutral "muted" for not-probed states.
STATUS = {
    "ok":         ("good", "✓"),
    "empty":      ("warning", "!"),
    "unhealthy":  ("critical", "✕"),
    "capability": ("critical", "⚠"),
    "private":    ("muted", "🔒"),
    "api":        ("muted", "◦"),
    "unfetched":  ("muted", "–"),
}

STR = {
    "en": {
        "title": "Relevance — Source Report", "brand": "Relevance",
        "lead": "Health check of your planned sources. Fix anything flagged, then apply the plan.",
        "freshness": "Freshness (items per week)",
        "status": {"ok": "Healthy", "empty": "No fresh items", "unhealthy": "Unhealthy",
                   "capability": "Capability URL — make private", "private": "Private (not probed)",
                   "api": "API source (not probed)", "unfetched": "No URL"},
        "th": ["Source", "Kind", "Section", "Status", "Items", "Per week",
               "Weight", "Recommendation"],
        "tiles": {"total": "sources", "ok": "healthy", "attention": "need attention",
                  "notprobed": "not probed"},
        "weightArrow": "→", "none": "—",
    },
    "zh": {
        "title": "及君 — 信源报告", "brand": "及君",
        "lead": "对计划中的信源做健康检查。先处理被标记的问题，再应用方案。",
        "freshness": "更新频率（每周条目数）",
        "status": {"ok": "健康", "empty": "无新条目", "unhealthy": "无法解析",
                   "capability": "凭证 URL——请设为私密", "private": "私密（未探测）",
                   "api": "API 信源（未探测）", "unfetched": "无 URL"},
        "th": ["信源", "类型", "栏目", "状态", "条目", "每周", "权重", "建议"],
        "tiles": {"total": "信源", "ok": "健康", "attention": "需处理", "notprobed": "未探测"},
        "weightArrow": "→", "none": "—",
    },
}


def _site_lang() -> str:
    site = CONFIG_DIR / "site.json"
    if site.exists():
        try:
            return json.loads(site.read_text(encoding="utf-8")).get("default_language", "en")
        except (OSError, json.JSONDecodeError):
            pass
    return "en"


def _esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def _weight_cell(row: dict, t: dict) -> str:
    planned = row.get("planned_weight")
    rec = (row.get("health") or {}).get("recommended_weight")
    if planned is None and rec is None:
        return t["none"]
    if rec is not None and planned is not None and abs(float(planned) - float(rec)) >= 0.2:
        return f"{planned} {t['weightArrow']} <strong>{rec}</strong>"
    return _esc(planned if planned is not None else rec)


def render_report(report: dict, lang: str = "en") -> str:
    t = STR["zh" if lang == "zh" else "en"]
    rows = report.get("sources", [])
    summary = report.get("summary", {})

    cadences = [(r.get("health") or {}).get("cadence_per_week") or 0 for r in rows]
    max_cad = max(cadences + [0]) or 1

    # summary tiles
    attention = summary.get("unhealthy", 0) + summary.get("empty", 0) + summary.get("capability", 0)
    not_probed = summary.get("private", 0) + summary.get("api", 0)
    tiles = "".join(
        f'<div class="tile"><span class="tile-num">{n}</span>'
        f'<span class="tile-label">{_esc(lbl)}</span></div>'
        for n, lbl in [
            (summary.get("total", 0), t["tiles"]["total"]),
            (summary.get("ok", 0), t["tiles"]["ok"]),
            (attention, t["tiles"]["attention"]),
            (not_probed, t["tiles"]["notprobed"]),
        ])

    # bars (one row per source; status chip + name + freshness bar + value)
    bar_rows = []
    for r in rows:
        role, icon = STATUS.get(r.get("status"), ("muted", "?"))
        health = r.get("health") or {}
        cad = health.get("cadence_per_week")
        pct = round((cad or 0) / max_cad * 100)
        if health:
            val = f"{cad if cad is not None else '?'}/wk · {health.get('count', 0)}"
        else:
            val = t["none"]
        chip = (f'<span class="chip chip-{role}">{icon} '
                f'{_esc(t["status"].get(r.get("status"), r.get("status")))}</span>')
        bar_rows.append(
            f'<div class="bar-row" title="{_esc(r.get("recommendation"))}">'
            f'{chip}'
            f'<span class="bar-name">{_esc(r.get("name"))}</span>'
            f'<span class="bar-track"><span class="bar-fill" '
            f'style="width:{pct}%;background:var(--{role})"></span></span>'
            f'<span class="bar-val">{_esc(val)}</span></div>')

    # legend (present statuses only)
    seen_roles = []
    legend = []
    for st in STATUS:
        if any(r.get("status") == st for r in rows):
            role, icon = STATUS[st]
            legend.append(f'<span class="lg"><span class="sw" style="background:var(--{role})">'
                          f'</span>{icon} {_esc(t["status"][st])}</span>')

    # table
    trs = []
    for r in rows:
        role, icon = STATUS.get(r.get("status"), ("muted", "?"))
        health = r.get("health") or {}
        cad = health.get("cadence_per_week")
        trs.append(
            "<tr>"
            f"<td>{_esc(r.get('name'))}</td>"
            f"<td>{_esc(r.get('kind'))}</td>"
            f"<td>{_esc(r.get('section'))}</td>"
            f'<td><span class="chip chip-{role}">{icon} '
            f'{_esc(t["status"].get(r.get("status"), r.get("status")))}</span></td>'
            f"<td class='num'>{_esc(health.get('count', t['none']))}</td>"
            f"<td class='num'>{_esc(cad if cad is not None else t['none'])}</td>"
            f"<td class='num'>{_weight_cell(r, t)}</td>"
            f"<td class='rec'>{_esc(r.get('recommendation'))}</td>"
            "</tr>")

    return (TEMPLATE
            .replace("%%LANG%%", "zh" if lang == "zh" else "en")
            .replace("%%TITLE%%", _esc(t["title"]))
            .replace("%%LEAD%%", _esc(t["lead"]))
            .replace("%%FRESHNESS%%", _esc(t["freshness"]))
            .replace("%%TILES%%", tiles)
            .replace("%%BARS%%", "".join(bar_rows))
            .replace("%%LEGEND%%", "".join(legend))
            .replace("%%THEAD%%", "".join(f"<th>{_esc(h)}</th>" for h in t["th"]))
            .replace("%%ROWS%%", "".join(trs)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the Source Report HTML.")
    parser.add_argument("--report", default=str(STUDIO_DIR / "source-report.json"),
                        help="report JSON from discover_source.py report")
    parser.add_argument("--out", default=str(STUDIO_DIR / "source-report.html"),
                        help="output HTML (gitignored)")
    args = parser.parse_args()

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(report, _site_lang()), encoding="utf-8")
    n = len(report.get("sources", []))
    print(f"Wrote {out} ({n} source{'s' if n != 1 else ''}). Open it in a browser.")


TEMPLATE = r'''<!doctype html>
<html lang="%%LANG%%">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%%TITLE%%</title>
<style>
  :root { color-scheme: light dark;
    --surface:#fcfcfb; --page:#f9f9f7; --ink:#0b0b0b; --ink2:#52514e;
    --border:rgba(11,11,11,.12); --track:rgba(11,11,11,.06);
    --good:#0ca30c; --warning:#fab219; --serious:#ec835a; --critical:#d03b3b; --muted:#8a877e; }
  @media (prefers-color-scheme: dark) {
    :root { --surface:#1a1a19; --page:#0d0d0d; --ink:#fff; --ink2:#c3c2b7;
      --border:rgba(255,255,255,.14); --track:rgba(255,255,255,.08); --muted:#9a958c; }
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--page); color:var(--ink);
    font:15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", sans-serif; }
  .wrap { max-width: 62rem; margin:0 auto; padding:1.5rem 1.25rem 4rem; }
  h1 { font-family:Georgia,"Noto Serif SC",serif; font-size:1.7rem; margin:0 0 .2rem; }
  h2 { font-family:Georgia,serif; font-size:1.05rem; margin:1.6rem 0 .7rem; }
  p.lead { color:var(--ink2); margin:0 0 1.2rem; }
  .tiles { display:flex; flex-wrap:wrap; gap:.7rem; margin-bottom:.5rem; }
  .tile { background:var(--surface); border:1px solid var(--border); border-radius:10px;
    padding:.6rem 1rem; min-width:6rem; }
  .tile-num { display:block; font-size:1.6rem; font-weight:700; font-family:Georgia,serif; }
  .tile-label { font-size:.8rem; color:var(--ink2); }
  .card { background:var(--surface); border:1px solid var(--border); border-radius:12px;
    padding:1rem 1.1rem; margin-top:.6rem; }
  .bar-row { display:grid; grid-template-columns:11rem 1fr 8rem 6rem; gap:.7rem;
    align-items:center; padding:.28rem 0; }
  .bar-name { color:var(--ink); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .bar-track { background:var(--track); border-radius:5px; height:.7rem; overflow:hidden; }
  .bar-fill { display:block; height:100%; border-radius:5px; min-width:2px; }
  .bar-val { font-size:.82rem; color:var(--ink2); text-align:right; font-variant-numeric:tabular-nums; }
  .chip { font-size:.76rem; padding:.08rem .5rem; border-radius:999px; white-space:nowrap;
    border:1px solid var(--border); color:var(--ink); }
  .chip-good { background:color-mix(in srgb, var(--good) 16%, transparent); }
  .chip-warning { background:color-mix(in srgb, var(--warning) 20%, transparent); }
  .chip-serious { background:color-mix(in srgb, var(--serious) 18%, transparent); }
  .chip-critical { background:color-mix(in srgb, var(--critical) 16%, transparent); }
  .chip-muted { background:color-mix(in srgb, var(--muted) 16%, transparent); }
  .legend { display:flex; flex-wrap:wrap; gap:.5rem 1rem; margin-top:.8rem; font-size:.8rem; color:var(--ink2); }
  .lg { display:inline-flex; align-items:center; gap:.35rem; }
  .sw { width:.7rem; height:.7rem; border-radius:3px; display:inline-block; }
  table { width:100%; border-collapse:collapse; margin-top:.6rem; font-size:.88rem; }
  th, td { text-align:left; padding:.45rem .55rem; border-bottom:1px solid var(--border); vertical-align:top; }
  th { color:var(--ink2); font-weight:600; font-size:.8rem; }
  td.num { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
  td.rec { color:var(--ink2); }
  .scroll { overflow-x:auto; }
</style>
</head>
<body>
<div class="wrap">
  <h1>%%TITLE%%</h1>
  <p class="lead">%%LEAD%%</p>
  <div class="tiles">%%TILES%%</div>

  <div class="card">
    <h2>%%FRESHNESS%%</h2>
    %%BARS%%
    <div class="legend">%%LEGEND%%</div>
  </div>

  <div class="scroll">
    <table>
      <thead><tr>%%THEAD%%</tr></thead>
      <tbody>%%ROWS%%</tbody>
    </table>
  </div>
</div>
</body>
</html>
'''


if __name__ == "__main__":
    main()
