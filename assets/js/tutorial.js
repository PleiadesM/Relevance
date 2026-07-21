// First-deploy tutorial: a one-time, multi-slide welcome shown after the
// site's first successful load. Presents setup as a to-do checklist with deep
// links into the deployer's OWN repo (Issues, Secrets, the Page Skill). Reuses
// the modal shell (.modal-backdrop/.modal) and the nd.* prefs store; links are
// derived solely from the Pages origin via repoUrl() — never from any input.

import { clear, el } from "./dom.js";
import { t } from "./i18n.js";
import { prefs } from "./store.js";
import { repoUrl } from "./views/shared.js";

const SEEN_KEY = "tutorialSeen";

// Built at open time so links resolve against the live origin and current
// language. `action` renders as a button (only when a repo URL is known);
// slides without one are pure copy.
function buildSlides() {
  const repo = repoUrl(); // null on custom domains (no *.github.io host)
  const link = (path) => (repo ? repo + path : null);
  return [
    { title: t("tutorial.s1Title"), body: t("tutorial.s1Body") },
    {
      title: t("tutorial.s2Title"), body: t("tutorial.s2Body"),
      action: { href: link("/issues/new/choose"), label: t("tutorial.s2Action") },
    },
    {
      title: t("tutorial.s3Title"), body: t("tutorial.s3Body"),
      note: t("tutorial.s3Note"),
      action: { href: link("/settings/secrets/actions"), label: t("tutorial.s3Action") },
    },
    {
      title: t("tutorial.s4Title"), body: t("tutorial.s4Body"),
      action: { href: link("/blob/main/skills/newsdash/README.md"), label: t("tutorial.s4Action") },
    },
    { title: t("tutorial.s5Title"), body: t("tutorial.s5Body") },
  ];
}

// True once the user has finished or explicitly skipped the tutorial.
export function tutorialSeen() {
  return prefs.read(SEEN_KEY) != null;
}

// Show the multi-slide tutorial. Called by maybeShowTutorial() on first run and
// by the "Setup guide" link in Settings → About (which ignores the seen flag).
export function showTutorial() {
  const root = document.getElementById("modal-root");
  if (!root) return;
  clear(root);
  const slides = buildSlides();
  const repoMissing = repoUrl() == null;
  let i = 0;

  const body = el("div", { class: "tut-body" });
  const dots = el("div", { class: "tut-dots" },
    slides.map(() => el("span", { class: "tut-dot" })));
  const backBtn = el("button", { type: "button", class: "secondary",
    onclick: () => go(i - 1) }, t("tutorial.back"));
  const nextBtn = el("button", { type: "button", class: "unlock-btn",
    onclick: () => (i === slides.length - 1 ? finish() : go(i + 1)) });

  // Finish / explicit skip: remember it so it won't reappear. Backdrop/Escape
  // only closes (recoverable) — an accidental dismiss shouldn't lose the guide.
  function finish() { prefs.write(SEEN_KEY, "1"); modal.remove(); }
  function dismiss() { modal.remove(); }

  function go(n) {
    i = Math.max(0, Math.min(slides.length - 1, n));
    const s = slides[i];
    clear(body);
    body.append(
      el("h3", { class: "tut-title" }, s.title),
      el("p", { class: "tut-text" }, s.body),
    );
    if (s.action) {
      if (s.action.href) {
        body.appendChild(el("a", {
          class: "tut-action", href: s.action.href,
          target: "_blank", rel: "noopener noreferrer",
        }, s.action.label));
      } else if (repoMissing) {
        body.appendChild(el("p", { class: "tut-note muted" }, t("tutorial.noRepoNote")));
      }
    }
    if (s.note) body.appendChild(el("p", { class: "tut-note muted" }, s.note));
    dots.querySelectorAll(".tut-dot").forEach((d, n2) =>
      d.classList.toggle("active", n2 === i));
    backBtn.disabled = i === 0;
    nextBtn.textContent = i === slides.length - 1 ? t("tutorial.done") : t("tutorial.next");
  }

  const modal = el("div", { class: "modal-backdrop" },
    el("div", { class: "modal tutorial-modal", role: "dialog", "aria-modal": "true",
                "aria-label": t("tutorial.title"), tabindex: "-1" },
      el("div", { class: "tut-head" },
        el("h2", { class: "tut-heading" }, t("tutorial.title")),
        el("button", { type: "button", class: "tut-skip", onclick: finish },
          t("tutorial.skip")),
      ),
      body,
      el("div", { class: "tut-foot" }, dots,
        el("div", { class: "modal-actions" }, backBtn, nextBtn)),
    ),
  );
  modal.addEventListener("click", (e) => { if (e.target === modal) dismiss(); });
  modal.addEventListener("keydown", (e) => { if (e.key === "Escape") dismiss(); });
  root.appendChild(modal);
  go(0);
  modal.querySelector(".tutorial-modal").focus();
}
