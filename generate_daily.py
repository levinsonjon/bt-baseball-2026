"""
generate_daily.py — Fully local/cloud daily report generator.

Pulls everything deterministically from public APIs (no LLM, no web search,
no Gmail drafts):
  - MLB Stats API gameLog  → yesterday's box scores + season totals (every
    slot rebuilt from full-season logs, per player segment — no watermark)
  - ESPN public injuries    → injury report
  - daily_report / config   → scoring, web JSON payloads, HTML email

Writes data/{yesterday,news,season_stats}.json, builds the HTML email, and
(optionally) sends it via Gmail SMTP. Git commit + push is handled by the
caller (the GitHub Actions workflow, or a manual `git push` for catch-up runs).

Designed to run in GitHub Actions on a daily cron — no dependency on Jon's Mac.

Usage:
    python3 generate_daily.py                  # report for yesterday, write files only
    python3 generate_daily.py --date 2026-06-21
    python3 generate_daily.py --send           # also send the email via SMTP
    python3 generate_daily.py --dry-run        # compute + print, write nothing

SMTP send reads two env vars (set as GitHub secrets):
    GMAIL_ADDRESS        the sending Gmail address
    GMAIL_APP_PASSWORD   a Google app password (never expires; not the account password)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

import config
from daily_report import (
    DayResult,
    export_web_data,
    build_html_email,
    build_subject,
    compute_ytd_points,
    compute_pace_points,
    load_season_stats,
    save_season_stats,
)
from update_health import (
    normalize_name,
    _lookup_name,
    load_my_roster,
    resolve_player_ids,
    fetch_espn_injuries,
    generate_day_summary,
)

DATA_DIR = REPO_ROOT / "data"
YESTERDAY_FILE = DATA_DIR / "yesterday.json"
NEWS_FILE = DATA_DIR / "news.json"

# Approximate 2026 MLB opening day — used only for the email's cosmetic "Pace"
# column (the website's projected totals come from projections, not this).
OPENING_DAY = date(2026, 3, 26)

MLB_GAMELOG_URL = (
    "https://statsapi.mlb.com/api/v1/people/{pid}/stats"
    "?stats=gameLog&season={season}&group={group}&gameType=R"
)


def log(msg: str):
    print(f"[generate_daily] {msg}", flush=True)


# ---------------------------------------------------------------------------
# MLB Stats API — gameLog
# ---------------------------------------------------------------------------

def _get_json(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def ip_to_decimal(ip) -> float:
    """Convert baseball innings notation (6.2 = 6 and 2/3) to a true decimal.

    season_stats.json stores true decimals (e.g. 64.67), so all IP math and
    storage uses this form. 6.1 -> 6.333, 6.2 -> 6.667, 6.0 -> 6.0.
    """
    if ip in (None, ""):
        return 0.0
    s = str(ip)
    if "." not in s:
        return float(s)
    whole, frac = s.split(".", 1)
    whole = int(whole) if whole else 0
    outs = int(frac[0]) if frac else 0
    return round(whole + outs / 3.0, 3)


def fetch_gamelog(pid: int, group: str, season: int) -> list[dict]:
    """Return the list of gameLog splits for a player/group, or [] on failure."""
    url = MLB_GAMELOG_URL.format(pid=pid, season=season, group=group)
    try:
        data = _get_json(url)
    except Exception as e:
        log(f"  gameLog fetch failed for {pid}/{group}: {e}")
        return []
    stats = data.get("stats", [])
    if not stats:
        return []
    return stats[0].get("splits", [])


def hitter_day_stats(split: dict) -> dict:
    s = split.get("stat", {})
    return {
        "AB": int(s.get("atBats", 0)),
        "H": int(s.get("hits", 0)),
        "HR": int(s.get("homeRuns", 0)),
        "RBI": int(s.get("rbi", 0)),
        "R": int(s.get("runs", 0)),
        "SB": int(s.get("stolenBases", 0)),
        "BB": int(s.get("baseOnBalls", 0)),
    }


def pitcher_day_stats(split: dict) -> dict:
    s = split.get("stat", {})
    return {
        "IP": round(ip_to_decimal(s.get("inningsPitched", 0)), 2),
        "H": int(s.get("hits", 0)),
        "ER": int(s.get("earnedRuns", 0)),
        "K": int(s.get("strikeOuts", 0)),
        "BB": int(s.get("baseOnBalls", 0)),
        "W": int(s.get("wins", 0)),
        "L": int(s.get("losses", 0)),
        "SV": int(s.get("saves", 0)),
        "GS": int(s.get("gamesStarted", 0)),
    }


def split_opponent(split: dict) -> str:
    opp = split.get("opponent", {}).get("name", "")
    if not opp:
        return ""
    # Compact: prefer team abbreviation if the gameLog provides one upstream.
    is_home = split.get("isHome")
    prefix = "vs" if is_home else "@"
    return f"{prefix} {opp}"


# ---------------------------------------------------------------------------
# Season totals: every slot is rebuilt from full-season gameLogs, one segment
# per player who has occupied the slot (see slot_segments). No watermark, no
# carried-over deltas — a missed or double run can never corrupt a slot.
# ---------------------------------------------------------------------------

def season_totals_from_gamelog(splits: list[dict], player_type: str) -> dict:
    """Aggregate a full-season gameLog into our season_stats schema."""
    if player_type == "hitter":
        tot = {"AB": 0, "H": 0, "HR": 0, "RBI": 0, "R": 0, "SB": 0}
        for sp in splits:
            d = hitter_day_stats(sp)
            for k in tot:
                tot[k] += d[k]
        tot["AVG"] = round(tot["H"] / tot["AB"], 3) if tot["AB"] else 0.0
        return tot
    else:
        ip = er = k = bb = w = sv = g = gs = 0.0
        for sp in splits:
            d = pitcher_day_stats(sp)
            ip += d["IP"]
            er += d["ER"]
            k += d["K"]
            bb += d["BB"]
            w += d["W"]
            sv += d["SV"]
            gs += d["GS"]
            g += 1
        ip = round(ip, 2)
        era = round(er * 9.0 / ip, 2) if ip else 0.0
        out = {"IP": ip, "G": int(g), "GS": int(gs), "ERA": era,
               "K": int(k), "BB": int(bb), "W": int(w)}
        if sv:
            out["SV"] = int(sv)
        return out


def slot_segments(player: dict) -> list[dict]:
    """The (player, from, to) segments that make up a roster slot's season.

    A roster entry may carry `segments`: an ordered list of
    {"player": <full MLB name>, "from": "YYYY-MM-DD" | null, "to": "YYYY-MM-DD" | null}
    covering the season (from=null means opening day, to=null means through
    today). Entries without `segments` are a single player for the whole
    season, using current_player / name as today.
    """
    segs = player.get("segments")
    if segs:
        out = []
        for seg in segs:
            out.append({
                "player": seg["player"],
                "from": date.fromisoformat(seg["from"]) if seg.get("from") else None,
                "to": date.fromisoformat(seg["to"]) if seg.get("to") else None,
            })
        return out
    return [{"player": _lookup_name(player), "from": None, "to": None}]


def _in_segment(d, seg: dict, through: date) -> bool:
    if d is None or d > through:
        return False
    if seg["from"] is not None and d < seg["from"]:
        return False
    if seg["to"] is not None and d > seg["to"]:
        return False
    return True


def season_totals_from_segments(segment_splits: list, player_type: str, through: date) -> dict:
    """Aggregate a slot's season from (segment, gameLog splits) pairs, keeping
    only the games that fall inside each segment's date range and on or before
    `through`. Inclusive on both ends of a segment."""
    kept = []
    for seg, splits in segment_splits:
        kept.extend(sp for sp in splits if _in_segment(_split_date(sp), seg, through))
    return season_totals_from_gamelog(kept, player_type)


def _split_date(split: dict):
    raw = split.get("date")
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Injuries
# ---------------------------------------------------------------------------

def _injury_key(name: str) -> str:
    """Accent-insensitive normalized key for injury matching. ESPN drops
    diacritics (e.g. 'Teoscar Hernandez') while the roster keeps them
    ('Teoscar Hernández'); normalize_name alone preserves accents, so an
    accented roster name would never match. Strip accents on both sides."""
    stripped = "".join(
        c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c)
    )
    return normalize_name(stripped)


def build_injury_lookup() -> dict:
    """accent-insensitive normalized name -> {status, note, team} from ESPN."""
    try:
        raw = fetch_espn_injuries()
    except Exception as e:
        log(f"ESPN injuries fetch failed (continuing without injury report): {e}")
        return {}
    return {_injury_key(name): info for name, info in raw.items()}


def previous_injury_status() -> dict:
    """slot name -> prior status, from the existing news.json (for change notes)."""
    out = {}
    if NEWS_FILE.exists():
        try:
            for inj in json.loads(NEWS_FILE.read_text()).get("injuries", []):
                out[inj.get("name", "")] = inj.get("status", "")
        except Exception:
            pass
    return out


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------

def build_day_results(report_date: date) -> tuple[list[DayResult], dict]:
    roster = load_my_roster()
    season = datetime.now().year
    # Resolve an MLB ID for every player who has occupied any slot this season
    # (not just the current one) so each segment's gameLog can be fetched.
    lookup_entries = [{"name": seg["player"]} for p in roster for seg in slot_segments(p)]
    player_ids = resolve_player_ids(lookup_entries, {})
    injuries = build_injury_lookup()
    prev_inj = previous_injury_status()

    season_stats = load_season_stats()

    team_games = max(1, round((report_date - OPENING_DAY).days * 162 / 186))

    day_results = []
    for p in roster:
        slot = p["name"]
        ptype = p["player_type"]
        lookup = _lookup_name(p)
        segments = slot_segments(p)

        r = DayResult(slot, ptype)
        r.position = p["positions"][0] if p.get("positions") else ""
        r.team = p.get("team", "")
        r.preseason_pts = float(p.get("projected_points", 0) or 0)

        group = "hitting" if ptype == "hitter" else "pitching"
        # One gameLog per segment player; the last segment is the current player.
        segment_splits = []
        for seg in segments:
            pid = player_ids.get(normalize_name(seg["player"]))
            segment_splits.append((seg, fetch_gamelog(pid, group, season) if pid else []))
        splits = segment_splits[-1][1]

        # --- yesterday's box score ---
        day_split = next((s for s in splits if _split_date(s) == report_date), None)
        if day_split is None:
            r.dnp = True
        else:
            if ptype == "hitter":
                r.stats = hitter_day_stats(day_split)
                if r.stats["AB"] == 0 and r.stats["BB"] == 0:
                    r.dnp = True
            else:
                r.stats = pitcher_day_stats(day_split)
                if r.stats["W"]:
                    r.decision = "W"
                elif r.stats["L"]:
                    r.decision = "L"
                elif r.stats["SV"]:
                    r.decision = "SV"
            r.opponent = split_opponent(day_split)
            if not r.dnp:
                r.compute_points()
                r.summary = generate_day_summary(
                    ptype, {"stats": r.stats, "decision": r.decision}
                )

        # --- season totals: authoritative rebuild from the segments' gameLogs ---
        if any(sp for _, sp in segment_splits):
            season_stats[slot] = season_totals_from_segments(segment_splits, ptype, report_date)

        # --- YTD / pace for the email (site is canonical for the website) ---
        slot_season = season_stats.get(slot, {})
        if slot_season:
            r.ytd_pts = compute_ytd_points(slot_season, ptype)
            r.pace_pts = compute_pace_points(slot_season, ptype, team_games)

        # --- injuries ---
        info = injuries.get(_injury_key(lookup))
        if info:
            r.injury_flag = True
            r.injury_curr = info.get("status", "")
            r.injury_prev = prev_inj.get(slot, "")
            r.injury_note = info.get("note", "")
            if r.dnp:
                r.injury_flag = True

        day_results.append(r)

    return day_results, season_stats


def send_email_smtp(subject: str, html: str):
    """Send the report via Gmail SMTP using an app password from env vars.

    Best-effort: logs and returns False on any failure so the data pipeline
    (the real deliverable) is never blocked by an email problem.
    """
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    addr = os.environ.get("GMAIL_ADDRESS")
    pw = os.environ.get("GMAIL_APP_PASSWORD")
    if not addr or not pw:
        log("SMTP send skipped: GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = addr
    msg["To"] = config.REPORT_EMAIL
    msg["Cc"] = ", ".join(config.REPORT_EMAIL_CC)
    msg.attach(MIMEText(html, "html"))
    recipients = [config.REPORT_EMAIL] + config.REPORT_EMAIL_CC

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(addr, pw)
            server.sendmail(addr, recipients, msg.as_string())
        log(f"Sent email to {config.REPORT_EMAIL} (cc {', '.join(config.REPORT_EMAIL_CC)})")
        return True
    except Exception as e:
        log(f"SMTP send FAILED (continuing — data already written): {e}")
        return False


def print_summary(report_date: date, day_results: list[DayResult]):
    log(f"Report for {report_date.isoformat()}:")
    total = 0.0
    for r in day_results:
        total += r.fantasy_points
        if r.dnp:
            line = "DNP"
        elif r.player_type == "hitter":
            s = r.stats
            line = f"{s.get('H',0)}-{s.get('AB',0)} {s.get('HR',0)}HR {s.get('RBI',0)}RBI {s.get('R',0)}R {s.get('SB',0)}SB"
        else:
            s = r.stats
            line = f"{s.get('IP',0)}IP {s.get('ER',0)}ER {s.get('K',0)}K {r.decision}"
        inj = f"  [INJ: {r.injury_curr}]" if r.injury_flag else ""
        print(f"    {r.player_name:22s} {r.position:3s} {line:32s} {r.fantasy_points:+6.2f}{inj}")
    print(f"    {'TEAM TODAY':22s} {'':3s} {'':32s} {total:+6.2f}")


def main():
    ap = argparse.ArgumentParser(description="Generate the daily fantasy baseball report")
    ap.add_argument("--date", help="Report date YYYY-MM-DD (default: yesterday)")
    ap.add_argument("--send", action="store_true", help="Send the email via SMTP")
    ap.add_argument("--dry-run", action="store_true", help="Compute and print only; write nothing")
    args = ap.parse_args()

    report_date = (datetime.strptime(args.date, "%Y-%m-%d").date()
                   if args.date else date.today() - timedelta(days=1))

    log(f"Building report for {report_date.isoformat()}")
    day_results, season_stats = build_day_results(report_date)
    print_summary(report_date, day_results)

    yesterday, news = export_web_data(report_date, day_results)
    # Injury-report-only: no LLM prose blurbs, so the /news headlines list is empty.
    news["players"] = []

    html = build_html_email(report_date, day_results, season_stats)
    subject = build_subject(report_date, day_results)

    if args.dry_run:
        log("Dry run — no files written, no email sent.")
        log(f"Subject: {subject}")
        return

    YESTERDAY_FILE.write_text(json.dumps(yesterday, indent=2, ensure_ascii=False))
    NEWS_FILE.write_text(json.dumps(news, indent=2, ensure_ascii=False))
    save_season_stats(season_stats)
    log(f"Wrote {YESTERDAY_FILE.name}, {NEWS_FILE.name}, season_stats.json")

    if args.send:
        send_email_smtp(subject, html)


if __name__ == "__main__":
    main()
