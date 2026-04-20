// team.js — renders Team Overview: position players, SPs, RP.

const MLB_AVG_ERA = 4.20;
const SP_RSAR_MULTIPLIER = 3.5;

function hitterAVG(s) {
  if (!s) return null;
  if (typeof s.AVG === "number") return s.AVG;
  if (s.AB && typeof s.H === "number") return s.H / s.AB;
  return null;
}

function hitterYTD(s) {
  const avg = hitterAVG(s);
  if (avg === null) return 0;
  return Math.round(avg * 1000) + (s.HR || 0) + (s.RBI || 0) + (s.R || 0) + (s.SB || 0);
}

function hitterProj(p, s) {
  const projAB = (p.projected_stats && p.projected_stats.AB) || 0;
  const avg = hitterAVG(s);
  if (!s || !s.AB || !projAB || avg === null) return Math.round(p.projected_points || 0);
  const scale = projAB / s.AB;
  const counting = (s.HR || 0) + (s.RBI || 0) + (s.R || 0) + (s.SB || 0);
  return Math.round(avg * 1000 + counting * scale);
}

function spERA(s) {
  if (!s) return null;
  if (typeof s.ERA === "number") return s.ERA;
  if (s.IP && typeof s.ER === "number") return (s.ER * 9) / s.IP;
  return null;
}

function spRSAR(s) {
  if (!s || !s.IP) return 0;
  const era = spERA(s);
  if (era === null) return 0;
  return ((1.2 * MLB_AVG_ERA - era) * (s.IP / 9));
}

function spProj(p, s) {
  const projIP = (p.projected_stats && p.projected_stats.IP) || 0;
  if (!s || !s.IP || !projIP) return p.projected_points || 0;
  const era = spERA(s);
  if (era === null) return p.projected_points || 0;
  return (1.2 * MLB_AVG_ERA - era) * (projIP / 9);
}

function rpYTD(s) {
  if (!s) return 0;
  return 5 * ((s.W || 0) + (s.SV || 0));
}

function rpProj(p, s) {
  const projIP = (p.projected_stats && p.projected_stats.IP) || 0;
  if (!s || !s.IP || !projIP) return p.projected_points || 0;
  const scale = projIP / s.IP;
  return 5 * ((s.W || 0) + (s.SV || 0)) * scale;
}

function td(value, cls, label) {
  const className = cls ? ` class="${cls}"` : "";
  const dataLabel = label ? ` data-label="${label}"` : "";
  return `<td${className}${dataLabel}>${value}</td>`;
}

function renderHitters(players, statsByName) {
  const headers = ["Player", "Pos", "AB", "AVG", "HR", "RBI", "R", "SB", "Pre", "Proj", "YTD"];
  let html = `<thead><tr>${headers.map((h, i) => `<th class="${i >= 2 ? 'num' : ''}">${h}</th>`).join("")}</tr></thead><tbody>`;

  let t = { AB: 0, avgSum: 0, avgCount: 0, HR: 0, RBI: 0, R: 0, SB: 0, pre: 0, proj: 0, ytd: 0 };
  for (const p of players) {
    const s = statsByName[p.name] || {};
    const avg = hitterAVG(s);
    const ytd = hitterYTD(s);
    const pre = Math.round(p.projected_points || 0);
    const proj = hitterProj(p, s);
    t.AB += s.AB || 0;
    if (avg !== null) { t.avgSum += avg; t.avgCount += 1; }
    t.HR += s.HR || 0;
    t.RBI += s.RBI || 0; t.R += s.R || 0; t.SB += s.SB || 0;
    t.pre += pre; t.proj += proj; t.ytd += ytd;

    html += `<tr>
      ${td(`<div class="player-cell"><strong>${p.name}</strong><small>${p.team}</small></div>`, "", "Player")}
      ${td(p.positions[0] || "—", "", "Pos")}
      ${td(s.AB || 0, "num", "AB")}
      ${td(avg !== null ? avg.toFixed(3).replace(/^0/, "") : "—", "num", "AVG")}
      ${td(fmtOrDash(s.HR), "num", "HR")}
      ${td(fmtOrDash(s.RBI), "num", "RBI")}
      ${td(fmtOrDash(s.R), "num", "R")}
      ${td(fmtOrDash(s.SB), "num", "SB")}
      ${td(pre, "num", "Pre")}
      ${td(proj, "num", "Proj")}
      ${td(ytd, "num", "YTD")}
    </tr>`;
  }

  const teamAvg = t.avgCount ? (t.avgSum / t.avgCount).toFixed(3).replace(/^0/, "") : "—";
  html += `<tr class="total">
    ${td("TOTAL", "", "")}
    ${td("", "", "")}
    ${td(t.AB, "num", "AB")}
    ${td(teamAvg, "num", "AVG")}
    ${td(t.HR, "num", "HR")}
    ${td(t.RBI, "num", "RBI")}
    ${td(t.R, "num", "R")}
    ${td(t.SB, "num", "SB")}
    ${td(t.pre, "num", "Pre")}
    ${td(t.proj, "num", "Proj")}
    ${td(t.ytd, "num", "YTD")}
  </tr></tbody>`;
  return html;
}

function renderSPs(players, statsByName) {
  const headers = ["Player", "IP", "ERA", "K", "BB", "W", "Pre", "Proj", "YTD"];
  let html = `<thead><tr>${headers.map((h, i) => `<th class="${i >= 1 ? 'num' : ''}">${h}</th>`).join("")}</tr></thead><tbody>`;

  const rows = players.map((p) => {
    const s = statsByName[p.name] || {};
    const ytd = spRSAR(s);
    const proj = spProj(p, s);
    const pre = p.projected_points || 0;
    return { p, s, ytd, proj, pre };
  });

  // Team SP score uses the top-3 of each column individually (so the best
  // three preseason projections, the best three projections-to-date, and
  // the best three YTDs — each multiplied by 3.5).
  const topN = (arr, n = 3) => [...arr].sort((a, b) => b - a).slice(0, n);
  const teamPre = topN(rows.map(r => r.pre)).reduce((a, b) => a + b, 0);
  const teamProj = topN(rows.map(r => r.proj)).reduce((a, b) => a + Math.round(b), 0) * SP_RSAR_MULTIPLIER;
  const teamYTD = topN(rows.map(r => r.ytd)).reduce((a, b) => a + Math.round(b), 0) * SP_RSAR_MULTIPLIER;

  for (const { p, s, ytd, proj, pre } of rows) {
    const era = spERA(s);
    html += `<tr>
      ${td(`<div class="player-cell"><strong>${p.name}</strong><small>${p.team}</small></div>`, "", "Player")}
      ${td(s.IP ? fmt(s.IP, 1) : "—", "num", "IP")}
      ${td(era !== null ? fmt(era, 2) : "—", "num", "ERA")}
      ${td(fmtOrDash(s.K), "num", "K")}
      ${td(fmtOrDash(s.BB), "num", "BB")}
      ${td(fmtOrDash(s.W), "num", "W")}
      ${td(fmt(pre, 1), "num", "Pre")}
      ${td(fmt(proj, 1), "num", "Proj")}
      ${td(fmt(ytd, 1), "num", "YTD")}
    </tr>`;
  }

  html += `<tr class="total">
    ${td("TEAM SP (top 3 × 3.5)", "", "")}
    ${td("", "num", "")}
    ${td("", "num", "")}
    ${td("", "num", "")}
    ${td("", "num", "")}
    ${td("", "num", "")}
    ${td(fmt(teamPre, 1), "num", "Pre (top 3)")}
    ${td(fmt(teamProj, 1), "num", "Proj (top 3 × 3.5)")}
    ${td(fmt(teamYTD, 1), "num", "YTD (top 3 × 3.5)")}
  </tr></tbody>`;
  return html;
}

function renderRP(players, statsByName) {
  const headers = ["Player", "G", "IP", "ERA", "W", "SV", "Pre", "Proj", "YTD"];
  let html = `<thead><tr>${headers.map((h, i) => `<th class="${i >= 1 ? 'num' : ''}">${h}</th>`).join("")}</tr></thead><tbody>`;

  for (const p of players) {
    const s = statsByName[p.name] || {};
    const era = spERA(s);
    const ytd = rpYTD(s);
    const proj = rpProj(p, s);
    const pre = p.projected_points || 0;
    html += `<tr>
      ${td(`<div class="player-cell"><strong>${p.name}</strong><small>${p.team}</small></div>`, "", "Player")}
      ${td(fmtOrDash(s.G), "num", "G")}
      ${td(s.IP ? fmt(s.IP, 1) : "—", "num", "IP")}
      ${td(era !== null ? fmt(era, 2) : "—", "num", "ERA")}
      ${td(fmtOrDash(s.W), "num", "W")}
      ${td(fmtOrDash(s.SV), "num", "SV")}
      ${td(fmt(pre, 1), "num", "Pre")}
      ${td(fmt(proj, 1), "num", "Proj")}
      ${td(fmt(ytd, 1), "num", "YTD")}
    </tr>`;
  }
  html += `</tbody>`;
  return html;
}

async function renderTeam() {
  try {
    const [team, stats, yesterday] = await Promise.all([
      loadJSON("my_team.json"),
      loadJSON("season_stats.json"),
      loadJSON("yesterday.json").catch(() => ({}))
    ]);

    const statsByName = stats;
    const players = team.players;

    const hitters = players.filter((p) => p.player_type === "hitter");
    const sps = players.filter((p) => p.player_type === "sp");
    const rps = players.filter((p) => p.player_type === "rp");

    document.getElementById("hitters-table").innerHTML = renderHitters(hitters, statsByName);
    document.getElementById("sp-table").innerHTML = renderSPs(sps, statsByName);
    document.getElementById("rp-table").innerHTML = renderRP(rps, statsByName);

    const refreshed = yesterday.generated_at ? fmtTimestamp(yesterday.generated_at) : "—";
    document.getElementById("page-sub").textContent =
      `Season stats, fantasy points to date, and projected season totals · data refreshed ${refreshed}`;
  } catch (err) {
    document.getElementById("hitters-section").innerHTML =
      `<div class="empty-state">Couldn't load team data: ${err.message}</div>`;
    console.error(err);
  }
}

renderTeam();
