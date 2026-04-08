"""
daily_report.py — Daily team report generator.

Fetches prior day box scores, news, injury updates, and cumulative team score.
Formats an HTML email and sends to Jon's personal Gmail.

Called by run_daily.py.
"""

from __future__ import annotations
import json
from pathlib import Path
from datetime import date, timedelta, datetime
from typing import Optional

import config
from players import Player
from draft import load_my_team

GMAIL_CREDENTIALS_PATH = Path.home() / ".config" / "personal-mcp" / "gmail" / "credentials.json"

# Season cumulative stats are persisted here
SEASON_STATS_FILE = Path(__file__).parent / "data" / "season_stats.json"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class DayResult:
    """Holds one player's performance data for a single day."""
    def __init__(self, player_name: str, player_type: str):
        self.player_name = player_name
        self.player_type = player_type
        self.position: str = ""      # roster position (C, 1B, SP, RP, etc.)
        self.team: str = ""          # MLB team abbreviation
        self.opponent: str = ""      # opponent (e.g., "vs LAA", "@ NYM")
        self.stats: dict = {}        # raw box score stats
        self.fantasy_points: float = 0.0
        self.summary: str = ""       # one-line game summary
        self.decision: str = ""      # pitcher decision: W, L, SV, or ""
        self.news: str = ""          # 2-3 sentence summary
        self.injury_note: str = ""   # empty if healthy
        self.injury_flag: bool = False
        self.injury_prev: str = ""   # previous injury status
        self.injury_curr: str = ""   # current injury status
        self.dnp: bool = False       # did not play
        self.preseason_pts: float = 0.0  # preseason projection
        self.ytd_pts: float = 0.0    # year-to-date points
        self.pace_pts: float = 0.0   # 162-game extrapolation

    def compute_points(self):
        if self.player_type == "hitter":
            scoring = config.HITTER_SCORING
            total = 0.0
            for stat, weight in scoring.items():
                total += self.stats.get(stat, 0.0) * weight
            self.fantasy_points = round(total, 2)
        elif self.player_type == "rp":
            w = self.stats.get("W", 0.0)
            sv = self.stats.get("SV", 0.0)
            self.fantasy_points = round(config.RP_WIN_SAVE_MULTIPLIER * (w + sv), 2)
        else:
            # SP: daily RSAR contribution
            # RSAR = (1.2 × MLB_AVG_ERA − ERA) × (IP / 9)
            # For a single game, ERA = (ER / IP) × 9
            ip = self.stats.get("IP", 0.0)
            er = self.stats.get("ER", 0.0)
            if ip > 0:
                game_era = (er / ip) * 9.0
                rsar = (1.2 * config.MLB_AVG_ERA - game_era) * (ip / 9.0)
                self.fantasy_points = round(rsar, 2)
            else:
                self.fantasy_points = 0.0
        return self.fantasy_points


# ---------------------------------------------------------------------------
# Web search helpers (called from run_daily.py with Claude's WebSearch tool)
# ---------------------------------------------------------------------------

def build_box_score_query(player_name: str, game_date: str) -> str:
    """Return a web search query for a player's box score."""
    return f"{player_name} baseball stats {game_date} box score"


def build_news_query(player_name: str, game_date: str) -> str:
    """Return a search query for recent news."""
    return f"{player_name} baseball news {game_date}"


def build_injury_query(player_name: str) -> str:
    """Return a search query for injury status."""
    return f"{player_name} baseball injury update status"


def parse_box_score_from_search(player_name: str, player_type: str, search_text: str) -> DayResult:
    """
    Parse stats from raw web search text into a DayResult.
    This is a best-effort parser — results vary by search snippet quality.

    In practice, run_daily.py will call this after using Claude's WebSearch
    tool, passing the raw snippet text here for parsing.
    """
    result = DayResult(player_name, player_type)

    import re
    text = search_text.lower()

    if player_type == "hitter":
        # Look for patterns like "3-for-4", "2 HR", "5 RBI", etc.
        patterns = {
            "HR":  r"(\d+)\s*(?:hr|home run)",
            "RBI": r"(\d+)\s*rbi",
            "R":   r"(\d+)\s*run",
            "SB":  r"(\d+)\s*(?:sb|stolen base)",
            "BB":  r"(\d+)\s*walk",
            "H":   r"(\d+)-for-(\d+)",  # hits-for-at-bats
        }
        for stat, pattern in patterns.items():
            m = re.search(pattern, text)
            if m:
                result.stats[stat] = float(m.group(1))
    else:
        # Pitchers: look for IP, K, ER, W/L
        patterns = {
            "IP":  r"(\d+\.?\d*)\s*ip",
            "K":   r"(\d+)\s*(?:k|strikeout)",
            "ER":  r"(\d+)\s*earned run",
            "BB":  r"(\d+)\s*walk",
            "W":   r"\bwin\b|\bwon\b",
            "L":   r"\bloss\b|\blose\b",
            "SV":  r"\bsave\b",
        }
        for stat, pattern in patterns.items():
            m = re.search(pattern, text)
            if m:
                if stat in ("W", "L", "SV"):
                    result.stats[stat] = 1.0
                else:
                    result.stats[stat] = float(m.group(1))

    result.compute_points()
    return result


# ---------------------------------------------------------------------------
# Season cumulative stats
# ---------------------------------------------------------------------------

def load_season_stats() -> dict:
    """Load cumulative season stats dict: {player_name: {stat: total, ...}}"""
    if SEASON_STATS_FILE.exists():
        with open(SEASON_STATS_FILE) as f:
            return json.load(f)
    return {}


def update_season_stats(season: dict, day_results: list[DayResult]) -> dict:
    """Add today's stats to the running season totals."""
    for r in day_results:
        if r.player_name not in season:
            season[r.player_name] = {"fantasy_points": 0.0}
        season[r.player_name]["fantasy_points"] = round(
            season[r.player_name].get("fantasy_points", 0.0) + r.fantasy_points, 2
        )
        for stat, val in r.stats.items():
            season[r.player_name][stat] = round(
                season[r.player_name].get(stat, 0.0) + val, 2
            )
    return season


def save_season_stats(season: dict):
    with open(SEASON_STATS_FILE, "w") as f:
        json.dump(season, f, indent=2)


def compute_ytd_points(player_stats: dict, player_type: str) -> float:
    """
    Compute full-season YTD points from cumulative stats using actual league scoring.

    Hitters: BA × 1000 + HR + RBI + R + SB
    SP: RSAR = (1.2 × MLB_AVG_ERA − ERA) × (IP / 9)
    RP: 5 × (W + SV)
    """
    if player_type == "hitter":
        ab = player_stats.get("AB", 0)
        h = player_stats.get("H", 0)
        ba = h / ab if ab > 0 else 0.0
        return round(
            ba * 1000
            + player_stats.get("HR", 0)
            + player_stats.get("RBI", 0)
            + player_stats.get("R", 0)
            + player_stats.get("SB", 0),
            1
        )
    elif player_type == "rp":
        w = player_stats.get("W", 0)
        sv = player_stats.get("SV", 0)
        return round(config.RP_WIN_SAVE_MULTIPLIER * (w + sv), 1)
    else:
        # SP: RSAR from cumulative season stats
        ip = player_stats.get("IP", 0)
        er = player_stats.get("ER", 0)
        if ip > 0:
            season_era = (er / ip) * 9.0
            rsar = (1.2 * config.MLB_AVG_ERA - season_era) * (ip / 9.0)
            return round(rsar, 1)
        return 0.0


def compute_pace_points(player_stats: dict, player_type: str, team_games_played: int) -> float:
    """
    Project full-season (162-game) points from cumulative stats.

    Hitters:
      - BA is a rate stat — use current BA (or apply 300 AB min penalty if
        projected AB < 300). BA × 1000 stays flat; counting stats scale.
      - Projected AB = (AB / GP) × 162. If < 300, effective BA uses
        H / 300 (shortfall added to AB without adding hits).
      - Pace = effective_BA × 1000 + (HR + RBI + R + SB) × (162 / GP)

    SP:
      - Extrapolate IP and ER to full season based on games started.
      - Projected IP = (IP / GS) × projected_GS (assume ~32 starts).
      - RSAR from projected totals. Apply IP/G < 3.5 zero-score penalty.

    RP:
      - Extrapolate W and SV to 162 team games.
      - Pace = 5 × (W + SV) × (162 / GP)
    """
    if team_games_played <= 0:
        return 0.0

    scale = 162.0 / team_games_played

    if player_type == "hitter":
        ab = player_stats.get("AB", 0)
        h = player_stats.get("H", 0)
        hr = player_stats.get("HR", 0)
        rbi = player_stats.get("RBI", 0)
        r = player_stats.get("R", 0)
        sb = player_stats.get("SB", 0)

        if ab == 0:
            return 0.0

        # Project AB to full season
        projected_ab = ab * scale

        # Apply 300 AB minimum rule
        if projected_ab >= config.HITTER_MIN_AB:
            # Current BA holds at pace
            ba = h / ab
        else:
            # Shortfall: effective AB becomes 300, hits stay the same (scaled)
            projected_h = h * scale
            ba = projected_h / config.HITTER_MIN_AB

        # Scale counting stats linearly
        return round(
            ba * 1000
            + hr * scale
            + rbi * scale
            + r * scale
            + sb * scale,
            1
        )

    elif player_type == "rp":
        w = player_stats.get("W", 0)
        sv = player_stats.get("SV", 0)
        return round(config.RP_WIN_SAVE_MULTIPLIER * (w + sv) * scale, 1)

    else:
        # SP: extrapolate based on starts
        ip = player_stats.get("IP", 0)
        er = player_stats.get("ER", 0)
        gs = player_stats.get("GS", 0)
        g = player_stats.get("G", 0)

        if ip <= 0:
            return 0.0

        # IP/G penalty check (reliever-as-starter prevention)
        if g > 0 and (ip / g) < config.SP_MIN_IP_PER_GAME:
            return 0.0

        # ERA stays the same (rate stat); extrapolate IP
        # Assume ~32 starts for a full season if we have GS data
        if gs > 0:
            ip_per_start = ip / gs
            projected_starts = 32.0
            projected_ip = ip_per_start * projected_starts
        else:
            projected_ip = ip * scale

        season_era = (er / ip) * 9.0
        rsar = (1.2 * config.MLB_AVG_ERA - season_era) * (projected_ip / 9.0)
        return round(rsar, 1)


# ---------------------------------------------------------------------------
# Gmail MCP token expiry check
# ---------------------------------------------------------------------------

def check_gmail_reauth_needed() -> Optional[str]:
    """
    Check if the Gmail personal MCP refresh token expires tomorrow or sooner.
    Uses the credentials file's expiry_date (access token) and
    refresh_token_expires_in to compute the actual refresh token expiry.
    Returns a warning message string if re-auth is needed, else None.
    """
    if not GMAIL_CREDENTIALS_PATH.exists():
        return "Gmail credentials file not found — re-auth may be needed now."
    with open(GMAIL_CREDENTIALS_PATH) as f:
        creds = json.load(f)
    expiry_ms = creds.get("expiry_date")
    refresh_ttl = creds.get("refresh_token_expires_in")
    if not expiry_ms or not refresh_ttl:
        return None
    # access token expiry minus ~1hr gives approximate auth time
    access_expires = datetime.fromtimestamp(expiry_ms / 1000)
    authed_at = access_expires - timedelta(hours=1)
    refresh_expires = (authed_at + timedelta(seconds=refresh_ttl)).date()
    days_left = (refresh_expires - date.today()).days
    if days_left <= 1:
        return (
            f"Gmail personal MCP token expires {'today' if days_left <= 0 else 'tomorrow'} "
            f"(authed {authed_at.strftime('%b %-d')}). "
            f"Re-authenticate to avoid missing tomorrow's email."
        )
    return None


def _build_reauth_banner() -> str:
    """Return an HTML warning banner if Gmail re-auth is due, else empty string."""
    msg = check_gmail_reauth_needed()
    if msg:
        return f'<div class="reauth-banner"><strong>Action needed:</strong> {msg}</div>'
    return ""


# ---------------------------------------------------------------------------
# HTML email formatter
# ---------------------------------------------------------------------------

# Inline styles used throughout the email (Gmail strips <style> blocks)
_TH = 'style="padding:6px 10px;text-align:left;border-bottom:2px solid #ddd;white-space:nowrap"'
_TD = 'style="padding:5px 10px;border-bottom:1px solid #eee"'
_TD_R = 'style="padding:5px 10px;border-bottom:1px solid #eee;text-align:right"'
_TD_NEWS = 'style="padding:5px 10px;border-bottom:1px solid #eee;font-size:11px;color:#555;max-width:180px"'
_TOTAL_TD = 'style="padding:6px 10px;border-top:2px solid #1a3a5c;font-weight:bold;background:#e8f0fe"'
_TOTAL_TD_R = 'style="padding:6px 10px;border-top:2px solid #1a3a5c;font-weight:bold;background:#e8f0fe;text-align:right"'


def _fmt(val, default="—") -> str:
    if val is None or val == 0:
        return default
    if isinstance(val, float) and val == int(val):
        return str(int(val))
    return str(val)


def _fmt_pts(val) -> str:
    if isinstance(val, float):
        if val == int(val):
            return f"{int(val)}.0"
        return f"{val:.1f}"
    return str(val)


def build_html_email(
    report_date: date,
    day_results: list[DayResult],
    season_stats: dict,
) -> str:
    """Build the full HTML email body matching the established format."""

    hitters = [r for r in day_results if r.player_type == "hitter"]
    pitchers = [r for r in day_results if r.player_type in ("sp", "rp")]
    injured = [r for r in day_results if r.injury_flag]
    played_count = sum(1 for r in day_results if not r.dnp)
    date_short = report_date.strftime("%b %-d")

    html = f"""<html><body style="font-family:Arial,sans-serif;color:#222;max-width:1100px;margin:0 auto">
  <h1 style="color:#1a3a5c;border-bottom:2px solid #1a3a5c;padding-bottom:6px">Fantasy Baseball Daily — {report_date.strftime("%B %d, %Y")}</h1>
  {_build_reauth_banner()}
    <h2 style="color:#1a3a5c">Hitters — {date_short}</h2>
    <p style="color:#999;font-size:11px;margin-top:0">Scoring: BA&times;1000 + HR + RBI + R + SB (300 AB min)</p>
    <table style="border-collapse:collapse;width:100%;font-size:13px">
      <thead><tr style="background:#f5f5f5">
        <th {_TH}>Player</th><th {_TH}>Pos</th><th {_TH}>Opp</th>
        <th {_TH}>H/AB</th><th {_TH}>R</th><th {_TH}>HR</th><th {_TH}>RBI</th><th {_TH}>SB</th>
        <th {_TH}>Summary</th><th {_TH}>News</th><th {_TH}>Pre</th><th {_TH}>YTD</th><th {_TH}>Pace</th>
      </tr></thead>
      <tbody>"""

    # Hitter rows
    total_h, total_ab, total_r, total_hr, total_rbi, total_sb = 0, 0, 0, 0, 0, 0
    total_pre_h, total_ytd_h, total_pace_h = 0.0, 0.0, 0.0

    for r in hitters:
        total_pre_h += r.preseason_pts
        total_ytd_h += r.ytd_pts
        total_pace_h += r.pace_pts

        if r.dnp:
            html += f"""<tr style="color:#aaa">
              <td {_TD}><strong>{r.player_name}</strong></td><td {_TD}>{r.position}</td>
              <td {_TD} colspan="6" style="color:#aaa">DNP</td>
              <td {_TD} style="color:#aaa">DNP</td><td {_TD_NEWS}>{r.news or '—'}</td>
              <td {_TD_R}>{int(r.preseason_pts)}</td><td {_TD_R}>{_fmt_pts(r.ytd_pts)}</td><td {_TD_R}>{_fmt_pts(r.pace_pts)}</td>
            </tr>"""
        else:
            h = int(r.stats.get("H", 0))
            ab = int(r.stats.get("AB", 0))
            runs = int(r.stats.get("R", 0))
            hr = int(r.stats.get("HR", 0))
            rbi = int(r.stats.get("RBI", 0))
            sb = int(r.stats.get("SB", 0))
            total_h += h; total_ab += ab; total_r += runs
            total_hr += hr; total_rbi += rbi; total_sb += sb

            html += f"""<tr>
              <td {_TD}><strong>{r.player_name}</strong></td><td {_TD}>{r.position}</td>
              <td {_TD}>{r.opponent}</td><td {_TD_R}>{h}-{ab}</td>
              <td {_TD_R}>{_fmt(runs)}</td><td {_TD_R}>{_fmt(hr)}</td>
              <td {_TD_R}>{_fmt(rbi)}</td><td {_TD_R}>{_fmt(sb)}</td>
              <td {_TD}>{r.summary or '—'}</td><td {_TD_NEWS}>{r.news or '—'}</td>
              <td {_TD_R}>{int(r.preseason_pts)}</td><td {_TD_R}>{_fmt_pts(r.ytd_pts)}</td><td {_TD_R}>{_fmt_pts(r.pace_pts)}</td>
            </tr>"""

    # Hitter totals
    html += f"""<tr>
      <td {_TOTAL_TD} colspan="3">TOTAL</td>
      <td {_TOTAL_TD_R}>{total_h}-{total_ab}</td>
      <td {_TOTAL_TD_R}>{total_r}</td><td {_TOTAL_TD_R}>{total_hr}</td>
      <td {_TOTAL_TD_R}>{total_rbi}</td><td {_TOTAL_TD_R}>{total_sb}</td>
      <td {_TOTAL_TD}></td><td {_TOTAL_TD}></td>
      <td {_TOTAL_TD_R}>{int(total_pre_h)}</td><td {_TOTAL_TD_R}>{_fmt_pts(total_ytd_h)}</td><td {_TOTAL_TD_R}>{_fmt_pts(total_pace_h)}</td>
    </tr></tbody>
    </table>
  """

    # Pitchers section
    html += f"""
    <h2 style="color:#1a3a5c">Pitchers — {date_short}</h2>
    <p style="color:#999;font-size:11px;margin-top:0">SP: RSAR = (1.2&times;AvgERA &minus; ERA)&times;(IP/9), top 3 &times; 3.5 &middot; RP: 5&times;(W+SV)</p>
    <table style="border-collapse:collapse;width:100%;font-size:13px">
      <thead><tr style="background:#f5f5f5">
        <th {_TH}>Player</th><th {_TH}>Pos</th><th {_TH}>Opp</th>
        <th {_TH}>IP</th><th {_TH}>H</th><th {_TH}>ER</th><th {_TH}>K</th><th {_TH}>BB</th><th {_TH}>Dec</th>
        <th {_TH}>Summary</th><th {_TH}>News</th><th {_TH}>Pre</th><th {_TH}>YTD</th><th {_TH}>Pace</th>
      </tr></thead>
      <tbody>"""

    total_ip, total_ph, total_er, total_k, total_bb = 0.0, 0, 0, 0, 0
    total_pre_p, total_ytd_p, total_pace_p = 0.0, 0.0, 0.0

    for r in pitchers:
        total_pre_p += r.preseason_pts
        total_ytd_p += r.ytd_pts
        total_pace_p += r.pace_pts

        if r.dnp:
            html += f"""<tr style="color:#aaa">
              <td {_TD}><strong>{r.player_name}</strong></td><td {_TD}>{r.position}</td>
              <td {_TD} colspan="7" style="color:#aaa">DNP</td>
              <td {_TD} style="color:#aaa">DNP</td><td {_TD_NEWS}>{r.news or '—'}</td>
              <td {_TD_R}>{_fmt_pts(r.preseason_pts)}</td><td {_TD_R}>{_fmt_pts(r.ytd_pts)}</td><td {_TD_R}>{_fmt_pts(r.pace_pts)}</td>
            </tr>"""
        else:
            ip = r.stats.get("IP", 0.0)
            ph = int(r.stats.get("H", 0))
            er = int(r.stats.get("ER", 0))
            k = int(r.stats.get("K", 0))
            bb = int(r.stats.get("BB", 0))
            total_ip += ip; total_ph += ph; total_er += er
            total_k += k; total_bb += bb

            html += f"""<tr>
              <td {_TD}><strong>{r.player_name}</strong></td><td {_TD}>{r.position}</td>
              <td {_TD}>{r.opponent}</td><td {_TD_R}>{ip}</td>
              <td {_TD_R}>{ph}</td><td {_TD_R}>{er}</td>
              <td {_TD_R}>{k}</td><td {_TD_R}>{bb}</td><td {_TD}>{r.decision or '—'}</td>
              <td {_TD}>{r.summary or '—'}</td><td {_TD_NEWS}>{r.news or '—'}</td>
              <td {_TD_R}>{_fmt_pts(r.preseason_pts)}</td><td {_TD_R}>{_fmt_pts(r.ytd_pts)}</td><td {_TD_R}>{_fmt_pts(r.pace_pts)}</td>
            </tr>"""

    # Pitcher totals
    html += f"""<tr>
      <td {_TOTAL_TD} colspan="3">TOTAL</td>
      <td {_TOTAL_TD_R}>{total_ip}</td>
      <td {_TOTAL_TD_R}>{total_ph}</td><td {_TOTAL_TD_R}>{total_er}</td>
      <td {_TOTAL_TD_R}>{total_k}</td><td {_TOTAL_TD_R}>{total_bb}</td>
      <td {_TOTAL_TD}></td><td {_TOTAL_TD}></td><td {_TOTAL_TD}></td>
      <td {_TOTAL_TD_R}>{_fmt_pts(total_pre_p)}</td><td {_TOTAL_TD_R}>{_fmt_pts(total_ytd_p)}</td><td {_TOTAL_TD_R}>{_fmt_pts(total_pace_p)}</td>
    </tr></tbody>
    </table>
  """

    # Injury Report
    if injured:
        html += f"""<h2 style="color:#1a3a5c">Injury Report</h2>
        <p style="color:#555">{len(injured)} roster player(s) with status changes.</p>
        <table style="border-collapse:collapse;width:100%;font-size:13px">
          <thead><tr style="background:#f5f5f5">
            <th {_TH}>Player</th><th {_TH}>Team &middot; Pos</th>
            <th {_TH}>Previous</th><th {_TH}>Current</th><th {_TH}>Note</th>
          </tr></thead>
          <tbody>"""
        for r in injured:
            html += f"""<tr>
              <td {_TD}><strong>{r.player_name}</strong></td>
              <td {_TD}>{r.team} &middot; {r.position}</td>
              <td {_TD}>{r.injury_prev or '—'}</td><td {_TD}>{r.injury_curr or '—'}</td>
              <td {_TD} style="color:#555;font-size:12px">{r.injury_note}</td>
            </tr>"""
        html += "</tbody></table>"
    else:
        html += '<h2 style="color:#1a3a5c">Injury Report</h2><p style="color:#888">No injury status changes for your roster.</p>'

    # Footer
    html += f"""
  <p style="margin-top:20px;font-size:12px">
    <a href="https://docs.google.com/spreadsheets/d/{config.GOOGLE_SHEET_ID}" style="color:#1a73e8">View rankings sheet &rarr;</a>
    &nbsp;&middot;&nbsp; Pre = preseason projection &nbsp;&middot;&nbsp; YTD = season points to date
    &nbsp;&middot;&nbsp; Pace = 162-game extrapolation
  </p>
</body></html>"""
    return html


def build_subject(report_date: date, day_results: list[DayResult] = None) -> str:
    base = f"{config.REPORT_SUBJECT_PREFIX} — {report_date.strftime('%B %d, %Y')}"
    if day_results:
        played = sum(1 for r in day_results if not r.dnp)
        injured = sum(1 for r in day_results if r.injury_flag)
        base += f" ({played} played, {injured} injury updates)"
    return base
