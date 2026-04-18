// yesterday.js — renders prior-day game stats per player, with DNP rows.

function td(value, cls, label, extra) {
  const className = cls ? ` class="${cls}"` : "";
  const dataLabel = label ? ` data-label="${label}"` : "";
  const attrs = extra || "";
  return `<td${className}${dataLabel}${attrs}>${value}</td>`;
}

function renderHittersYesterday(players) {
  const headers = ["Player", "Opp", "H/AB", "R", "HR", "RBI", "SB", "Pts", "Summary"];
  let html = `<thead><tr>${headers.map((h, i) => {
    const align = (i >= 2 && i <= 7) ? "num" : "";
    return `<th class="${align}">${h}</th>`;
  }).join("")}</tr></thead><tbody>`;

  let total = { AB: 0, H: 0, R: 0, HR: 0, RBI: 0, SB: 0, pts: 0 };
  for (const p of players) {
    if (p.dnp) {
      html += `<tr class="dnp">
        ${td(`<div class="player-cell"><strong>${p.name}</strong><small>${p.team} · ${p.position}</small></div>`, "", "Player")}
        ${td(`<span class="dnp-badge">DNP</span> ${p.dnp_reason || ""}`, "", "", ` colspan="7"`)}
        ${td(p.summary || "", "", "Summary")}
      </tr>`;
    } else {
      const s = p.stats || {};
      total.AB += s.AB || 0; total.H += s.H || 0; total.R += s.R || 0;
      total.HR += s.HR || 0; total.RBI += s.RBI || 0; total.SB += s.SB || 0;
      total.pts += p.points || 0;
      html += `<tr>
        ${td(`<div class="player-cell"><strong>${p.name}</strong><small>${p.team} · ${p.position}</small></div>`, "", "Player")}
        ${td(p.opponent || "—", "", "Opp")}
        ${td(`${s.H ?? 0}-${s.AB ?? 0}`, "num", "H/AB")}
        ${td(fmtOrDash(s.R), "num", "R")}
        ${td(fmtOrDash(s.HR), "num", "HR")}
        ${td(fmtOrDash(s.RBI), "num", "RBI")}
        ${td(fmtOrDash(s.SB), "num", "SB")}
        ${td(fmt(p.points, 0), "num", "Pts")}
        ${td(p.summary || "", "", "Summary")}
      </tr>`;
    }
  }

  html += `<tr class="total">
    ${td("TOTAL", "", "")}
    ${td("", "", "")}
    ${td(`${total.H}-${total.AB}`, "num", "H/AB")}
    ${td(total.R, "num", "R")}
    ${td(total.HR, "num", "HR")}
    ${td(total.RBI, "num", "RBI")}
    ${td(total.SB, "num", "SB")}
    ${td(fmt(total.pts, 0), "num", "Pts")}
    ${td("", "", "")}
  </tr></tbody>`;
  return html;
}

function renderPitchersYesterday(players, isRP) {
  const headers = isRP
    ? ["Player", "Opp", "IP", "H", "ER", "K", "BB", "Dec", "Pts", "Summary"]
    : ["Player", "Opp", "IP", "H", "ER", "K", "BB", "W/L", "Pts", "Summary"];
  let html = `<thead><tr>${headers.map((h, i) => {
    const align = (i >= 2 && i <= 8) ? "num" : "";
    return `<th class="${align}">${h}</th>`;
  }).join("")}</tr></thead><tbody>`;

  let total = { IP: 0, H: 0, ER: 0, K: 0, BB: 0, pts: 0 };
  for (const p of players) {
    if (p.dnp) {
      html += `<tr class="dnp">
        ${td(`<div class="player-cell"><strong>${p.name}</strong><small>${p.team} · ${p.position}</small></div>`, "", "Player")}
        ${td(`<span class="dnp-badge">DNP</span> ${p.dnp_reason || ""}`, "", "", ` colspan="8"`)}
        ${td(p.summary || "", "", "Summary")}
      </tr>`;
    } else {
      const s = p.stats || {};
      total.IP += s.IP || 0; total.H += s.H || 0; total.ER += s.ER || 0;
      total.K += s.K || 0; total.BB += s.BB || 0;
      total.pts += p.points || 0;
      const decision = s.W ? "W" : s.SV ? "SV" : s.L ? "L" : "—";
      html += `<tr>
        ${td(`<div class="player-cell"><strong>${p.name}</strong><small>${p.team} · ${p.position}</small></div>`, "", "Player")}
        ${td(p.opponent || "—", "", "Opp")}
        ${td(s.IP ? fmt(s.IP, 1) : "—", "num", "IP")}
        ${td(fmtOrDash(s.H), "num", "H")}
        ${td(s.ER !== undefined ? s.ER : "—", "num", "ER")}
        ${td(fmtOrDash(s.K), "num", "K")}
        ${td(fmtOrDash(s.BB), "num", "BB")}
        ${td(decision, "num", isRP ? "Dec" : "W/L")}
        ${td(fmt(p.points, 1), "num", "Pts")}
        ${td(p.summary || "", "", "Summary")}
      </tr>`;
    }
  }

  if (players.length > 1) {
    html += `<tr class="total">
      ${td("TOTAL", "", "")}
      ${td("", "", "")}
      ${td(fmt(total.IP, 1), "num", "IP")}
      ${td(total.H, "num", "H")}
      ${td(total.ER, "num", "ER")}
      ${td(total.K, "num", "K")}
      ${td(total.BB, "num", "BB")}
      ${td("", "", "")}
      ${td(fmt(total.pts, 1), "num", "Pts")}
      ${td("", "", "")}
    </tr>`;
  }
  html += `</tbody>`;
  return html;
}

async function renderYesterday() {
  try {
    const data = await loadJSON("yesterday.json");
    const hitters = data.players.filter((p) => p.type === "hitter");
    const sps = data.players.filter((p) => p.type === "sp");
    const rps = data.players.filter((p) => p.type === "rp");

    document.getElementById("page-title").textContent = `Yesterday — ${fmtDate(data.date)}`;
    document.getElementById("page-sub").textContent =
      `Previous day's game stats · data generated ${fmtTimestamp(data.generated_at)}`;
    document.getElementById("hitters-table").innerHTML = renderHittersYesterday(hitters);
    document.getElementById("sp-table").innerHTML = renderPitchersYesterday(sps, false);
    document.getElementById("rp-table").innerHTML = renderPitchersYesterday(rps, true);
  } catch (err) {
    document.getElementById("hitters-section").innerHTML =
      `<div class="empty-state">Couldn't load yesterday's data: ${err.message}</div>`;
    console.error(err);
  }
}

renderYesterday();
