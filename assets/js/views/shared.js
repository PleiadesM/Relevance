// Small shared state cards (locked / empty / error / not-configured).

import { el } from "../dom.js";
import { t } from "../i18n.js";

export function lockedCard() {
  return el("div", { class: "state-card locked-card" },
    el("p", {}, "🔒 ", t("today.lockedBlock")),
    el("button", {
      onclick: () => document.dispatchEvent(new CustomEvent("nd:unlock-request")),
    }, t("login.unlock")),
  );
}

export function notConfiguredCard() {
  return el("div", { class: "state-card" },
    el("p", {}, t("app.notConfigured")),
    el("p", { class: "muted" }, t("app.notConfiguredHint")),
    el("a", {
      class: "doc-link", target: "_blank", rel: "noopener",
      href: "https://github.com/#setup-guide",
      dataset: { repoDoc: "docs/SETUP.md" },
    }, t("app.setupGuide")),
  );
}

export function emptyCard() {
  return el("div", { class: "state-card" }, el("p", { class: "muted" }, t("app.empty")));
}

export function errorCard() {
  return el("div", { class: "state-card" }, el("p", { class: "muted" }, t("app.error")));
}

// Point doc links at the deployer's own repo when the site runs on
// <owner>.github.io/<repo>; generic fallback otherwise (custom domains).
export function fixDocLinks(root) {
  const match = window.location.hostname.match(/^([\w-]+)\.github\.io$/);
  if (!match) return;
  const repo = window.location.pathname.split("/")[1];
  if (!repo) return;
  for (const link of root.querySelectorAll("a[data-repo-doc]")) {
    link.href = `https://github.com/${match[1]}/${repo}/blob/main/${link.dataset.repoDoc}`;
  }
}

// The deployer's repo root URL, derived like fixDocLinks() from the GitHub
// Pages origin; null when not on a *.github.io host (custom domains).
export function repoUrl() {
  const match = window.location.hostname.match(/^([\w-]+)\.github\.io$/);
  if (!match) return null;
  const repo = window.location.pathname.split("/")[1];
  if (!repo) return null;
  return `https://github.com/${match[1]}/${repo}`;
}

// Tab bar for a merged page. Plain anchors so deep-linking and rerender
// come free via the existing hashchange handler.
export function tabBar(pageId, tabs, activeId) {
  return el("nav", { class: "tabs" }, tabs.map(([id, label]) =>
    el("a", { href: `#/${pageId}/${id}`, class: id === activeId ? "active" : "" }, label)));
}
