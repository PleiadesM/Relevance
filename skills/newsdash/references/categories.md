# Categories — custom nav tabs

This is **step 4** of the guided setup workflow (Studio → test & report →
priority → **categories**). By now the sources exist, are healthy, and are
ranked the way the owner likes. This last step gives the dashboard its shape:
group the sources into a handful of named nav tabs (sections) with friendly
**bilingual** labels, instead of everything landing in the default `news` /
`papers` tabs.

A "category" here is just a **section** — the same `section` field you already
set per source in the Studio (step 1). What this step adds is the *metadata* for
those sections: a bilingual `label`, an optional display `order`, and (custom
sections only) an optional `kind` override. That metadata lives in
`config/site.json` under `sections[]`; the section itself is created simply by
one or more sources pointing their `section` at it.

Zero LLM calls, zero new machinery — custom sections already build and route.
You are only naming and ordering them.

## (a) Clustering existing sources into tabs

Read the current `config/sources.json` (`sources[]` + the merged presets) and
look at each source's `section`, `type`, and topic. Propose tabs by grouping
sources that belong together:

- **By topic** — an owner following several AI feeds plus an arXiv `cs.CL`
  query wants an `ai` tab; climate feeds want a `climate` tab.
- **By type** — news-like feeds read chronologically (`kind: "news"`);
  paper-like feeds (arXiv/OpenAlex/CrossRef) read impact-first
  (`kind: "papers"`).

Rules of thumb:

- Keep it to **4–7 tabs**. More fragments the feed and leaves half-empty tabs.
- The built-ins **`news`** and **`papers`** stay as-is — they are good default
  homes and you may not override their `kind`.
- A tab only appears when at least one source points its `section` at it. A
  metadata entry for a section with no sources is silently ignored.
- Private sources stay in the **`private`** section (the encrypted, gated tab).
  Never move a private source into a public custom tab.

## (b) The proposal — show the owner before applying

Present a small table and confirm before editing anything:

| Tab id | en label | zh label | Sources moving in | kind |
|---|---|---|---|---|
| `ai` | AI | AI 前沿 | `openai_blog`, `arxiv_cs_cl`, `hf_papers` | news |
| `climate` | Climate | 气候 | `carbon_brief`, `iea_news` | news |
| `papers` | (built-in) | (built-in) | `arxiv_stat`, `openalex_hci` | papers |

Say plainly which sources leave their current tab and where they land, and
what the tab bar will read in each language.

## (c) Apply procedure

1. In `config/sources.json`, set `section` on each source that is moving
   (Studio step 1's assignment; override preset sources by id, never edit the
   pack). Preserve `$schema`, `schema_version`, `presets`, `interests`,
   `tag_rules`.
2. In `config/site.json`, add a `sections[]` array of metadata objects:
   ```json
   "sections": [
     { "id": "ai", "label": { "en": "AI", "zh": "AI 前沿" }, "order": 1, "kind": "news" },
     { "id": "climate", "label": { "en": "Climate", "zh": "气候" }, "order": 2 }
   ]
   ```
   `order` and `kind` are optional; `label` needs at least one of `en`/`zh`
   (give both). This block sits alongside `windows` and `ranking`.
3. Validate — schema + semantics (duplicate ids, kind-on-builtin, label
   shape):
   ```bash
   python scripts/validate_config.py
   ```
   The `sections:` line now prints each tab with its label, e.g.
   `ai ("AI"), climate ("Climate")`.
4. Smoke-build and confirm the manifest carries the metadata:
   ```bash
   python scripts/build.py --output-dir /tmp/nd --smoke
   ```
   Check `/tmp/nd/manifest.json`: each custom section's entry has a
   `label` object and the right `kind`, and ordered sections sort ahead of
   unordered ones (unordered keep their relative position after them).
5. Preview the site and read the tab bar in both languages (toggle 中文/EN).
   The nav shows `label[lang]` (falling back en→zh, then the raw id). Confirm
   with the owner before committing.

## (d) Rules

- **ids** are a lowercase slug, `^[a-z0-9_-]{2,32}$` — same pattern as a
  source's `section`.
- Give **both** `en` and `zh` labels whenever you can; the nav falls back
  `label[lang] → en → zh → id`, so a missing label just shows less-localized
  text, never breaks.
- **`kind` override** (`"news"` / `"papers"`) is for **custom sections only**
  — it picks news-like (chronological) vs papers-like (impact-first, with
  authors/venue) rendering. It is **rejected on the built-ins**
  (`news`/`papers`/`following`/`private`) so it can never redirect the
  private-section pipeline. Omit it to inherit the default (`news`).
- `order` is any integer; lower sorts first. Sections without `order` keep
  their config/source order, after the ordered ones.
- **Labels are public plaintext in the manifest** — the manifest is readable
  before login even on a private site. Never put private, secret, or
  identifying information in a label.
- Private sources stay in the `private` section. Do not give the `private`
  section a custom `kind`, and never route a `secret_ref` source into a
  public tab.
