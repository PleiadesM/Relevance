# Secrets setup recipes (narrate these — never handle values)

All secrets go to: `https://github.com/<owner>/<repo>/settings/secrets/actions/new`
Variables go to the *Variables* tab on the same page.

## NEWSDASH_PASSPHRASE

- Recommend ≥ 4 random words (e.g. diceware). It is both the encryption key
  source and the site login. There is **no recovery**: lost passphrase =
  private history in git stays sealed.
- Rotation: update the secret → `gh workflow run update.yml`. Old ciphertext
  remains in git history (see SECURITY_MODEL §rotation).

## LLM_API_KEY + SMITHSONIAN_API_KEY (optional AI daily brief + Apropos-of-Nothing + Today's Image)

Off by default — nothing changes until the user adds `LLM_API_KEY`. Explain
before narrating: this is the *only* feature that sends any of the user's
content (news/paper titles + short summaries — never private-section content,
never the passphrase) to a third-party endpoint the user chooses, once per
scheduled build (never per visitor). Get informed opt-in before walking
through it.

1. **`LLM_API_KEY`** (secret) — any OpenAI-Chat-Completions-compatible
   provider key: OpenAI, OpenRouter, Groq, Together, or a self-hosted
   endpoint. This alone unlocks the AI daily brief, per-section summaries,
   and Apropos-of-Nothing card on the Today page.
2. **`LLM_BASE_URL`** / **`LLM_MODEL`** (variables, optional) — only needed
   if not using OpenAI directly. Defaults: `https://api.openai.com/v1`,
   `gpt-4o-mini`.
3. **`SMITHSONIAN_API_KEY`** (secret, optional, requires `LLM_API_KEY` too)
   — unlocks "Today's Image". Free key: user visits
   `https://api.data.gov/signup/`, fills in name + email, gets a key by
   email immediately (one key works across every api.data.gov API,
   Smithsonian's Open Access API included).
4. **`LLM_SUMMARY_ENABLED=0`** / **`TODAYS_IMAGE_ENABLED=0`** /
   **`APROPOS_OF_NOTHING_ENABLED=0`** (variables) — emergency stop for an
   AI feature without removing the key.

## Optional

- `OPENALEX_API_KEY` (secret) — makes the OpenAlex fetcher reliable.
- `FOLLOW_OPML_B64` (secret) — base64 of a private OPML file.
- `CONTACT_MAILTO` (variable) — any email; joins CrossRef/OpenAlex polite pools.
- `<UPPERCASED_SOURCE_ID>_ENABLED=0` (variable) — emergency stop for a source.

## Verify after each secret

```bash
gh workflow run update.yml && gh run watch
curl -s https://<owner>.github.io/<repo>/data/manifest.json | python3 -m json.tool
# the section's "status" flips from "not_configured" to "ok"
```

Sources with `enabled: "auto"` turn on the moment every env var in their
`secret_ref` exists — no config edit needed.
