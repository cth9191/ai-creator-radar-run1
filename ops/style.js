// Injects ops/ops.css once, for both W5 panels.
export function useOpsCss() {
  if (document.getElementById("ops-css")) return;
  const link = document.createElement("link");
  link.id = "ops-css";
  link.rel = "stylesheet";
  link.href = new URL("./ops.css", import.meta.url).href;
  document.head.append(link);
}

const CT_DAY = new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", month: "short", day: "numeric" });
const CT_TIME = new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", hour: "numeric", minute: "2-digit" });

// "Oct 16 · 6:07 AM CT"
export function ctStamp(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "–";
  return `${CT_DAY.format(d)} · ${CT_TIME.format(d)} CT`;
}

export function ctDay(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "–" : CT_DAY.format(d);
}
