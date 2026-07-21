#!/usr/bin/env python3
"""Generate the local **Source Studio** — a self-contained HTML editor for a
deployer's news/paper sources.

The Studio reads the current `config/sources.json` and renders an offline,
gitignored page where the user can add/remove/edit sources, set each one
public or private, pick a friendly source *kind*, and tune weights. Saving
produces a `sources.plan.json` that the coding agent reads back and applies
to the real config (see `skills/newsdash/references/source-studio.md`).

Security: this script reads ONLY the config files, which are secret-free by
design — private sources carry a `secret_ref` name, never a capability URL.
The generated page and the plan it emits therefore contain no secrets, and
the Studio never offers a URL field for a private source. Both the HTML and
the plan live under a gitignored working dir and must never be committed.

Usage:
    python scripts/build_source_studio.py [--output-dir newsdash-studio]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"
DEFAULT_OUTPUT = REPO_ROOT / "newsdash-studio"

# Sections the frontend renders first (others follow, alphabetically).
DEFAULT_SECTIONS = ["news", "papers", "following", "private"]


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _collect_presets() -> list[dict]:
    """Scan config/presets/*.json for the available source packs. Only
    metadata (id/name/category/section/count) is surfaced — never the pack's
    individual source URLs, which the Studio does not need."""
    packs: list[dict] = []
    presets_dir = CONFIG_DIR / "presets"
    if not presets_dir.is_dir():
        return packs
    for path in sorted(presets_dir.glob("*.json")):
        try:
            data = _load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        packs.append({
            "id": data.get("id", path.stem),
            "name": data.get("name") or {"en": path.stem, "zh": path.stem},
            "category": data.get("category", "open"),
            "section": data.get("section", "news"),
            "count": len(data.get("sources", [])),
        })
    return packs


def build_data() -> dict:
    """Assemble the (secret-free) data the Studio page needs."""
    sources_cfg = _load_json(CONFIG_DIR / "sources.json")
    site_cfg = {}
    site_path = CONFIG_DIR / "site.json"
    if site_path.exists():
        site_cfg = _load_json(site_path)

    raw_sources = sources_cfg.get("sources", [])
    # Defense-in-depth: a private source must never carry a capability URL.
    # The schema already forbids url/path on private sources, but strip them
    # here too so even a malformed config can't surface a credential in the
    # generated page.
    for s in raw_sources:
        if s.get("category") == "private":
            s.pop("url", None)
            s.pop("path", None)
    # Sections known to the config, in a stable order (defaults first).
    seen = [s.get("section", "news") for s in raw_sources]
    sections = list(DEFAULT_SECTIONS)
    for sec in seen:
        if sec and sec not in sections:
            sections.append(sec)

    return {
        "site": {
            "title": site_cfg.get("title", "Relevance"),
            "lang": site_cfg.get("default_language", "en"),
        },
        "sources": raw_sources,
        "presets": {
            "available": _collect_presets(),
            "active": sources_cfg.get("presets", []),
        },
        "interests": sources_cfg.get("interests", {"keywords": [], "boost": 0.15}),
        "sections": sections,
    }


def render_html(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    # Escape "<" so the JSON can never terminate the <script> element early.
    payload = payload.replace("<", "\\u003c")
    return TEMPLATE.replace("/*__STUDIO_DATA__*/", payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the local Source Studio.")
    parser.add_argument(
        "--output-dir", default=str(DEFAULT_OUTPUT),
        help="Directory for the generated studio (gitignored; default: newsdash-studio/)",
    )
    args = parser.parse_args()

    data = build_data()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "source-studio.html"
    out_file.write_text(render_html(data), encoding="utf-8")

    n = len(data["sources"])
    print(f"Wrote {out_file} ({n} source{'s' if n != 1 else ''}).")
    print("Open it in a browser, edit your sources, then Save / Copy the plan.")
    print("The agent reads it back from: "
          f"{out_dir / 'sources.plan.json'} (or your pasted JSON).")


TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Source Studio</title>
<script id="studio-data" type="application/json">/*__STUDIO_DATA__*/</script>
<style>
  :root { color-scheme: light dark; --fg:#1a1a1a; --muted:#666; --bg:#faf9f7;
          --card:#fff; --line:#e2ded7; --accent:#8a1f1f; --accent-fg:#fff;
          --warn:#a15c00; --ok:#2b6b3a; }
  @media (prefers-color-scheme: dark) {
    :root { --fg:#e8e6e2; --muted:#9a958c; --bg:#171614; --card:#201f1c;
            --line:#33312d; --accent:#d98b8b; --accent-fg:#171614; --warn:#d8a24a; --ok:#79c088; }
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.5 -apple-system,
         BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", sans-serif; }
  .wrap { max-width: 60rem; margin: 0 auto; padding: 1.5rem 1.25rem 5rem; }
  h1 { font-family: Georgia, "Noto Serif SC", serif; font-size: 1.7rem; margin: 0 0 .2rem; }
  h2 { font-family: Georgia, serif; font-size: 1.1rem; margin: 1.6rem 0 .6rem; }
  p.lead { color: var(--muted); margin: 0 0 1rem; }
  .panel { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
           padding: 1rem 1.1rem; margin-bottom: 1rem; }
  .src { border: 1px solid var(--line); border-radius: 8px; padding: .7rem .8rem;
         margin-bottom: .6rem; background: var(--card); }
  .src.removed { opacity: .45; }
  .src.priv { border-left: 3px solid var(--accent); }
  .row { display: flex; flex-wrap: wrap; gap: .5rem .7rem; align-items: center; }
  .row + .row { margin-top: .5rem; }
  label { font-size: .78rem; color: var(--muted); display: block; margin-bottom: .1rem; }
  .f { display: flex; flex-direction: column; }
  .f.grow { flex: 1 1 14rem; }
  input, select { font: inherit; padding: .35rem .5rem; border: 1px solid var(--line);
                  border-radius: 6px; background: var(--bg); color: var(--fg); }
  input.w { width: 5rem; } input.id { width: 12rem; } input.sec { width: 9rem; }
  button { font: inherit; cursor: pointer; border: 1px solid var(--line);
           border-radius: 6px; padding: .4rem .8rem; background: var(--card); color: var(--fg); }
  button.primary { background: var(--accent); color: var(--accent-fg); border-color: var(--accent); }
  button.link { background: none; border: none; color: var(--accent); padding: .2rem .3rem; }
  .sec-head { font-family: Georgia, serif; font-size: .95rem; color: var(--muted);
              margin: 1.1rem 0 .4rem; text-transform: uppercase; letter-spacing: .04em; }
  .tag { font-size: .72rem; padding: .05rem .4rem; border-radius: 999px; border: 1px solid var(--line); color: var(--muted); }
  .tag.priv { color: var(--accent); border-color: var(--accent); }
  .warnmsg { color: var(--warn); font-size: .82rem; margin: .3rem 0 0; }
  .foot { position: fixed; left: 0; right: 0; bottom: 0; background: var(--card);
          border-top: 1px solid var(--line); padding: .7rem 1.25rem; display: flex;
          gap: .6rem; align-items: center; flex-wrap: wrap; }
  .foot .status { color: var(--muted); font-size: .85rem; margin-right: auto; }
  .foot .status.bad { color: var(--warn); }
  .foot .status.good { color: var(--ok); }
  .muted { color: var(--muted); }
  .chk { display: flex; align-items: center; gap: .3rem; }
  .presets label.pk { display: inline-flex; align-items: center; gap: .4rem; margin: .2rem .9rem .2rem 0;
                      color: var(--fg); font-size: .95rem; }
</style>
</head>
<body>
<div class="wrap">
  <h1 id="title">Source Studio</h1>
  <p class="lead" id="lead"></p>

  <div class="panel presets">
    <h2 id="h-presets"></h2>
    <div id="presets"></div>
  </div>

  <h2 id="h-sources"></h2>
  <div id="sources"></div>
  <button id="add" class="primary" style="margin-top:.4rem"></button>
</div>

<div class="foot">
  <span class="status" id="status"></span>
  <button id="save"></button>
  <button id="copy"></button>
  <button id="download"></button>
</div>

<script>
const DATA = JSON.parse(document.getElementById("studio-data").textContent);
const L = DATA.site.lang === "zh" ? "zh" : "en";
const BRAND = L === "zh" ? "及君" : "Relevance";

const STR = {
  en: {
    title: BRAND + " — Source Studio",
    lead: "Curate your sources offline. Add, edit, or remove feeds, set each one public or private, then Save the plan — your coding agent applies it. This file is local and never uploaded.",
    hPresets: "Starter packs", hSources: "Your sources",
    add: "+ Add a source", save: "Save to working folder", copy: "Copy for agent",
    download: "Download JSON", copied: "Copied ✓", saved: "Saved ✓",
    name: "Name", id: "ID", kind: "Kind", section: "Section", weight: "Weight",
    enabled: "State", url: "Feed URL", secret: "Secret name", value: "Value",
    remove: "Remove", undo: "Undo", on: "On", off: "Off", auto: "Auto",
    ready: "Ready", issues: (n) => n + " thing" + (n === 1 ? "" : "s") + " to fix",
    noUrlPriv: "Private feeds take a secret NAME only — never paste the URL here.",
    kinds: { news: "News", blog: "Blog", youtube: "YouTube", podcast: "Podcast",
             social: "Social", scholar: "Scholar (follow)", journal: "Journal",
             topic: "Topic / arXiv", private: "Private feed", advanced: "Advanced" },
    val: { name: "Value", url: "Feed or page URL", filter: "OpenAlex author id or query",
           issn: "ISSN(s), comma-separated", query: "arXiv query (e.g. cat:cs.CL)" },
    errId: "invalid or duplicate ID", errUrl: "needs a feed URL",
    errSecret: "needs a SECRET_NAME (UPPER_SNAKE)", errIssn: "needs an ISSN",
    errWeight: "weight must be 0–1",
    saveHint: "Saved. Tell your agent the plan is ready.",
  },
  zh: {
    title: BRAND + " — 信源工作台",
    lead: "在本地整理你的信源：添加、编辑或删除，设置公开或私密，然后保存方案——由编程助手应用。此文件仅存本地，不会上传。",
    hPresets: "预设信源包", hSources: "你的信源",
    add: "+ 添加信源", save: "保存到工作文件夹", copy: "复制给助手",
    download: "下载 JSON", copied: "已复制 ✓", saved: "已保存 ✓",
    name: "名称", id: "ID", kind: "类型", section: "栏目", weight: "权重",
    enabled: "状态", url: "信源地址", secret: "Secret 名称", value: "值",
    remove: "删除", undo: "撤销", on: "开", off: "关", auto: "自动",
    ready: "就绪", issues: (n) => "有 " + n + " 处需修正",
    noUrlPriv: "私密信源只填 Secret 名称——切勿在此粘贴 URL。",
    kinds: { news: "新闻", blog: "博客", youtube: "YouTube", podcast: "播客",
             social: "社交媒体", scholar: "关注学者", journal: "期刊",
             topic: "主题 / arXiv", private: "私密信源", advanced: "高级" },
    val: { name: "值", url: "信源或页面 URL", filter: "OpenAlex 作者 ID 或查询",
           issn: "ISSN（逗号分隔）", query: "arXiv 查询（如 cat:cs.CL）" },
    errId: "ID 无效或重复", errUrl: "缺少信源 URL",
    errSecret: "缺少 SECRET 名称（大写下划线）", errIssn: "缺少 ISSN",
    errWeight: "权重需在 0–1 之间",
    saveHint: "已保存。告诉助手方案已就绪。",
  },
}[L];

// Friendly kind -> backend defaults.
const KINDS = {
  news:     { type: "rss",      section: "news",      cat: "open",     field: "url" },
  blog:     { type: "rss",      section: "news",      cat: "open",     field: "url" },
  youtube:  { type: "rss",      section: "news",      cat: "open",     field: "url" },
  podcast:  { type: "rss",      section: "news",      cat: "open",     field: "url" },
  social:   { type: "rss",      section: "following", cat: "open",     field: "url" },
  scholar:  { type: "openalex", section: "following", cat: "optional", field: "filter" },
  journal:  { type: "crossref", section: "papers",    cat: "optional", field: "issn" },
  topic:    { type: "arxiv",    section: "papers",    cat: "optional", field: "query" },
  private:  { type: "rss",      section: "private",   cat: "private",  field: "secret" },
  advanced: { type: "rss",      section: "news",      cat: "open",     field: "url" },
};
const ID_RE = /^[a-z0-9_]{2,64}$/;
const SECRET_RE = /^[A-Z][A-Z0-9_]{1,63}$/;
const ISSN_RE = /^[0-9]{4}-[0-9]{3}[0-9Xx]$/;

let rid = 0;
function deriveKind(s) {
  if (s.category === "private") return "private";
  switch (s.type) {
    case "openalex": return "scholar";
    case "crossref": return "journal";
    case "arxiv": case "semanticscholar": return "topic";
    case "opml": case "feed-json": case "static-page": return "advanced";
    default:
      if ((s.url || "").includes("youtube.com/feeds")) return "youtube";
      return "news";
  }
}
function primaryValue(s) {
  if (s.category === "private") return (s.secret_ref || [])[0] || "";
  if (s.type === "openalex") return s.filter || s.query || "";
  if (s.type === "crossref") return (s.issn || []).join(", ");
  if (s.type === "arxiv" || s.type === "semanticscholar") return s.query || "";
  return s.url || "";
}

// Working state: one row object per source.
const rows = DATA.sources.map((s) => ({
  rid: rid++, removed: false,
  id: s.id || "", name: s.name || "", kind: deriveKind(s),
  section: s.section || "news",
  weight: (s.weight != null ? s.weight : 0.8),
  enabled: s.enabled === false ? "off" : (s.enabled === "auto" ? "auto" : "on"),
  value: primaryValue(s),
  type: s.type || "rss",           // used by advanced
}));
const activePresets = new Set(DATA.presets.active || []);

const $ = (sel) => document.querySelector(sel);
function opt(v, label, sel) {
  const o = document.createElement("option");
  o.value = v; o.textContent = label; if (v === sel) o.selected = true; return o;
}

function fieldLabelKey(kind) {
  const f = KINDS[kind].field;
  if (f === "url") return "url";
  if (f === "filter") return "filter";
  if (f === "issn") return "issn";
  if (f === "query") return "query";
  return "name";
}

function rowEl(r) {
  const wrap = document.createElement("div");
  wrap.className = "src" + (r.kind === "private" ? " priv" : "") + (r.removed ? " removed" : "");

  const line1 = document.createElement("div");
  line1.className = "row";
  line1.append(
    field(STR.name, mkInput(r, "name", "grow")),
    field(STR.id, mkInput(r, "id", "", "id")),
    field(STR.kind, mkKind(r)),
    field(STR.section, mkSection(r)),
  );
  wrap.append(line1);

  const line2 = document.createElement("div");
  line2.className = "row";
  const isPriv = r.kind === "private";
  const valLabel = isPriv ? STR.secret : STR.val[fieldLabelKey(r.kind)];
  line2.append(
    field(valLabel, mkInput(r, "value", "grow"), isPriv ? STR.noUrlPriv : ""),
    field(STR.weight, mkWeight(r)),
    field(STR.enabled, mkEnabled(r)),
  );
  const rm = document.createElement("button");
  rm.className = "link";
  rm.textContent = r.removed ? STR.undo : STR.remove;
  rm.onclick = () => { r.removed = !r.removed; render(); };
  const rmF = document.createElement("div"); rmF.className = "f";
  rmF.append(document.createElement("label"), rm);
  line2.append(rmF);
  wrap.append(line2);
  return wrap;
}

function field(labelText, control, warn) {
  const f = document.createElement("div");
  f.className = "f" + (control.classList.contains("grow") ? " grow" : "");
  const lab = document.createElement("label"); lab.textContent = labelText;
  f.append(lab, control);
  if (warn) { const w = document.createElement("p"); w.className = "warnmsg"; w.textContent = warn; f.append(w); }
  return f;
}
function mkInput(r, key, cls, extra) {
  const i = document.createElement("input");
  i.type = "text"; if (cls) i.className = cls; if (extra) i.classList.add(extra);
  i.value = r[key]; i.oninput = () => { r[key] = i.value; updateStatus(); };
  return i;
}
function mkWeight(r) {
  const i = document.createElement("input");
  i.type = "number"; i.min = "0"; i.max = "1"; i.step = "0.05"; i.className = "w";
  i.value = r.weight; i.oninput = () => { r.weight = parseFloat(i.value); updateStatus(); };
  return i;
}
function mkKind(r) {
  const s = document.createElement("select");
  Object.keys(KINDS).forEach((k) => s.append(opt(k, STR.kinds[k], r.kind)));
  s.onchange = () => {
    r.kind = s.value; const d = KINDS[r.kind];
    if (!DATA.sections.includes(r.section) || ["news", "papers", "following", "private"].includes(r.section)) {
      r.section = d.section;
    }
    r.type = d.type;
    render();
  };
  return s;
}
function mkSection(r) {
  const i = document.createElement("input");
  i.className = "sec"; i.setAttribute("list", "sections"); i.value = r.section;
  i.oninput = () => { r.section = i.value.trim(); updateStatus(); };
  return i;
}
function mkEnabled(r) {
  const s = document.createElement("select");
  s.append(opt("on", STR.on, r.enabled), opt("off", STR.off, r.enabled), opt("auto", STR.auto, r.enabled));
  s.onchange = () => { r.enabled = s.value; };
  return s;
}

function render() {
  $("#title").textContent = STR.title;
  document.title = STR.title;
  $("#lead").textContent = STR.lead;
  $("#h-presets").textContent = STR.hPresets;
  $("#h-sources").textContent = STR.hSources;
  $("#add").textContent = STR.add;
  $("#save").textContent = STR.save;
  $("#copy").textContent = STR.copy;
  $("#download").textContent = STR.download;

  // section datalist
  let dl = document.getElementById("sections");
  if (!dl) { dl = document.createElement("datalist"); dl.id = "sections"; document.body.append(dl); }
  dl.innerHTML = "";
  DATA.sections.forEach((s) => { const o = document.createElement("option"); o.value = s; dl.append(o); });

  // presets
  const pc = $("#presets"); pc.innerHTML = "";
  (DATA.presets.available || []).forEach((p) => {
    const lab = document.createElement("label"); lab.className = "pk";
    const cb = document.createElement("input"); cb.type = "checkbox";
    cb.checked = activePresets.has(p.id);
    cb.onchange = () => { cb.checked ? activePresets.add(p.id) : activePresets.delete(p.id); };
    const nm = (p.name && (p.name[L] || p.name.en)) || p.id;
    lab.append(cb, document.createTextNode(nm + " (" + p.count + ")"));
    pc.append(lab);
  });
  if (!(DATA.presets.available || []).length) pc.innerHTML = "<span class='muted'>—</span>";

  // sources grouped by section
  const host = $("#sources"); host.innerHTML = "";
  const bySec = {};
  rows.forEach((r) => { (bySec[r.section] = bySec[r.section] || []).push(r); });
  const secOrder = DATA.sections.filter((s) => bySec[s]).concat(
    Object.keys(bySec).filter((s) => !DATA.sections.includes(s)));
  secOrder.forEach((sec) => {
    const h = document.createElement("div"); h.className = "sec-head"; h.textContent = sec;
    host.append(h);
    bySec[sec].forEach((r) => host.append(rowEl(r)));
  });
  updateStatus();
}

function validate() {
  const errs = [];
  const ids = {};
  rows.filter((r) => !r.removed).forEach((r) => {
    if (!ID_RE.test(r.id) || ids[r.id]) errs.push([r, STR.errId]);
    ids[r.id] = true;
    if (!(r.weight >= 0 && r.weight <= 1)) errs.push([r, STR.errWeight]);
    const f = KINDS[r.kind].field;
    if (f === "secret" && !SECRET_RE.test((r.value || "").trim())) errs.push([r, STR.errSecret]);
    if (f === "url" && !/^https?:\/\//.test((r.value || "").trim())) errs.push([r, STR.errUrl]);
    if (f === "issn" && !(r.value || "").split(/[,\s]+/).some((x) => ISSN_RE.test(x.trim()))) errs.push([r, STR.errIssn]);
  });
  return errs;
}
function updateStatus() {
  const errs = validate();
  const st = $("#status");
  if (errs.length) { st.textContent = STR.issues(errs.length); st.className = "status bad"; }
  else { st.textContent = STR.ready; st.className = "status good"; }
}

// Build a config-shaped source (only schema fields; no url for private).
function toConfig(r) {
  const d = KINDS[r.kind];
  const type = r.kind === "advanced" ? r.type : d.type;
  const cat = d.cat;
  const o = { id: r.id, category: cat, type, section: r.section, name: r.name };
  const v = (r.value || "").trim();
  if (cat === "private") {
    o.enabled = "auto";
    o.secret_ref = [v];
  } else {
    if (r.enabled === "off") o.enabled = false;
    else if (r.enabled === "auto") o.enabled = "auto";
    if (type === "openalex") { v.includes(":") ? (o.filter = v) : (o.query = v); }
    else if (type === "crossref") { o.issn = v.split(/[,\s]+/).map((x) => x.trim()).filter(Boolean); }
    else if (type === "arxiv" || type === "semanticscholar") { o.query = v; }
    else if (v) { o.url = v; }
  }
  if (r.weight != null && !Number.isNaN(r.weight)) o.weight = r.weight;
  return o;
}
function buildPlan() {
  return {
    schema: "newsdash-source-plan/v1",
    presets: [...activePresets],
    interests: DATA.interests,
    sources: rows.filter((r) => !r.removed).map(toConfig),
  };
}
function planText() { return JSON.stringify(buildPlan(), null, 2); }

// A plan is only emitted when it is valid — this is the barrier that stops a
// capability URL mistyped into a "Secret name" field (which fails validation)
// from being copied into chat or written to disk.
function guardEmit() {
  const errs = validate();
  if (!errs.length) return true;
  const st = $("#status");
  st.textContent = STR.issues(errs.length); st.className = "status bad";
  st.scrollIntoView({ block: "center" });
  return false;
}

async function doSave() {
  if (!guardEmit()) return;
  const text = planText();
  if (window.showSaveFilePicker) {
    try {
      const h = await window.showSaveFilePicker({
        suggestedName: "sources.plan.json",
        types: [{ description: "JSON", accept: { "application/json": [".json"] } }],
      });
      const w = await h.createWritable(); await w.write(text); await w.close();
      flash("#save", STR.saved); $("#status").textContent = STR.saveHint;
      return;
    } catch (e) { if (e && e.name === "AbortError") return; }
  }
  doDownload(); // fallback when the File System Access API is unavailable
}
function doDownload() {
  if (!guardEmit()) return;
  const blob = new Blob([planText()], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "sources.plan.json";
  a.click(); URL.revokeObjectURL(a.href); flash("#download", STR.saved);
}
function doCopy() {
  if (!guardEmit()) return;
  navigator.clipboard.writeText(planText()).then(() => flash("#copy", STR.copied));
}
function flash(sel, txt) {
  const b = $(sel); const old = b.textContent; b.textContent = txt;
  setTimeout(() => { b.textContent = old; }, 1500);
}

$("#add").onclick = () => {
  rows.push({ rid: rid++, removed: false, id: "", name: "", kind: "news",
              section: "news", weight: 0.8, enabled: "on", value: "", type: "rss" });
  render();
};
$("#save").onclick = doSave;
$("#save").classList.add("primary");
$("#copy").onclick = doCopy;
$("#download").onclick = doDownload;

render();
</script>
</body>
</html>
'''


if __name__ == "__main__":
    main()
