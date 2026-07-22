#!/usr/bin/env python3
"""Issue-ops onboarding: parse the "Set up my Relevance" issue-form body,
rewrite config/site.json + config/sources.json, and emit the bilingual
comment the workflow posts back.

The heading labels in .github/ISSUE_TEMPLATE/setup.yml are the contract:
this parser keys on the English part of each label (before " ·").
tests/test_issue_parser.py enforces the pairing.

Usage:
    python scripts/apply_issue_setup.py --body-file body.md \
        --comment-out comment.md --repo owner/name [--repo-root PATH]

Exit codes: 0 = applied; 2 = rejected (comment-out still written).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from newsdash.config import ConfigError, load_config

NO_RESPONSE = "_No response_"

FIELD_LANGUAGE = "Interface language"
FIELD_VISIBILITY = "Site visibility"
FIELD_THEME = "Theme"
FIELD_TITLE = "Site title"
FIELD_TIMEZONE = "Timezone"
FIELD_OPEN_PACKS = "Open news packs"
FIELD_ACADEMIC_PACKS = "Academic packs"
FIELD_EXTRA_RSS = "Extra RSS feeds"
FIELD_INTERESTS = "Interest keywords"
FIELD_UPDATE_FREQ = "Update frequency"
FIELD_ACK = "Acknowledgement"

# Update-frequency dropdown → NEWSDASH_UPDATE_FREQ repo-Variable value. The
# knob is a repo Variable, never written into config files; the workflow reads
# `update_freq` from GITHUB_OUTPUT and sets the Variable. Values are pinned to
# this whitelist — anything else (junk API body) maps to "" and is ignored.
UPDATE_FREQ_MAP = {
    "Every 2 hours (default)": "2h",
    "3 times a day": "3x",
    "Once a day": "daily",
}

# add-source.yml field labels (English segment is the parser contract).
FIELD_ACTION = "Action"
FIELD_SOURCE_ID = "Source ID"
FIELD_CATEGORY = "Category"
FIELD_TYPE = "Type"
FIELD_SECTION = "Section"
FIELD_NAME = "Name"
FIELD_URL_QUERY = "URL or query (public sources only)"
FIELD_ISSN = "ISSN(s)"
FIELD_SECRET_NAME = "Secret name (private sources only)"

URL_TYPES = {"rss", "feed-json", "static-page", "opml"}
QUERY_TYPES = {"arxiv", "openalex", "semanticscholar"}
SECRET_NAME_RE = re.compile(r"^SRC_[A-Z0-9_]+$")
SOURCE_ID_RE = re.compile(r"^[a-z0-9_]{2,64}$")

OPEN_PACK_MAP = [("AI news", "ai-news"), ("General news", "general-news")]
ACADEMIC_PACK_MAP = [("Data visualization", "academic-datavis"),
                     ("Technical communication", "academic-techcomm")]

CUSTOM_RSS_PREFIX = "custom_rss_"

SECRET_PATTERN = re.compile(
    r"(github_pat_|ghp_[A-Za-z0-9]{20,}|/calendar/ical/.+/private|Bearer\s+[A-Za-z0-9._-]{20,}"
    r"|[?&](token|key|secret|sig|signature)=)",
    re.IGNORECASE,
)


def parse_form(body: str) -> dict[str, str]:
    """Issue-form bodies render as '### Label\\n\\nvalue' blocks."""
    fields: dict[str, str] = {}
    current = None
    lines: list[str] = []
    for line in body.splitlines():
        match = re.match(r"^###\s+(.*)$", line)
        if match:
            if current is not None:
                fields[current] = "\n".join(lines).strip()
            heading = match.group(1).strip()
            current = heading.split("·")[0].strip()  # English part is the key
            lines = []
        elif current is not None:
            lines.append(line)
    if current is not None:
        fields[current] = "\n".join(lines).strip()
    return fields


def field(fields: dict[str, str], key: str) -> str:
    value = fields.get(key, "").strip()
    return "" if value == NO_RESPONSE else value


def checked_labels(raw: str) -> list[str]:
    return [m.group(1).strip()
            for m in re.finditer(r"^- \[[xX]\] (.+)$", raw, re.MULTILINE)]


def slug_for_feed(url: str, taken: set[str]) -> str:
    host = (urlsplit(url).hostname or "feed").lower()
    base = CUSTOM_RSS_PREFIX + re.sub(r"[^a-z0-9]+", "_", host).strip("_")[:40]
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}_{n}", n + 1
    taken.add(slug)
    return slug


def apply(body: str, repo_root: Path) -> tuple[dict, list[str]]:
    """Mutate config files from the parsed form; returns (summary, warnings)."""
    fields = parse_form(body)
    warnings: list[str] = []

    if SECRET_PATTERN.search(body):
        raise ValueError(
            "The issue body contains something that looks like a credential. "
            "Nothing was applied — please edit the issue to remove it, and "
            "rotate that credential if it was real."
        )
    if "[x]" not in fields.get(FIELD_ACK, "").lower():
        raise ValueError("The acknowledgement checkbox is required.")

    site_path = repo_root / "config" / "site.json"
    sources_path = repo_root / "config" / "sources.json"
    site = json.loads(site_path.read_text(encoding="utf-8"))
    sources = json.loads(sources_path.read_text(encoding="utf-8"))

    # site.json -----------------------------------------------------------
    lang_raw = field(fields, FIELD_LANGUAGE)
    if lang_raw:
        site["default_language"] = "zh" if lang_raw.startswith("中文") else "en"

    vis_raw = field(fields, FIELD_VISIBILITY)
    if vis_raw:
        site["visibility"] = "private" if vis_raw.startswith("Private") else "public"

    theme_raw = field(fields, FIELD_THEME)
    if theme_raw:
        theme = theme_raw.split("—")[0].split(" ")[0].strip()
        if theme in ("the-type", "nyt", "bear"):
            site["theme"] = theme
        else:
            warnings.append(f"unknown theme {theme!r} ignored")

    title = field(fields, FIELD_TITLE)
    if title:
        site["title"] = title[:120]

    tz = field(fields, FIELD_TIMEZONE)
    if tz:
        try:
            ZoneInfo(tz)
            site["timezone"] = tz
        except Exception:
            warnings.append(f"unknown timezone {tz!r} ignored (kept {site['timezone']!r})")

    # Update frequency is NOT a config value — it maps to the NEWSDASH_UPDATE_FREQ
    # repo Variable, surfaced via GITHUB_OUTPUT for the workflow to set. An
    # unknown/absent selection maps to "" (workflow leaves the Variable alone).
    freq_raw = _dropdown(fields, FIELD_UPDATE_FREQ)
    update_freq = UPDATE_FREQ_MAP.get(freq_raw, "")
    if freq_raw and not update_freq:
        warnings.append(f"unknown update frequency {freq_raw!r} ignored")

    # sources.json --------------------------------------------------------
    presets: list[str] = []
    open_checked = checked_labels(fields.get(FIELD_OPEN_PACKS, ""))
    for label_prefix, preset_id in OPEN_PACK_MAP:
        if any(label.startswith(label_prefix) for label in open_checked):
            presets.append(preset_id)
    academic_checked = checked_labels(fields.get(FIELD_ACADEMIC_PACKS, ""))
    for label_prefix, preset_id in ACADEMIC_PACK_MAP:
        if any(label.startswith(label_prefix) for label in academic_checked):
            presets.append(preset_id)
    if not presets:
        presets = ["ai-news", "general-news"]
        warnings.append("no packs selected; kept the default ai-news + general-news")
    sources["presets"] = presets

    interests_raw = field(fields, FIELD_INTERESTS)
    if interests_raw:
        keywords = [k.strip() for k in re.split(r"[,，]", interests_raw) if k.strip()]
        sources.setdefault("interests", {})["keywords"] = keywords[:20]

    kept = [s for s in sources.get("sources", [])
            if not s.get("id", "").startswith(CUSTOM_RSS_PREFIX)]
    taken = {s.get("id", "") for s in kept}
    extra_urls = [u.strip() for u in field(fields, FIELD_EXTRA_RSS).splitlines()
                  if u.strip()]
    added_feeds = []
    for url in extra_urls[:20]:
        if not re.match(r"^https?://", url):
            warnings.append(f"skipped non-http feed line: {url[:60]!r}")
            continue
        slug = slug_for_feed(url, taken)
        kept.append({
            "id": slug, "category": "open", "type": "rss", "section": "news",
            "name": urlsplit(url).hostname or slug, "url": url, "weight": 0.8,
        })
        added_feeds.append(url)
    sources["sources"] = kept

    original_site = site_path.read_text(encoding="utf-8")
    original_sources = sources_path.read_text(encoding="utf-8")
    site_path.write_text(json.dumps(site, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    sources_path.write_text(json.dumps(sources, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")

    # final gate: the merged config must still validate; restore on failure so
    # a rejected form never leaves half-applied config behind
    try:
        load_config(repo_root, env={})
    except ConfigError as exc:
        site_path.write_text(original_site, encoding="utf-8")
        sources_path.write_text(original_sources, encoding="utf-8")
        raise ValueError(f"resulting config failed validation: {exc}") from exc

    summary = {
        "language": site["default_language"],
        "visibility": site["visibility"],
        "theme": site["theme"],
        "title": site["title"],
        "timezone": site["timezone"],
        "presets": presets,
        "extra_feeds": added_feeds,
        "interests": sources.get("interests", {}).get("keywords", []),
        "update_freq": update_freq,
    }
    return summary, warnings


def _dropdown(fields: dict[str, str], key: str) -> str:
    """Selected dropdown value; keep only the English part before ' ·'."""
    return field(fields, key).split("·")[0].strip()


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:64]


def _preset_source_ids(repo_root: Path, sources: dict) -> set[str]:
    """Ids provided by the presets currently referenced in sources.json."""
    ids: set[str] = set()
    for preset_id in sources.get("presets", []):
        pack_path = repo_root / "config" / "presets" / f"{preset_id}.json"
        try:
            pack = json.loads(pack_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        for raw in pack.get("sources", []):
            if isinstance(raw, dict) and raw.get("id"):
                ids.add(raw["id"])
    return ids


def _existing_source_category(repo_root: Path, sources: dict, sid: str,
                             customs: list[dict], idx: int | None) -> str:
    """Effective category of an already-configured source `sid`, or "".

    Mirrors the merge load_config performs: a custom entry's own `category`
    wins; otherwise the category comes from whichever preset pack defines the
    id (the source's own `category`, else the pack default). Used to protect an
    EXISTING private source regardless of the category the issue submits.
    """
    if idx is not None and customs[idx].get("category"):
        return customs[idx]["category"]
    for preset_id in sources.get("presets", []):
        pack_path = repo_root / "config" / "presets" / f"{preset_id}.json"
        try:
            pack = json.loads(pack_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        for raw in pack.get("sources", []):
            if isinstance(raw, dict) and raw.get("id") == sid:
                return raw.get("category") or pack.get("category", "")
    return ""


LEAK_MESSAGE = (
    "This source is marked **private**, but the URL/query field is not empty. "
    "A capability URL pasted into a public issue must be treated as LEAKED: "
    "rotate/regenerate it now, put the new value only in Settings → Secrets, and "
    "leave this field blank. "
    "该信源为私密，但填写了地址/查询字段。粘贴于公开 Issue 的凭据 URL 必须视为已泄露："
    "请立即重新生成，新值只放入 Settings → Secrets，并将此字段留空。"
)

CATEGORY_LOCK_MESSAGE = (
    "This source is currently **private**. Its category cannot be changed to "
    "public/optional through the issue flow, because a private source's "
    "capability URL lives in a GitHub Secret that must be rotated first. To "
    "de-privatize it, rotate the credential, then use the Page Skill (书童Skill) "
    "or open a pull request. "
    "该信源当前为**私密**。无法通过 Issue 流程将其类别改为公开/可选："
    "私密信源的凭据 URL 存放于 GitHub Secret，需先轮换。如需转为公开，"
    "请先轮换凭据，再使用书童 Skill 或提交 Pull Request。"
)

# Static, value-free message for a post-write validation failure in the source
# flow. The raw ConfigError / jsonschema text embeds the offending value, which
# would be echoed into the public issue comment and the ::error:: Actions log —
# so it must NEVER be interpolated here. Config is restored before this raises.
SOURCE_VALIDATION_MESSAGE = (
    "The resulting configuration did not pass validation, so nothing was "
    "applied (the previous config was restored). Please check this source's "
    "Type / Category / Section / URL combination against docs/CONFIG_REFERENCE.md "
    "and try again. Details are withheld here to avoid echoing any submitted value. "
    "生成的配置未通过校验，已回滚，未作任何改动。请对照 docs/CONFIG_REFERENCE.md "
    "检查该信源的 类型 / 类别 / 栏目 / 地址 组合后重试。为避免回显提交内容，此处不显示详细报错。"
)


def apply_source(fields: dict[str, str], repo_root: Path) -> tuple[dict, list[str]]:
    """Add/update/remove one source in config/sources.json from a parsed form.

    The whole-body SECRET_PATTERN gate is expected to have run already (see
    apply_any). Security invariants this enforces:
    - never writes a url/query/issn/path onto a private source;
    - an EXISTING private source is protected by a category-transition guard:
      any URL/query/ISSN targeting it is treated as a leaked capability URL and
      rejected without echoing the value, and its category can never be flipped
      off "private" via the issue flow;
    - never echoes a rejected URL value, nor raw validation detail (which can
      embed a submitted value), back in any message or the ::error:: log line.
    """
    warnings: list[str] = []

    if "[x]" not in fields.get(FIELD_ACK, "").lower():
        raise ValueError("The acknowledgement checkbox is required. 需要勾选确认项。")

    action = _dropdown(fields, FIELD_ACTION).lower()
    if action not in ("add", "update", "remove"):
        raise ValueError(f"unknown action {action!r}; expected Add/Update/Remove.")

    id_raw = field(fields, FIELD_SOURCE_ID)
    name = field(fields, FIELD_NAME)
    category = _dropdown(fields, FIELD_CATEGORY).lower()
    stype = _dropdown(fields, FIELD_TYPE)
    section = _dropdown(fields, FIELD_SECTION)
    url_or_query = field(fields, FIELD_URL_QUERY)
    issn_raw = field(fields, FIELD_ISSN)
    secret_name = field(fields, FIELD_SECRET_NAME)

    if action == "add" and not id_raw:
        sid = _slugify(name)
    else:
        sid = id_raw.strip().lower()
    if not SOURCE_ID_RE.match(sid):
        raise ValueError(
            "Source ID must be lowercase snake_case matching ^[a-z0-9_]{2,64}$ "
            "(supply Source ID, or a Name to derive it from for Add). "
            "信源标识需为小写下划线命名，匹配 ^[a-z0-9_]{2,64}$。"
        )

    sources_path = repo_root / "config" / "sources.json"
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    customs: list[dict] = sources.setdefault("sources", [])
    idx = next((i for i, s in enumerate(customs) if s.get("id") == sid), None)

    is_private = False
    entry: dict = {}
    change = ""

    if action == "remove":
        if sid in _preset_source_ids(repo_root, sources):
            # documented preset-mute: an override {"id", "enabled": false}
            if idx is not None:
                customs[idx]["enabled"] = False
            else:
                customs.append({"id": sid, "enabled": False})
            change = f"muted preset source `{sid}` (override `enabled: false`)"
        elif idx is not None:
            customs.pop(idx)
            change = f"removed custom source `{sid}`"
        else:
            raise ValueError(
                f"no source with id `{sid}` found to remove. 未找到要移除的信源。")
    else:  # add / update
        entry = dict(customs[idx]) if idx is not None else {"id": sid}
        entry["id"] = sid

        # Category-transition guard: if the source ALREADY exists as private
        # (custom entry or preset), it is protected no matter what category the
        # issue submits. This keys off the EXISTING category, not the submitted
        # one, closing the leak where Update+Category=open (or blank) would
        # otherwise flip private→open with a capability URL persisted/echoed.
        existing_category = _existing_source_category(
            repo_root, sources, sid, customs, idx)
        if existing_category == "private":
            # (a) any URL/query/ISSN targeting a private source in a public
            # issue is a leaked-credential event — reject, never echo. This
            # fires BEFORE the write/validate gate so the jsonschema message
            # (which embeds the value) can never reach any surface.
            if url_or_query or issn_raw:
                raise ValueError(LEAK_MESSAGE)  # never echo the value back
            # (b) category may not be changed off "private" via the issue flow.
            if category in ("open", "optional"):
                raise ValueError(CATEGORY_LOCK_MESSAGE)  # static, no echo
            # (c) blank category inherits "private" and keeps all invariants.
            category = "private"

        is_private = category == "private"
        if is_private:
            if url_or_query or issn_raw:
                raise ValueError(LEAK_MESSAGE)  # never echo the value back
            if secret_name and not SECRET_NAME_RE.match(secret_name):
                # the NAME is not a secret; echoing the name is fine
                raise ValueError(
                    f"Secret name `{secret_name}` is invalid; it must match "
                    "^SRC_[A-Z0-9_]+$ (e.g. SRC_MY_FEED_URL). "
                    f"Secret 名称 `{secret_name}` 不合法，需匹配 ^SRC_[A-Z0-9_]+$。"
                )
            entry["category"] = "private"
            entry["enabled"] = "auto"
            # preserve an existing secret_ref on update; default on fresh add
            entry["secret_ref"] = ([secret_name] if secret_name
                                   else entry.get("secret_ref")
                                   or [f"SRC_{sid.upper()}_URL"])
            entry["section"] = section or entry.get("section") or "private"
            if stype:
                entry["type"] = stype
            if name:
                entry["name"] = name
            # a private source must never carry url/query/issn/path
            for k in ("url", "query", "issn", "path"):
                entry.pop(k, None)
            change = f"private source `{sid}` referencing secret `{entry['secret_ref'][0]}`"
        else:
            if category:
                entry["category"] = category
            if stype:
                entry["type"] = stype
            if section:
                entry["section"] = section
            if name:
                entry["name"] = name
            etype = entry.get("type", "")
            if etype in URL_TYPES:
                if url_or_query:
                    entry["url"] = url_or_query
                    entry.pop("query", None)
            elif etype in QUERY_TYPES:
                if url_or_query:
                    entry["query"] = url_or_query
                    entry.pop("url", None)
            elif etype == "crossref":
                if issn_raw:
                    entry["issn"] = [x.strip() for x in issn_raw.split(",") if x.strip()]
                elif url_or_query:
                    entry["query"] = url_or_query
            if action == "add":
                entry.setdefault("category", "open")
                entry.setdefault("section", "news")
                entry.setdefault("weight", 0.8)
            change = f"{action}ed source `{sid}`"

        if idx is not None:
            customs[idx] = entry
        else:
            customs.append(entry)

    # write → validate → restore-on-failure, same gate as apply()
    original_sources = sources_path.read_text(encoding="utf-8")
    sources_path.write_text(json.dumps(sources, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    try:
        load_config(repo_root, env={})
    except ConfigError as exc:
        sources_path.write_text(original_sources, encoding="utf-8")
        # Static message only: `exc` embeds the offending value (jsonschema
        # echoes it) and would leak into the public comment + ::error:: log.
        raise ValueError(SOURCE_VALIDATION_MESSAGE) from exc

    summary = {
        "kind": "source",
        "action": action,
        "id": sid,
        "private": is_private,
        "change": change,
        "secret_ref": entry.get("secret_ref", []),
        "entry": entry,
    }
    return summary, warnings


def apply_any(body: str, repo_root: Path) -> tuple[dict, list[str]]:
    """Whole-body secret gate, then dispatch to apply_source or apply()."""
    if SECRET_PATTERN.search(body):
        raise ValueError(
            "The issue body contains something that looks like a credential. "
            "Nothing was applied — please edit the issue to remove it, and "
            "rotate that credential if it was real."
        )
    fields = parse_form(body)
    if field(fields, FIELD_ACTION):
        return apply_source(fields, repo_root)
    return apply(body, repo_root)


def success_comment_source(summary: dict, warnings: list[str], repo: str) -> str:
    owner, _, name = repo.partition("/")
    action = summary["action"]
    sid = summary["id"]
    lines = [
        "## ✅ Source change applied · 信源已更新", "",
        f"- **Action · 操作**: `{action}`",
        f"- **Source ID · 信源标识**: `{sid}`",
    ]
    if summary.get("change"):
        lines.append(f"- {summary['change']}")
    if warnings:
        lines += ["", "### ⚠️ Notes"] + [f"- {w}" for w in warnings]

    if action == "add" and summary["private"]:
        secret = summary["secret_ref"][0]
        secrets_url = f"https://github.com/{owner}/{name}/settings/secrets/actions/new"
        lines += [
            "", "## Next steps · 后续步骤", "",
            f"1. **Create the secret `{secret}`** at {secrets_url} — paste the full "
            "capability URL as the value (it must start with `https://`). Paste it "
            "**ONLY there**, never back into this issue. "
            f"在 Secrets 页面创建 `{secret}`，值为完整凭据 URL（须以 https:// 开头）；值只粘贴在 Secrets 页面。",
            "2. **Ensure the `NEWSDASH_PASSPHRASE` secret is set** — private sections "
            "refuse to build without it. 确保已配置 `NEWSDASH_PASSPHRASE`，否则私密内容不会构建。",
            "3. **Run the update workflow** "
            f"([Actions → Update Relevance](https://github.com/{repo}/actions/workflows/update.yml)) "
            "and check the 🔒 Private tab after you unlock. 运行更新工作流后，解锁并查看 🔒 私密标签页。",
        ]
    elif action in ("add", "update") and not summary["private"]:
        entry = summary.get("entry", {})
        lines += [
            "", "Config entry · 配置条目 (public — URLs are fine here):",
            "```json", json.dumps(entry, ensure_ascii=False, indent=2), "```",
        ]

    lines += [
        "",
        "A rebuild is running: "
        f"[Actions → Update Relevance](https://github.com/{repo}/actions/workflows/update.yml)",
    ]
    return "\n".join(lines) + "\n"


def success_comment(summary: dict, warnings: list[str], repo: str) -> str:
    owner, _, name = repo.partition("/")
    site_url = f"https://{owner}.github.io/{name}/"
    private = summary["visibility"] == "private"
    lines = [
        "## ✅ Preferences applied · 配置已应用", "",
        f"- **Theme · 主题**: `{summary['theme']}`",
        f"- **Language · 语言**: `{summary['language']}`",
        f"- **Visibility · 可见性**: `{summary['visibility']}`",
        f"- **Timezone · 时区**: `{summary['timezone']}`",
        f"- **Packs · 信源包**: {', '.join(f'`{p}`' for p in summary['presets'])}",
    ]
    if summary["extra_feeds"]:
        lines.append(f"- **Extra feeds · 自定义订阅**: {len(summary['extra_feeds'])} added")
    if summary["interests"]:
        lines.append(f"- **Interests · 兴趣词**: {', '.join(summary['interests'][:8])}")
    if summary.get("update_freq"):
        _freq_label = {"2h": "every 2 hours · 每2小时",
                       "3x": "3×/day · 每天3次",
                       "daily": "once a day · 每天1次"}.get(
                           summary["update_freq"], summary["update_freq"])
        lines.append(f"- **Update frequency · 更新频率**: `{summary['update_freq']}` ({_freq_label})")
    if warnings:
        lines += ["", "### ⚠️ Notes"] + [f"- {w}" for w in warnings]

    lines += [
        "",
        "A rebuild is running: "
        f"[Actions → Update Relevance](https://github.com/{repo}/actions/workflows/update.yml)",
        "",
        "## Next steps · 后续步骤", "",
        f"1. **Enable GitHub Pages** (once): [Settings → Pages](https://github.com/{repo}/settings/pages)"
        " → *Deploy from a branch* → `main` / `/ (root)`."
        f" Your site · 你的网站: {site_url}",
    ]
    step = 2
    if private:
        lines += [
            f"{step}. 🔴 **REQUIRED — add the `NEWSDASH_PASSPHRASE` secret** "
            f"([add secret](https://github.com/{repo}/settings/secrets/actions/new)). "
            "Your site is set to *private*: without the passphrase the build refuses to publish. "
            "Pick ≥4 random words and keep them safe — the passphrase is also your login. "
            "私密模式必需：请添加口令 Secret（≥4 个随机单词），它同时也是你的登录口令。",
        ]
        step += 1
    lines += [
        f"{step}. **Or let AI walk you through it** — open this repo in Claude Code / Codex and paste: "
        "更推荐让 AI 带你配置——在 Claude Code 里粘贴：",
        "",
        "   > Use the Page Skill (书童Skill) in this repo. Interview me about my news sources "
        "and academic fields; update config/ for me; then guide me through "
        "adding each GitHub Secret myself. Never ask me to paste secret values into chat, and "
        "never commit URLs that contain tokens.",
        "",
        "Full walkthrough · 完整教程: "
        f"[docs/SETUP.md](https://github.com/{repo}/blob/main/docs/SETUP.md) · "
        f"[中文](https://github.com/{repo}/blob/main/docs/SETUP.zh.md)",
    ]
    return "\n".join(lines) + "\n"


def error_comment(message: str) -> str:
    return (
        "## ❌ Setup not applied · 配置未应用\n\n"
        f"{message}\n\n"
        "Edit this issue to fix the problem — the bot re-runs on every edit. "
        "修改本 Issue 后机器人会自动重试。\n"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--comment-out", required=True)
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--repo-root", default=None)
    args = ap.parse_args()

    repo_root = Path(args.repo_root) if args.repo_root \
        else Path(__file__).resolve().parent.parent
    body = Path(args.body_file).read_text(encoding="utf-8")

    try:
        summary, warnings = apply_any(body, repo_root)
    except (ValueError, ConfigError, json.JSONDecodeError) as exc:
        Path(args.comment_out).write_text(error_comment(str(exc)), encoding="utf-8")
        print(f"::error::setup rejected: {exc}")
        sys.exit(2)

    comment = (success_comment_source if summary.get("kind") == "source"
               else success_comment)(summary, warnings, args.repo)
    Path(args.comment_out).write_text(comment, encoding="utf-8")

    # Surface the chosen update cadence to the workflow, which sets the
    # NEWSDASH_UPDATE_FREQ repo Variable. Value is whitelisted (2h|3x|daily);
    # an empty/absent selection writes nothing, so the workflow skips the
    # variable step and the current cadence is left untouched.
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output and summary.get("update_freq"):
        with open(gh_output, "a", encoding="utf-8") as fh:
            fh.write(f"update_freq={summary['update_freq']}\n")

    print(f"applied: {json.dumps({k: v for k, v in summary.items() if k != 'entry'}, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
