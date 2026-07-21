# Priority interview — tune what floats to the top

This is **step 3** of the guided setup workflow (Studio → test & report →
**priority** → categories). Once the sources exist and are healthy, this step
makes the dashboard feel like *theirs*: interview the owner about what they
care about, then map the answers onto three existing config knobs plus one
homepage-variety knob.

You are tuning a **heuristic** ranker — zero LLM calls. Read
`scripts/newsdash/scoring.py` (`score_item()`) before you promise anything, so
your guidance matches the real formula:

```
news item      score = 0.45·recency + 0.35·keyword-relevance + 0.20·source-weight
cited paper    score = 0.35·recency + 0.25·keyword-relevance + 0.15·weight + 0.25·citations
```

- **recency** decays with a half-life (news ~12h, papers ~84h) — you cannot
  tune it from config, only offset it with weight/keywords.
- **keyword-relevance** = `min(1.0, 0.4·(#interest keywords that match title+summary) + boost)`.
  One matched keyword already lands `0.4 + boost`; matches saturate at `1.0`.
- **source-weight** is the per-source `weight` (0–1); it is a steady thumb on
  the scale for a trusted feed, independent of any keyword.

So the three levers are `interests.keywords`, `interests.boost` (both in
`config/sources.json`), and per-source `weight`. The fourth knob, `ranking`
(in `config/site.json`), shapes the homepage **Highlights** block, not scores.

## (a) Guiding questions

Ask one topic at a time — don't dump the whole list. Read their current
`config/sources.json` `interests` and each source's `weight` first so you can
frame questions against what's already there.

1. **Topics.** "When you skim the dashboard, which 5–10 words or phrases make
   you stop and read?" → candidate `interests.keywords`. Push for concrete
   nouns (`diffusion models`, `Taiwan`, `RNA`), not vibes.
2. **Recency vs. relevance.** "If a highly on-topic piece is three days old and
   a lukewarm one is an hour old, which do you want up top?" Recency-first →
   keep `boost` low, weights modest. Relevance-first → raise `boost` and lean
   on keywords/weight to overcome the recency decay.
3. **Most-trusted sources.** "Which 2–3 feeds would you never want buried?" →
   raise their `weight` toward `1.0`.
4. **Least-trusted / noisy sources.** "Which feeds are worth keeping but
   usually noise?" → lower their `weight` (`0.3–0.5`) rather than dropping them.
5. **Homepage feel.** "Should the top of the page be a mix across everything,
   or go straight into the top news?" and "Does one chatty feed tend to hog
   the front page?" → drives `ranking.highlights` and `ranking.max_per_source`.

## (b) Mapping table

| They said… | Config key | File | Sane range |
|---|---|---|---|
| "I care about X, Y, Z" | `interests.keywords` | `config/sources.json` | 5–15 concrete terms; more just dilutes |
| "Relevance should beat freshness" | `interests.boost` | `config/sources.json` | `0.0`–`0.5` (default `0.15`); >`0.5` makes any single match dominate |
| "Never bury this feed" | source `weight` | `config/sources.json` | `0.8`–`1.0` |
| "Keep it but it's noisy" | source `weight` | `config/sources.json` | `0.3`–`0.5` |
| "Show a mixed front block / don't" | `ranking.highlights` | `config/site.json` | `true` / `false` |
| "One feed hogs the front page" | `ranking.max_per_source` | `config/site.json` | `1`–`3` (lower = more diverse) |

Notes:
- `keywords` are matched **case-insensitively** as substrings of title +
  summary, so `gpt` also fires inside `GPT-5`. Keep them short and specific.
- `boost` is global, not per-keyword. It lifts *every* keyword match, so treat
  it as the single "how much does relevance matter" dial. Staying in `0–0.5`
  keeps recency and weight meaningful; the schema does not cap it, judgment does.
- **Preset source weights are overridden by id**, never edited in the pack:
  add `{"id": "<same-id>", "weight": 0.4}` to `sources[]`.

### The `ranking` knob (homepage variety)

`ranking` lives in `config/site.json` alongside `windows`:

```json
"ranking": { "highlights": true, "max_per_source": 2 }
```

- `highlights` (default `true`) — show the mixed **Highlights** block at the
  top of the Today page: the highest-scored items pooled across *all loaded*
  content sections (news- and papers-kind, including custom sections), so a
  new deployer sees a lively front page even before they've read the formula.
  `false` hides the block entirely (Top Stories then leads).
- `max_per_source` (default `2`, minimum `1`) — the diversity cap: at most this
  many items from any one `source_id` may appear in Highlights. Lower it to `1`
  when a single prolific feed keeps crowding out everything else; raise it if
  the owner wants a couple of trusted sources to carry the block.

The block only renders when at least 3 items survive the cap, and it never
touches locked/private sections — it reads only already-loaded content.

## (c) Apply procedure

1. Edit `config/sources.json` (`interests`, per-source `weight` overrides) and
   `config/site.json` (`ranking`). Preserve `$schema`, `schema_version`,
   `presets`, and `tag_rules`.
2. Validate the shape and semantics:
   ```bash
   python scripts/validate_config.py
   ```
3. Smoke-build and sanity-read the resulting ordering — this exercises the real
   scorer with no network:
   ```bash
   python scripts/build.py --output-dir /tmp/nd --smoke
   ```
   In `--smoke` the feeds are empty, so also do a **live** build (or read the
   deployed `data/news.json` / `data/papers.json`) and eyeball the top items:
   are the owner's keywords and trusted sources actually surfacing? If not,
   nudge `boost` or the relevant `weight` and rebuild. Confirm the
   `ranking` block in `/tmp/nd/manifest.json` matches what you set.
4. Show the owner the before/after top-of-feed ordering and confirm before
   committing.

After priority is dialed in, move on to **step 4 — categories**: propose nav
tabs (sections) and assign sources.
