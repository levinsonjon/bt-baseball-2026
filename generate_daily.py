"""
generate_daily.py — Fully local/cloud daily report generator.

Pulls everything deterministically from public APIs (no LLM, no web search,
no Gmail drafts):
  - MLB Stats API gameLog  → yesterday's box scores + season totals
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
# Season totals (non-swapped) and swap-delta accumulation (swapped slots)
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


def apply_swap_deltas(prior: dict, splits: list[dict], player_type: str,
                      after: date, through: date) -> dict:
    """Add the current player's gameLog deltas for (after, through] onto the
    prior carryover total. Recompute AVG / ERA. Used for mid-season-swapped
    slots so pre-swap games (folded into `prior`) are never double-counted.

    Self-healing: the date range covers every gap day, so a missed run is
    recovered on the next run rather than lost forever.
    """
    out = dict(prior)
    if player_type == "hitter":
        for sp in splits:
            d = _split_date(sp)
            if d is None or not (after < d <= through):
                continue
            day = hitter_day_stats(sp)
            for k in ("AB", "H", "HR", "RBI", "R", "SB"):
                out[k] = out.get(k, 0) + day[k]
        if out.get("AB"):
            out["AVG"] = round(out["H"] / out["AB"], 3)
        return out
    else:
        # Derive stored earned runs from the stored ERA/IP, add daily deltas.
        ip = float(out.get("IP", 0.0))
        er = out.get("ERA", 0.0) * ip / 9.0
        for sp in splits:
            d = _split_date(sp)
            if d is None or not (after < d <= through):
                continue
            day = pitcher_day_stats(sp)
            ip += day["IP"]
            er += day["ER"]
            out["K"] = out.get("K", 0) + day["K"]
            out["BB"] = out.get("BB", 0) + day["BB"]
            out["W"] = out.get("W", 0) + day["W"]
            if day["SV"]:
                out["SV"] = out.get("SV", 0) + day["SV"]
            out["G"] = out.get("G", 0) + 1
            out["GS"] = out.get("GS", 0) + day["GS"]
        out["IP"] = round(ip, 2)
        out["ERA"] = round(er * 9.0 / ip, 2) if ip else 0.0
        return out


def _split_date(split: dict):
    raw = split.get("date")
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def previous_watermark() -> date | None:
    """The last date already folded into season_stats — read from the existing
    yesterday.json. Used as the lower bound for swap-delta accumulation."""
    if YESTERDAY_FILE.exists():
        try:
            d = json.loads(YESTERDAY_FILE.read_text()).get("date")
            return date.fromisoformat(d) if d else None
        except Exception:
            return None
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
    player_ids = resolve_player_ids(roster, {})
    injuries = build_injury_lookup()
    prev_inj = previous_injury_status()

    season_stats = load_season_stats()
    watermark = previous_watermark()
    # Lower bound for swap deltas: everything strictly after `watermark` and
    # up to report_date. If no watermark, only count report_date itself.
    delta_after = watermark if watermark is not None else (report_date - timedelta(days=1))

    team_games = max(1, round((report_date - OPENING_DAY).days * 162 / 186))

    day_results = []
    for p in roster:
        slot = p["name"]
        ptype = p["player_type"]
        lookup = _lookup_name(p)
        norm = normalize_name(lookup)
        pid = player_ids.get(norm)
        swapped = bool(p.get("current_player")) and "/" in slot

        r = DayResult(slot, ptype)
        r.position = p["positions"][0] if p.get("positions") else ""
        r.team = p.get("team", "")
        r.preseason_pts = float(p.get("projected_points", 0) or 0)

        group = "hitting" if ptype == "hitter" else "pitching"
        splits = fetch_gamelog(pid, group, season) if pid else []

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

        # --- season totals ---
        if swapped:
            prior = season_stats.get(slot, {})
            season_stats[slot] = apply_swap_deltas(
                prior, splits, ptype, after=delta_after, through=report_date
            )
        elif splits:
            new_tot = season_totals_from_gamelog(splits, ptype)
            # Guardrail: never let counting stats regress (self-heal a missed run).
            old = season_stats.get(slot, {})
            for k in ("AB", "H", "HR", "RBI", "R", "SB", "K", "BB", "W", "SV", "G", "GS"):
                if k in new_tot and k in old and new_tot[k] < old[k]:
                    new_tot[k] = old[k]
            season_stats[slot] = new_tot

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
