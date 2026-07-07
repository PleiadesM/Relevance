#!/usr/bin/env python3
"""Regenerate assets/js/i18n-fallback.js from i18n/en.json.

Run after any edit to i18n/en.json; tests/test_i18n_fallback.mjs fails CI
when the two drift apart.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HEADER = (
    "// GENERATED from i18n/en.json — do not edit by hand.\n"
    "// Regenerate: python3 scripts/gen_i18n_fallback.py\n"
    "// Purpose: the network copies of i18n/*.json can fail behind a flaky\n"
    '// CDN; this embedded English dictionary guarantees the chrome never\n'
    '// renders raw keys like "app.tagline". Parity with en.json is pinned\n'
    "// by tests/test_i18n_fallback.mjs.\n\n"
)


def main() -> None:
    with open(ROOT / "i18n" / "en.json", encoding="utf-8") as fh:
        data = json.load(fh)
    body = json.dumps(data, ensure_ascii=False, indent=2)
    out = ROOT / "assets" / "js" / "i18n-fallback.js"
    out.write_text(HEADER + f"export const FALLBACK_EN = {body};\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
