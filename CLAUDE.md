# CLAUDE.md

Relevance (及君): serverless news · research dashboard template —
Python pipeline on Actions cron → static JSON in `data/` → vanilla-JS site on
GitHub Pages. Private sections are AES-256-GCM encrypted; the passphrase is the login.
Formerly "Personal Newsdash" — renamed 2026-07-08; internal identifiers
(folders `scripts/newsdash/`/`skills/newsdash/`, the `newsdash` Python
package, GitHub Secret/Variable names like `NEWSDASH_PASSPHRASE`, the
`newsdash-setup` label) deliberately kept the old name — see "Update
workflow" below for why.

## This repo's role: the public template

This repo (`PleiadesM/Personal_Newsdash`) is the **public-facing template**,
aimed at a generic audience who might fork/use it themselves. Its product
name/branding is **Relevance (及君)** as of 2026-07-08 — the repo itself
(folder name, GitHub repo name, Pages URL) was deliberately **not** renamed
in that pass, only user-facing text (README, site title, UI strings, docs
prose). If a future session renames the repo/URL too, update this note.

There is a **sibling private repo**, `PleiadesM/Apropos_PleiadesM`
(`~/Documents/GitHub/Apropos_PleiadesM`), forked from this one at commit
`fb76545` (2026-07-08). That repo is the owner's actual personal deployment:
it will carry private sources/config this public template deliberately
does not (more personal notes/sources), and its site visibility
is meant to move to `private` (passphrase-gated) as that content is added.
The two repos will diverge over time — **don't assume a fix or feature made
in one has been ported to the other**; check before assuming parity, and
port hard rules / crypto / security fixes across manually since there's no
automated sync between them.

## Update workflow (public ⇄ private)

Every round of updates across these two repos starts in **plan mode**.
Before finalizing the plan, confirm with the user which mode applies this
round and what the round's goal is — write both at the very top of the
plan document.

Three standard modes (default; an explicit user-specified scope for a
given round overrides them):

1. **Both repos** — the change is needed in both `Personal_Newsdash`
   (public) and `Apropos_PleiadesM` (private). **Start with the private
   repo**: implement and test the change there first, then port it to the
   public repo. Never the other direction — the private repo can carry
   real/private test data and is where regressions are cheapest to catch.
2. **Public only** — the change belongs only to `Personal_Newsdash` (e.g.
   the rebrand, generic template features aimed at external forkers). Do
   not port it to the private repo unless asked.
3. **Private only** — the change belongs only to `Apropos_PleiadesM` (e.g.
   wiring a new private source, personal config, passphrase/visibility
   settings). Do not port it to the public repo.

## First reads

- `README.md` — product + architecture overview
- `skills/newsdash/SKILL.md` — the Page Skill｜书童Skill (maintainer workflows; follow it for any source/config/secrets task)
- `docs/DATA_CONTRACT.md` — pipeline ⇄ frontend interface (manifest, payload schemas, crypto envelope)
- `docs/CONFIG_REFERENCE.md` — every config key; "change X → edit Y"

## Validate

```bash
python -m pytest -q                                    # unit tests (offline)
python scripts/validate_config.py                      # config schema + semantics
python scripts/build.py --output-dir /tmp/nd --smoke   # no-network end-to-end
node tests/test_crypto_webcrypto.mjs                   # crypto envelope cross-check
```

## Hard rules

- Never commit or log: the passphrase, tokens, capability URLs (they are
  credentials), or decrypted private payloads. Actions logs on public repos
  are public — never print private counts/titles/details.
- Never weaken crypto parameters (`scripts/newsdash/crypto.py`) or add a
  plaintext fallback for private sections. The envelope is pinned by
  `tests/test_crypto_webcrypto.mjs`.
- Never remove the owner guard in `.github/workflows/setup-from-issue.yml`,
  nor the schema rule forbidding `url`/`path` on private sources.
- Keep the zero-secret build green: new sources must skip cleanly when their
  secrets are absent (`enabled: "auto"` + `secret_ref`).
- `data/` is bot-owned output — don't hand-edit it.
