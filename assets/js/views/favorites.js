// Favorites library: items starred anywhere on the dashboard, stored
// locally with an itemSnapshot so entries outlive the rolling feed window.
// Lives behind the unlock gate, like Clippings (the private page).

import { listFavorites, removeFavorite } from "../annodb.js";
import { clear, el, safeHref } from "../dom.js";
import { fmtDateTime, t } from "../i18n.js";
import { get } from "../store.js";
import { lockedCard } from "./shared.js";

const state = { q: "" };

export async function render(container) {
  clear(container);
  if (!get().unlocked) {
    container.appendChild(el("p", { class: "muted" }, t("fav.lockedHint")));
    container.appendChild(lockedCard());
    return;
  }

  const favorites = await listFavorites();
  const list = el("div", { class: "clippings-list" });

  const search = el("input", {
    type: "search", class: "filter-search",
    placeholder: t("fav.searchPlaceholder"), value: state.q,
    oninput: (e) => { state.q = e.target.value; renderList(); },
  });
  container.appendChild(el("div", { class: "filter-bar" }, search));
  container.appendChild(list);

  function entryCard(fav) {
    const snap = fav.itemSnapshot || {};
    return el("article", { class: "clipping type-favorite" },
      el("div", { class: "clipping-meta" },
        el("span", { class: "tag tag-favorite" }, "★"),
        snap.source ? el("span", { class: "muted" }, snap.source) : null,
        snap.published_at
          ? el("span", { class: "muted" },
              fmtDateTime(snap.published_at, { year: "numeric" }))
          : null,
      ),
      el("p", { class: "clipping-source" },
        el("a", { href: safeHref(snap.url), target: "_blank", rel: "noopener" },
          snap.title || "untitled"),
        snap.venue ? ` · ${snap.venue}` : ""),
      snap.summary ? el("p", { class: "clipping-note muted" }, snap.summary) : null,
      el("div", { class: "clipping-actions" },
        el("button", {
          class: "linklike danger",
          onclick: async () => {
            await removeFavorite(fav.itemId);
            const idx = favorites.indexOf(fav);
            if (idx >= 0) favorites.splice(idx, 1);
            renderList();
          },
        }, t("fav.remove")),
      ),
    );
  }

  function renderList() {
    clear(list);
    const q = state.q.trim().toLowerCase();
    const visible = favorites.filter((fav) => {
      const snap = fav.itemSnapshot || {};
      return !q || `${snap.title || ""} ${snap.summary || ""} ${snap.source || ""}`
        .toLowerCase().includes(q);
    });
    if (!visible.length) {
      list.appendChild(el("p", { class: "muted" }, t("fav.empty")));
      return;
    }
    for (const fav of visible) list.appendChild(entryCard(fav));
  }

  renderList();
}
