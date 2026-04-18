// news.js — renders News Feed with injuries section and per-player updates.

function escapeHTML(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderSources(sources) {
  if (!sources || !sources.length) return "";
  return `<div class="sources">${sources
    .map((s) => `<a href="${encodeURI(s.url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(s.title)} →</a>`)
    .join("")}</div>`;
}

function renderInjury(inj) {
  const statusChange =
    inj.previous_status && inj.previous_status !== inj.status
      ? `<span class="prev-status">was: ${escapeHTML(inj.previous_status)}</span>`
      : "";
  const sourceLink = inj.source
    ? `<div class="sources"><a href="${encodeURI(inj.source.url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(inj.source.title)} →</a></div>`
    : "";

  return `<div class="injury-card">
    <div class="head">
      <div>
        <span class="name">${escapeHTML(inj.name)}</span>
        <span class="meta" style="margin-left:8px">${escapeHTML(inj.team || "")} · ${escapeHTML(inj.position || "")}</span>
      </div>
      <div><span class="status">${escapeHTML(inj.status)}</span>${statusChange}</div>
    </div>
    <p>${escapeHTML(inj.note)}</p>
    ${sourceLink}
  </div>`;
}

function renderPlayerUpdate(p) {
  return `<div class="news-card">
    <div class="head">
      <div class="name">${escapeHTML(p.name)}</div>
      <div class="meta">${escapeHTML(p.team || "")} · ${escapeHTML(p.position || "")}</div>
    </div>
    <p>${escapeHTML(p.summary)}</p>
    ${renderSources(p.sources)}
  </div>`;
}

async function renderNews() {
  try {
    const data = await loadJSON("news.json");

    document.getElementById("page-sub").textContent =
      `Synthesized player-level headlines · data generated ${fmtTimestamp(data.generated_at)}`;

    const injuries = data.injuries || [];
    const injuriesEl = document.getElementById("injuries-list");
    if (injuries.length === 0) {
      injuriesEl.innerHTML = `<div class="empty-state">No active injuries on the roster.</div>`;
    } else {
      injuriesEl.innerHTML = `<div class="news-grid">${injuries.map(renderInjury).join("")}</div>`;
    }

    const players = [...(data.players || [])].sort((a, b) => a.name.localeCompare(b.name));
    const playersEl = document.getElementById("players-list");
    if (players.length === 0) {
      playersEl.innerHTML = `<div class="empty-state">No player updates yet today.</div>`;
    } else {
      playersEl.innerHTML = players.map(renderPlayerUpdate).join("");
    }
  } catch (err) {
    document.getElementById("injuries-section").innerHTML =
      `<div class="empty-state">Couldn't load news: ${err.message}</div>`;
    console.error(err);
  }
}

renderNews();
