Hi — lovely project. I forked it, turned on `visibility: "private"`, and added
per-article bodies on top, and hit a growth problem that traces back to two
lines here. It is **latent on the default public visibility**, which is why it
has not surfaced, so this is a "you'd hit it the day someone flips that flag"
report rather than a bug you have today.

## The problem

In private mode every build re-encrypts **every** file even when its plaintext
is identical, so git stores a full new blob for the whole published tree on
every scheduled run. Ciphertext neither compresses nor deltas, so the repo
grows by roughly the size of `data/` per run.

Your own history is the evidence that public mode is fine: 195
`chore: update newsdash data` commits in ~7 MB, about **37 KB per commit** —
plaintext JSON delta-compresses beautifully. Flip one config value and that
number becomes the size of `data/`.

## Reproducing on `main` (f54474e)

Change only `config/site.json` → `"visibility": "private"`, then:

```bash
export NEWSDASH_PASSPHRASE='four random words here'
python scripts/build.py --output-dir out --smoke   # 1st
# commit out/ somewhere
python scripts/build.py --output-dir out --smoke   # 2nd, identical input
```

`--smoke` fetches nothing, so the two builds have byte-identical *content*.
git still reports all five encrypted files as modified.

## Cause

1. **`scripts/build.py`** — `salt = crypto.new_salt()` runs every build. A new
   salt means a new derived key, so every payload re-encrypts to different
   bytes regardless of whether its plaintext changed.
2. **`scripts/build.py`** — `shutil.rmtree(out_dir / ARTICLE_ROOT)` deletes and
   rebuilds the article tree, so every surviving article file is re-encrypted
   too. Cheap today (only entries with substantial `content:encoded` produce
   article files — ~13% of entries across a 30-source set I measured), but it
   scales directly with that fraction.

Measured on my fork, per build: **104 files touched / 1229 KB of new git
objects → 8 files / 219 KB.**

## What this PR does

- **Salt per deployment, not per run.** `crypto.reusable_salt` returns the
  previous salt while the current passphrase still opens
  `manifest.crypto.check`, and `None` otherwise — so a first build and a
  passphrase rotation both re-salt naturally.

  I want to be explicit that this is not a weakening, since it touches crypto:
  a salt exists so that one precomputation cannot attack many passphrases, and
  it is public in the manifest either way — one deployment with one passphrase
  legitimately has one salt. What must never repeat under a given key is the
  **nonce**, and every `encrypt_bytes` call still draws a fresh random one.
  There is a test that a rotated passphrase re-salts and re-encrypts everything.

- **Incremental article tree.** Each article file carries a content hash in its
  `meta`; an unchanged article is left untouched on disk; files that no longer
  back a live item are swept afterwards instead of up front.

  One subtlety worth knowing if you touch this: the hash must exclude
  `item.score`. Recency decay changes it on every build, so hashing the full
  item makes the check never fire — I hit exactly that. It is an explicit
  allowlist of stable fields rather than "`to_dict()` minus score", so a future
  volatile field cannot reintroduce the bug silently.

- **Memoized key derivation.** `decrypt_envelope` ran a 600k-iteration PBKDF2
  per envelope, and every file one build writes shares one salt — so reading a
  tree of ~200 article files burned ~25 s of CPU deriving the same key 200
  times, on the critical path.

## Scope and honesty

- 303 tests pass (your 296 plus 7 new).
- No behaviour change in public mode, no config from my deployment, nothing
  else touched.
- **Known remaining churn, deliberately out of scope:** section payloads still
  change every run because `meta.generated_at` does, and in a real build
  because item scores decay. This PR targets the article tree, which is where
  the bulk is.

Happy to split this into two PRs (salt / article tree) if you would rather
review them separately, or to drop it entirely if you would prefer to solve it
a different way — you know the threat model here better than I do.

For what it is worth: the candour in `SECURITY_MODEL.md` about what encryption
does and does not buy you is rarer than it should be, and it is why I trusted
the project enough to build on it.
