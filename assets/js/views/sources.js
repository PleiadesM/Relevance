// Source health table (radar tradition): who's delivering, who's failing,
// who's still waiting for secrets. Below it, an "Add a source" panel that
// hands the deployer a ready-to-paste Page-Skill prompt (and an optional
// GitHub-issue shortcut). Private sources take a nickname only — never a
// URL or token — so nothing sensitive can leak into chat or a public issue.

import { clear, el } from "../dom.js";
import { t } from "../i18n.js";
import { get } from "../store.js";
import { emptyCard, lockedCard, repoUrl } from "./shared.js";

function statusLabel(entry) {
  if (entry.skip_reason === "disabled") return ["disabled", t("sources.disabled")];
  if (entry.skip_reason === "not_configured") return ["skipped", t("sources.skipped")];
  if (entry.ok) return ["ok", t("sources.ok")];
  return ["failed", `${t("sources.failed")}${entry.error ? ` (${entry.error})` : ""}`];
}

function renderHealth(container) {
  const { sourceStatus, manifest, unlocked } = get();
  if (!sourceStatus) {
    if (manifest?.source_status_file?.endsWith(".enc.json") && !unlocked) {
      container.appendChild(lockedCard());
    } else {
      container.appendChild(emptyCard());
    }
    return;
  }

  container.appendChild(el("h3", {}, t("sources.title")));

  const rows = sourceStatus.sources || [];
  const table = el("table", { class: "sources-table" },
    el("thead", {}, el("tr", {},
      el("th", {}, t("sources.name")),
      el("th", {}, t("sources.type")),
      el("th", {}, t("sources.category")),
      el("th", {}, t("sources.status")),
      el("th", { class: "num" }, t("sources.fullText")),
      el("th", { class: "num" }, t("sources.items")),
    )),
    el("tbody", {}, rows.map((entry) => {
      const [cls, label] = statusLabel(entry);
      return el("tr", { class: `status-${cls}` },
        el("td", {}, entry.name),
        el("td", {}, entry.type),
        el("td", {}, t(`sources.categories.${entry.category}`)),
        el("td", {}, label),
        el("td", { class: "num" },
          entry.full_text_count ? t("sources.fullTextCount", { n: entry.full_text_count }) : "—"),
        el("td", { class: "num" }, entry.skip_reason ? "—" : String(entry.count)),
      );
    })),
  );
  container.appendChild(table);

  const priv = sourceStatus.private_summary;
  if (priv?.total) {
    container.appendChild(el("p", { class: "muted" },
      t("sources.privateSummary", { configured: priv.configured, total: priv.total })));
  }
}

// ---- add-a-source panel --------------------------------------------------

const KINDS = ["rss", "scholar", "journal", "private"];
const addState = { kind: "rss", input: "" }; // module-level, like other views

function renderAddPanel(panel) {
  clear(panel);
  const { kind, input } = addState;

  panel.appendChild(el("h3", {}, t("sources.add.title")));

  // kind picker — the .seg segmented idiom (see feed.js)
  const seg = el("div", { class: "seg", role: "group" });
  for (const k of KINDS) {
    const btn = el("button", {
      type: "button",
      class: k === kind ? "active" : "",
      onclick: () => { addState.kind = k; renderAddPanel(panel); },
    }, t(`sources.add.kind.${k}`));
    btn.dataset.value = k;
    seg.appendChild(btn);
  }
  panel.appendChild(seg);

  // single text input; for "private" this is a NICKNAME only, never a URL
  panel.appendChild(el("input", {
    type: "text",
    class: "add-source-input",
    placeholder: t(`sources.add.ph.${kind}`),
    value: input,
    oninput: (e) => { addState.input = e.target.value; updateDerived(); },
  }));

  // private kind always carries the "never paste the URL" warning
  if (kind === "private") {
    panel.appendChild(el("p", { class: "muted warn" }, t("sources.add.privateWarning")));
  }

  // generated Page-Skill prompt (read-only, copyable)
  panel.appendChild(el("label", { class: "add-source-label" }, t("sources.add.promptLabel")));
  const promptBox = el("textarea", { class: "prompt-box", readonly: "", rows: "5" });
  panel.appendChild(promptBox);

  const copyBtn = el("button", {
    type: "button", class: "secondary",
    onclick: () => {
      navigator.clipboard.writeText(promptBox.value).then(() => {
        copyBtn.textContent = t("sources.add.copied");
        setTimeout(() => { copyBtn.textContent = t("sources.add.copy"); }, 1500);
      });
    },
  }, t("sources.add.copy"));
  panel.appendChild(copyBtn);

  // optional GitHub-issue shortcut (only when we know the deployer's repo)
  const repo = repoUrl();
  let issueLink = null;
  if (repo) {
    issueLink = el("a", {
      class: "doc-link", target: "_blank", rel: "noopener",
    }, t("sources.add.issueLink"));
    panel.appendChild(issueLink);
  }

  // recompute prompt text + issue href from live input. Private input is a
  // nickname; it (and any URL-ish value) is NEVER placed in the issue link.
  function updateDerived() {
    const val = addState.input;
    promptBox.value = t(`sources.add.prompt.${addState.kind}`, { input: val || "…" });
    if (issueLink) {
      let href = `${repo}/issues/new?template=add-source.yml&labels=newsdash-source`;
      if (addState.kind !== "private" && val) {
        href += `&name=${encodeURIComponent(val)}`;
      }
      issueLink.href = href;
    }
  }
  updateDerived();
}

export function render(container) {
  clear(container);
  renderHealth(container);
  const panel = el("section", { class: "add-source" });
  container.appendChild(panel);
  renderAddPanel(panel);
}
