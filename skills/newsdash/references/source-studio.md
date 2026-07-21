# Source Studio — the offline source editor

`scripts/build_source_studio.py` generates a **self-contained HTML page** where
the deployer curates their sources by hand — add/remove/edit feeds, set each
public or private, pick a friendly *kind*, tune weights — and then hands the
result back to you as a plan you apply to `config/sources.json`.

It is **step 1** of the guided setup workflow (Studio → test & report →
priority → categories).

## Launch

```bash
python scripts/build_source_studio.py           # writes newsdash-studio/source-studio.html
```

The page and the plan it emits live under `newsdash-studio/` (or `--output-dir`),
which is **gitignored** — they never leave the deployer's machine. Tell the user
to open the file in a browser (the page matches their site's language,
Relevance / 及君), edit, then **Save / Copy** the plan.

## Friendly kind → backend mapping

The Studio speaks in plain "kinds"; on save it resolves each to the real
config `type` + `category` + a suggested `section`:

| Kind | `type` | `category` | default `section` | primary input |
|------|--------|------------|-------------------|---------------|
| News | `rss` | open | `news` | feed/page URL |
| Blog | `rss` | open | `news` | feed URL |
| YouTube | `rss` | open | `news` | `youtube.com/feeds/videos.xml?channel_id=…` |
| Podcast | `rss` | open | `news` | podcast RSS URL |
| Social | `rss` | open | `following` | Mastodon/other `.rss` URL |
| Scholar (follow) | `openalex` | optional | `following` | OpenAlex author id (`A…`) or query |
| Journal | `crossref` | optional | `papers` | ISSN(s) |
| Topic / arXiv | `arxiv` | optional | `papers` | arXiv query (`cat:cs.CL`) |
| **Private feed** | `rss` | **private** | `private` | **a Secret NAME only** |
| Advanced | (chosen) | open | `news` | url / query |

**Private is the hard line:** a private row shows a *Secret name* field, never
a URL. The plan therefore carries `secret_ref: ["SRC_<ID>_URL"]` and **no
`url`/`path`** for private sources — the capability URL only ever lives in the
GitHub Secret the user adds themselves (see `references/secrets-setup.md`).

## Handoff — how the plan reaches you

The Studio offers three routes (same JSON in each):

1. **Save to working folder** — File System Access API (Chrome/Edge): the user
   saves `sources.plan.json` into `newsdash-studio/`. Read it from there.
2. **Copy for agent** — copies the JSON; the user pastes it into chat.
3. **Download JSON** — fallback for browsers without the save picker.

## Plan format — `newsdash-source-plan/v1`

```json
{
  "schema": "newsdash-source-plan/v1",
  "presets": ["ai-news", "general-news"],
  "interests": { "keywords": ["…"], "boost": 0.15 },
  "sources": [
    { "id": "feifei_li", "category": "open", "type": "rss", "section": "news",
      "name": "Dr. Fei-Fei Li", "url": "https://…/feed", "weight": 1.0 },
    { "id": "my_private_feed", "category": "private", "type": "rss",
      "section": "private", "name": "My private feed",
      "enabled": "auto", "secret_ref": ["SRC_MY_PRIVATE_FEED_URL"] }
  ]
}
```

`sources` is the **complete desired** custom-source list (config `sources[]`).
Anything the user removed is simply absent. `presets` and `interests` are
carried through so applying the plan never drops them.

## Applying a plan — the safe procedure

1. Read the plan from `newsdash-studio/sources.plan.json` (or the pasted JSON).
   Reject anything whose `schema` is not `newsdash-source-plan/v1`.
2. **Capability-URL gate.** For every source carrying a `url`, confirm it is a
   plain public feed — pass it through `scripts/discover_source.py` (it exits 3
   on a capability URL). If one trips the gate, do **not** store the URL:
   reclassify that source as `private` (`category: "private"`, drop `url`, add a
   `secret_ref`) and switch to the private protocol in `SKILL.md`. Also check
   every `secret_ref` value is an `UPPER_SNAKE` **name** (`^[A-Z][A-Z0-9_]{1,63}$`)
   — if a value looks like a URL or token, it is a mis-entered credential: do not
   store it, and tell the user to rotate it. (The Studio refuses to emit such a
   plan, but verify anyway — the user may hand-edit the JSON.)
3. Write `plan.sources` into `config/sources.json` `sources`, set `presets`,
   and **preserve** `$schema`, `schema_version`, `interests`, and `tag_rules`.
4. `python scripts/validate_config.py` — fix anything it flags.
5. Confirm the diff with the user before committing. Never commit
   `newsdash-studio/` or a plan file (they are gitignored for a reason).

After the plan is applied, move on to **step 2 — test & report** to health-check
the sources and get weight/dedupe recommendations.
