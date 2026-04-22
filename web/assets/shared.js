// shared.js — loaders, formatters, nav highlighting used across all three views.

const DATA_BASE = "/data";

async function loadJSON(path) {
  const url = `${DATA_BASE}/${path}?_=${Date.now()}`;
  const resp = await fetch(url, { cache: "no-cache" });
  if (!resp.ok) throw new Error(`${path} ${resp.status}`);
  return resp.json();
}

function highlightActiveNav() {
  const here = location.pathname.replace(/\/$/, "") || "/";
  document.querySelectorAll("nav.tabs a").forEach((a) => {
    const href = a.getAttribute("href").replace(/\/$/, "") || "/";
    if (href === here) a.classList.add("active");
  });
}

function fmt(n, digits = 0) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  if (n === 0) return "0";
  return Number(n).toFixed(digits);
}

function fmtOrDash(n, digits = 0) {
  if (n === null || n === undefined || n === 0 || Number.isNaN(n)) return "—";
  return Number(n).toFixed(digits);
}

function fmtAvg(h, ab) {
  if (!ab) return ".000";
  return (h / ab).toFixed(3).replace(/^0/, "");
}

// Parse "YYYY-MM-DD" as a local-timezone date (not UTC midnight, which renders
// as the previous day in any timezone west of UTC).
function parseLocalDate(iso) {
  if (!iso) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return new Date(iso);
}

function fmtDate(iso) {
  const d = parseLocalDate(iso);
  if (!d) return "";
  return d.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
}

function fmtDateShort(iso) {
  const d = parseLocalDate(iso);
  if (!d) return "";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function fmtTimestamp(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit"
  });
}

function showError(container, err) {
  container.innerHTML = `<div class="empty-state">Couldn't load data: ${err.message}</div>`;
  console.error(err);
}

document.addEventListener("DOMContentLoaded", highlightActiveNav);
