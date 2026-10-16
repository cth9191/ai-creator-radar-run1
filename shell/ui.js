// Shared building blocks for panels. Import from here instead of re-creating them,
// so every panel looks like part of the same cockpit.

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

const CHECK = '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 6.2 5 8.6 9.5 3.4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const CROSS = '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M3 3l6 6M9 3 3 9" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';

// chip("YouTube", true) -> green check, chip("X", false) -> clay X,
// chip("GAP", "gap" | "closing" | "covered" | "sample") -> styled tag, chip("text") -> neutral.
export function chip(label, state) {
  const node = el("span", { class: "chip" });
  if (state === true) { node.classList.add("ok"); node.innerHTML = CHECK; }
  else if (state === false) { node.classList.add("bad"); node.innerHTML = CROSS; }
  else if (typeof state === "string") node.classList.add(state);
  node.append(label);
  return node;
}

// Cream metric card with dark text.
export function metric({ label, value, sub, accent = false }) {
  return el("div", { class: accent ? "metric accent" : "metric" },
    el("p", { class: "label", text: label }),
    el("div", { class: "value", text: value ?? "–" }),
    sub ? el("div", { class: "sub", text: sub }) : null);
}

export function list(items, renderItem) {
  return el("ul", { class: "rows" }, items.map((it, i) => {
    const li = el("li", { class: "row" });
    const out = renderItem(it, i);
    li.append(...(Array.isArray(out) ? out : [out]).filter(Boolean));
    return li;
  }));
}

export function empty(text, ...extra) {
  return el("div", { class: "empty" }, el("span", { text }), ...extra);
}

export function timeAgo(iso, now = Date.now()) {
  if (!iso) return "never";
  const s = Math.round((now - new Date(iso).getTime()) / 1000);
  const future = s < 0;
  const a = Math.abs(s);
  const v = a < 60 ? `${a}s` : a < 3600 ? `${Math.round(a / 60)}m` : a < 172800 ? `${Math.round(a / 3600)}h` : `${Math.round(a / 86400)}d`;
  return future ? `in ${v}` : `${v} ago`;
}

export function fmt(n) {
  if (n == null || Number.isNaN(n)) return "–";
  const a = Math.abs(n);
  if (a >= 1e9) return `${(n / 1e9).toFixed(1).replace(/\.0$/, "")}B`;
  if (a >= 1e6) return `${(n / 1e6).toFixed(1).replace(/\.0$/, "")}M`;
  if (a >= 1e4) return `${Math.round(n / 1e3)}K`;
  if (a >= 1e3) return `${(n / 1e3).toFixed(1).replace(/\.0$/, "")}K`;
  return String(Math.round(n));
}

export function link(href, text) {
  return /^https:\/\//.test(href || "") ? el("a", { href, target: "_blank", rel: "noopener", text }) : el("span", { text });
}
