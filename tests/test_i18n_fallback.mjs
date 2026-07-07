// Pins assets/js/i18n-fallback.js to i18n/en.json: the embedded fallback
// must stay byte-identical in content to the fetched dictionary, or the
// "CDN failed" degraded mode would silently show stale strings.
// Run: node tests/test_i18n_fallback.mjs   (regenerate with
// python3 scripts/gen_i18n_fallback.py after editing en.json)

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const enJson = JSON.parse(readFileSync(join(root, "i18n/en.json"), "utf8"));
const { FALLBACK_EN } = await import(
  new URL(`file://${join(root, "assets/js/i18n-fallback.js")}`).href
);

const a = JSON.stringify(enJson);
const b = JSON.stringify(FALLBACK_EN);
if (a !== b) {
  console.error(
    "FAIL: assets/js/i18n-fallback.js is out of sync with i18n/en.json.\n" +
    "Run: python3 scripts/gen_i18n_fallback.py"
  );
  process.exit(1);
}
console.log("OK i18n fallback matches en.json");
