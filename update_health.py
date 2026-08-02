"""
update_health.py — Daily job to update player health/injury status in Google Sheets.

Fetches MLB injury data from ESPN's public API, matches players in the
Rankings tab, and updates columns G (Health) and H (Injury Note).

Run standalone:
    python3 update_health.py

Designed to be called from crontab daily.
"""

import json
import urllib.request
import urllib.error
import urllib.parse
import subprocess
import time
import sys
import os
import re
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config

# Drive/Sheets OAuth. Prefer a dedicated `gdrive-fb/` client if one exists,
# exactly as GMAIL_* below prefers `gmail-fb/`, and fall back to the shared
# `gdrive/` folder until that client is created.
#
# Sharing `gdrive/` with the gdrive-personal MCP server is what broke this
# script: concurrent refreshes trip Google's rotation-revocation policy, so the
# token works whenever Jon is using Claude and is dead again by the 3:13am
# cron. Every run failed at get_token() with HTTP 400 from 2026-07-08 (last
# "Updated 72 cells") through 2026-08-01 — 24 days of no Sheets update — while
# an on-demand refresh always succeeded, which is why it looked healthy.
#
# To finish the fix (mirrors the 2026-05-12 Gmail split): create a second
# OAuth client ID (Desktop app) in GCP project personal-claude-mcp-486922,
# save it to ~/.config/personal-mcp/gdrive-fb/gcp-oauth.keys.json, and run the
# auth flow. This module picks it up automatically — no code change needed.
_GDRIVE_FB = os.path.expanduser("~/.config/personal-mcp/gdrive-fb")
_GDRIVE_SHARED = os.path.expanduser("~/.config/personal-mcp/gdrive")
_GDRIVE_DIR = _GDRIVE_FB if os.path.exists(
    os.path.join(_GDRIVE_FB, "gcp-oauth.keys.json")
) else _GDRIVE_SHARED

CREDS_PATH = os.path.join(_GDRIVE_DIR, ".gdrive-server-credentials.json")
OAUTH_PATH = os.path.join(_GDRIVE_DIR, "gcp-oauth.keys.json")
GDRIVE_REAUTH_CMD = f"node {os.path.join(_GDRIVE_DIR, 'auth.mjs')}"

# There is deliberately no Gmail credential here. This script stopped sending
# mail on 2026-08-02, and its weekly Gmail re-auth check went with it the same
# day: nothing in the active pipeline uses that token, so the Reminder
# was nagging Jon to renew a credential only the retired send_pending_email.py
# would need. Drive/Sheets (above) is the only OAuth credential this job holds.

# ESPN public injuries API
ESPN_INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/injuries"

# Jon's roster file
MY_TEAM_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "my_team.json")

# Pipeline freshness check: data/yesterday.json watermark file
YESTERDAY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "yesterday.json")
STALE_THRESHOLD_HOURS = 36

# MLB player ID cache (maps normalized name -> MLB person ID)
MLB_PLAYER_IDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "mlb_player_ids.json")

# MLB player-name lookup, used by search_mlb_player_id()
MLB_SEARCH_URL = "https://statsapi.mlb.com/api/v1/people/search"

# Map ESPN injury status to our health_status values (from config.PLAYING_TIME_DISCOUNTS)
# ESPN uses hyphenated forms like "60-Day-IL", "10-Day-IL", "Day-To-Day"
ESPN_STATUS_MAP = {
    "10-day-il":       "IL-10",
    "15-day-il":       "IL-10",
    "60-day-il":       "IL-60",
    "out":             "IL-season",
    "out for season":  "IL-season",
    "day-to-day":      "day-to-day",
    "probable":        "probable",
    "questionable":    "questionable",
    "suspension":      "IL-season",
}

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "health_update.log")

from log_rotation import rotate as _rotate_log

_rotate_log(LOG_PATH)


def log(msg):
    """Append one timestamped line to LOG_PATH.

    Echo to stdout only when attached to a terminal. The launchd plist points
    both StandardOutPath and StandardErrorPath at LOG_PATH, so an unconditional
    print() wrote every line to the file twice — which is half of why this log
    reached 1.2 MB, and made single runs look like duplicate ones. Tracebacks
    still land in the file via the stderr redirect.
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    if sys.stdout.isatty():
        print(line)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def create_reminder(title, body):
    """Create a persistent macOS Reminder so Jon sees the alert even though
    cron runs while he's asleep.

    Email is deliberately not the channel: everything this raises is either a
    broken credential or a broken pipeline, which are exactly the conditions
    under which an emailed warning wouldn't arrive. 60s osascript timeout —
    10s was too tight for a cold-wake cron and every alert during the 5/8-12
    outage silently timed out.
    """
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    script = (
        f'tell application "Reminders" to make new reminder '
        f'with properties {{name:"{esc(title)}", body:"{esc(body)}"}}'
    )
    try:
        subprocess.run(["osascript", "-e", script], check=True, timeout=60,
                       capture_output=True)
        log(f"Created Reminder — {title}: {body.splitlines()[0]}")
    except Exception as e:
        log(f"WARN: failed to create Reminder '{title}': {e}")


def _watermark_from_json(text):
    """Parse a yesterday.json payload into a date, or None."""
    try:
        date_str = json.loads(text).get("date")
        return datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else None
    except (json.JSONDecodeError, ValueError, AttributeError):
        return None


def _remote_watermark():
    """yesterday.json's date as of origin/main, or None if git/network fails.

    The GitHub Actions pipeline commits data straight to origin every morning
    and nothing pulls it down here, so the working copy routinely sits days
    behind while the site is perfectly current — on 2026-08-01 the local file
    was 12 days stale and the alert fired even though the pipeline was healthy.
    Checking only the working copy makes this alarm permanently false, which is
    worse than not having it.

    Best-effort by design: this runs before any other network step so that a
    DNS or OAuth failure can't silence the alert (see the 2026-05-04
    hardening), and every failure path here falls back to the local file.
    """
    import subprocess
    try:
        subprocess.run(
            ["git", "fetch", "--quiet", "origin", "main"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True, timeout=30, check=False,
        )
        out = subprocess.run(
            ["git", "show", "origin/main:data/yesterday.json"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True, timeout=30, check=False,
        )
        if out.returncode == 0:
            return _watermark_from_json(out.stdout.decode())
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def check_pipeline_freshness():
    """Compare data/yesterday.json's date to today. If >36h stale, the daily
    pipeline has silently failed for at least one cycle — fire a Reminder so
    Jon notices before the lag piles up. Since 2026-07-13 the pipeline is the
    GitHub Actions run, so that is where the cause almost always is.

    Keep the message's cause list current. When it still led with "Likely
    Gmail OAuth revoked" the real cause (empty DATA drafts) went unaddressed
    for two weeks even though this Reminder fired every single morning.

    Reads the newer of the local working copy and origin/main, because either
    can legitimately be ahead: Actions pushes to origin without pulling here,
    and a manual local run can write data before it is pushed.
    """
    try:
        with open(YESTERDAY_FILE) as f:
            local = _watermark_from_json(f.read())
    except (FileNotFoundError, OSError) as e:
        log(f"Pipeline freshness check: local yesterday.json unreadable ({e})")
        local = None

    remote = _remote_watermark()
    candidates = [w for w in (local, remote) if w is not None]
    if not candidates:
        log("Pipeline freshness check skipped: no readable watermark")
        return
    watermark = max(candidates)
    if remote is not None and local is not None and remote != local:
        log(f"Watermark: local {local}, origin/main {remote} — using {watermark}")

    expected = (datetime.now() - timedelta(days=1)).date()
    age_days = (expected - watermark).days
    if age_days <= 0:
        return  # fresh
    age_hours = age_days * 24
    if age_hours < STALE_THRESHOLD_HOURS:
        return  # within tolerance

    msg = (
        f"data/yesterday.json watermark is {age_days} day(s) behind "
        f"(file shows {watermark}, expected {expected}). The daily pipeline "
        f"hasn't pushed since then. Causes, in likelihood order: "
        f"(1) the GitHub Actions run is failing or was disabled — "
        f"`gh run list --workflow=daily.yml` and read the newest log; "
        f"(2) generate_daily.py is erroring on upstream data (MLB Stats API "
        f"or ESPN shape change) — reproduce with `python3 generate_daily.py "
        f"--dry-run`; (3) the push step is failing — check the run log for a "
        f"403 or a rejected non-fast-forward. Re-run with "
        f"`gh workflow run daily.yml` once fixed."
    )
    log(f"PIPELINE STALE: {msg}")
    create_reminder("Fantasy Baseball: daily pipeline is stale", msg)


def get_token():
    """Get a valid access token, refreshing if needed."""
    with open(CREDS_PATH) as f:
        creds = json.load(f)
    with open(OAUTH_PATH) as f:
        oauth = json.load(f)
        oauth_info = oauth.get("installed", oauth.get("web", oauth))

    now_ms = int(time.time() * 1000)
    if now_ms > creds.get("expiry_date", 0):
        log("Refreshing OAuth token...")
        data = urllib.parse.urlencode({
            "client_id": oauth_info["client_id"],
            "client_secret": oauth_info["client_secret"],
            "refresh_token": creds["refresh_token"],
            "grant_type": "refresh_token",
        }).encode()
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
        resp = urllib.request.urlopen(req, timeout=15)
        new_tokens = json.loads(resp.read())
        creds["access_token"] = new_tokens["access_token"]
        creds["expiry_date"] = int(time.time() * 1000) + new_tokens.get("expires_in", 3600) * 1000
        with open(CREDS_PATH, "w") as f:
            json.dump(creds, f, indent=2)

    return creds["access_token"]


def sheets_api(sheet_id, endpoint, method="GET", body=None, token=None):
    """Make a Google Sheets API call."""
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}{urllib.parse.quote(endpoint, safe='/:!?=&')}"
    if body:
        data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
    else:
        req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())


def fetch_espn_injuries():
    """Fetch current MLB injury data from ESPN's public API."""
    log("Fetching ESPN injury data...")
    req = urllib.request.Request(ESPN_INJURIES_URL)
    req.add_header("User-Agent", "Mozilla/5.0")
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read())

    injuries = {}  # player_name -> {"status": str, "note": str}

    for team_data in data.get("injuries", []):
        team_name = team_data.get("displayName", "???")
        for injury in team_data.get("injuries", []):
            athlete = injury.get("athlete", {})
            name = athlete.get("displayName", "").strip()
            if not name:
                continue

            status_raw = injury.get("status", "Unknown")
            detail = injury.get("shortComment", "") or injury.get("longComment", "")

            health = ESPN_STATUS_MAP.get(status_raw.lower(), "unknown")

            injuries[name] = {
                "status": health,
                "note": f"{status_raw}: {detail}" if detail else status_raw,
                "team": team_name,
            }

    log(f"Found {len(injuries)} injured players from ESPN")
    return injuries


def normalize_name(name):
    """Normalize player name for matching (lowercase, strip suffixes/punctuation)."""
    name = name.lower().strip()
    name = re.sub(r'\s+(jr\.?|sr\.?|ii|iii|iv)$', '', name)
    name = re.sub(r'[.\'-]', '', name)
    return name


def _lookup_name(p):
    """Real MLB player name for external lookups (boxscore, MLB ID, ESPN news).
    Falls back to the slot name. Differs from p["name"] only when a slot has
    been mid-season-swapped (e.g. "Lindor/McGonigle" → "Kevin McGonigle")."""
    return p.get("current_player") or p["name"]


def load_my_roster():
    """Load Jon's drafted team from my_team.json."""
    with open(MY_TEAM_FILE) as f:
        data = json.load(f)
    return data.get("players", [])


# ---------------------------------------------------------------------------
# Player ID resolution + season stats
# ---------------------------------------------------------------------------

def load_player_id_cache():
    """Load cached MLB player ID mappings."""
    if os.path.exists(MLB_PLAYER_IDS_FILE):
        with open(MLB_PLAYER_IDS_FILE) as f:
            return json.load(f)
    return {}


def save_player_id_cache(cache):
    """Save MLB player ID cache."""
    with open(MLB_PLAYER_IDS_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def search_mlb_player_id(player_name):
    """Look up a player's MLB ID via the search API."""
    encoded = urllib.parse.quote(player_name)
    url = f"{MLB_SEARCH_URL}?names={encoded}&sportId=1&active=true"
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0")
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        people = data.get("people", [])
        if people:
            return people[0]["id"]
    except Exception as e:
        log(f"  MLB search failed for '{player_name}': {e}")
    return None


def resolve_player_ids(roster, boxscore_ids):
    """Ensure all roster players have MLB IDs. Uses cache, boxscore data, and search."""
    cache = load_player_id_cache()
    resolved = {}
    to_search = []

    for p in roster:
        lookup = _lookup_name(p)
        norm = normalize_name(lookup)
        if norm in boxscore_ids:
            resolved[norm] = boxscore_ids[norm]
            cache[norm] = boxscore_ids[norm]
        elif norm in cache:
            resolved[norm] = cache[norm]
        else:
            to_search.append((norm, lookup))

    for norm, name in to_search:
        mlb_id = search_mlb_player_id(name)
        if mlb_id:
            resolved[norm] = mlb_id
            cache[norm] = mlb_id
            log(f"  Resolved MLB ID for {name}: {mlb_id}")
        else:
            log(f"  WARNING: Could not resolve MLB ID for {name}")

    save_player_id_cache(cache)
    log(f"Resolved {len(resolved)}/{len(roster)} MLB player IDs")
    return resolved


# ---------------------------------------------------------------------------
# Point calculations
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Day summary generation
# ---------------------------------------------------------------------------

def generate_day_summary(player_type, day_stats):
    """Generate a short 1-line narrative summary of yesterday's performance."""
    if day_stats is None:
        return "DNP"

    if player_type == "hitter":
        s = day_stats["stats"]
        ab, h, hr, rbi = s["AB"], s["H"], s["HR"], s["RBI"]
        r, sb, bb = s["R"], s["SB"], s["BB"]

        if ab == 0:
            return f"No AB ({bb} BB)" if bb else "No at-bats"

        highlights = []
        if hr >= 2:
            highlights.append(f"Multi-HR game ({hr})")
        elif hr == 1:
            highlights.append("Went deep")
        if rbi >= 3:
            highlights.append(f"drove in {rbi}")
        elif rbi and not hr:
            highlights.append(f"{rbi} RBI")
        if sb >= 2:
            highlights.append(f"swiped {sb} bags")
        elif sb == 1:
            highlights.append("stole a base")
        if r >= 3:
            highlights.append(f"scored {r}")

        if h == 0:
            base = f"0-for-{ab}"
            if bb >= 2:
                base += f", drew {bb} walks"
            return base

        if highlights:
            return "; ".join(highlights)
        if h >= 3:
            return f"{h}-hit game"
        if h == 2:
            return "Multi-hit day"
        return f"{h}-for-{ab}"

    else:  # pitcher (sp or rp)
        s = day_stats["stats"]
        ip = s.get("IP", 0)
        k = s.get("K", 0)
        er = s.get("ER", 0)
        dec = day_stats.get("decision", "")

        parts = []
        if dec == "W":
            parts.append("Earned the W")
        elif dec == "L":
            parts.append("Took the L")
        elif dec == "SV":
            parts.append("Nailed down the save")

        if ip >= 6 and er <= 3 and dec != "L":
            parts.append("quality start")
        elif ip < 4 and player_type == "sp":
            parts.append("short outing")

        if k >= 10:
            parts.append(f"dominant {k} K")
        elif k >= 7:
            parts.append(f"{k} K")

        if er == 0:
            parts.append("scoreless")
        elif er >= 5:
            parts.append(f"{er} ER allowed")

        return "; ".join(parts) if parts else f"{ip} IP, {k} K, {er} ER"


# ---------------------------------------------------------------------------
# Rankings sheet update
# ---------------------------------------------------------------------------

def apply_injuries_to_players(players):
    """
    Fetch ESPN injury data and apply health_status/injury_note to Player objects.
    Call this before computing projected points so scores reflect injuries.
    Returns the injuries dict for logging/reporting.
    """
    injuries = fetch_espn_injuries()
    injury_lookup = {}
    for name, info in injuries.items():
        injury_lookup[normalize_name(name)] = (name, info)

    updated = 0
    for p in players:
        norm = normalize_name(p.name)
        match = injury_lookup.get(norm)
        if match:
            _, info = match
            p.health_status = info["status"]
            p.injury_note = info["note"]
            updated += 1
        else:
            p.health_status = "healthy"
            p.injury_note = ""

    print(f"[health] Applied injury data to {updated} players from ESPN")
    return injuries


def read_sheet_players(token):
    """Read player names from the Rankings tab (column B, starting at row 2)."""
    log("Reading current Rankings tab...")
    sheet_id = config.GOOGLE_SHEET_ID
    result = sheets_api(
        sheet_id,
        f"/values/'{config.SHEET_RANKINGS}'!B2:I",
        token=token,
    )
    rows = result.get("values", [])
    log(f"Found {len(rows)} players in sheet")
    return rows  # each row: [Name, Team, Positions, Type, ProjPts, AdjPts, Health, InjuryNote]


def match_and_update(sheet_players, injuries, token):
    """Match injured players to sheet rows and batch-update Health + Injury Note."""
    sheet_id = config.GOOGLE_SHEET_ID

    # Build a normalized lookup for injury data
    injury_lookup = {}
    for name, info in injuries.items():
        injury_lookup[normalize_name(name)] = (name, info)

    updates = []  # list of {"range": str, "values": [[health, note]]}
    changes = []  # list of dicts for summary email
    cleared = 0
    updated = 0

    for i, row in enumerate(sheet_players):
        sheet_row = i + 2  # 1-indexed, skip header
        player_name = row[0] if len(row) > 0 else ""
        player_team = row[1] if len(row) > 1 else ""
        player_pos = row[2] if len(row) > 2 else ""
        current_health = row[6] if len(row) > 6 else "healthy"
        current_note = row[7] if len(row) > 7 else ""

        norm = normalize_name(player_name)
        match = injury_lookup.get(norm)

        if match:
            _, info = match
            new_health = info["status"]
            new_note = info["note"]
        else:
            # Player not on injury list — mark healthy
            new_health = "healthy"
            new_note = ""

        if new_health != current_health or new_note != current_note:
            updates.append({
                "range": f"'{config.SHEET_RANKINGS}'!H{sheet_row}:I{sheet_row}",
                "values": [[new_health, new_note]],
            })
            changes.append({
                "name": player_name,
                "team": player_team,
                "pos": player_pos,
                "old_status": current_health,
                "new_status": new_health,
                "note": new_note,
            })
            if new_health == "healthy" and current_health != "healthy":
                cleared += 1
                log(f"  CLEARED: {player_name} ({current_health} -> healthy)")
            elif new_health != "healthy":
                updated += 1
                log(f"  INJURY: {player_name} -> {new_health} ({new_note})")

    if not updates:
        log("No changes needed.")
        return changes

    log(f"Updating {len(updates)} rows ({updated} injuries, {cleared} cleared)...")

    # Batch update
    body = {
        "valueInputOption": "RAW",
        "data": updates,
    }
    result = sheets_api(
        sheet_id,
        "/values:batchUpdate",
        method="POST",
        body=body,
        token=token,
    )
    log(f"Updated {result.get('totalUpdatedCells', '?')} cells")

    # Also update the "Last Updated" column (column T) for changed rows
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    ts_updates = []
    for u in updates:
        # Extract row number from range like "'Rankings'!G5:H5"
        row_num = u["range"].split("!")[1].split(":")[0].replace("H", "")
        ts_updates.append({
            "range": f"'{config.SHEET_RANKINGS}'!T{row_num}",
            "values": [[ts]],
        })

    if ts_updates:
        sheets_api(
            sheet_id,
            "/values:batchUpdate",
            method="POST",
            body={"valueInputOption": "RAW", "data": ts_updates},
            token=token,
        )

    return changes


def main():
    log("=" * 50)
    log("Starting daily fantasy baseball update...")

    # Run the pipeline freshness check first — it's local-only (no network)
    # and must fire even if downstream steps crash on DNS/OAuth/etc.
    try:
        check_pipeline_freshness()
    except Exception as e:
        log(f"WARN: pipeline freshness check failed: {e}")

    try:
        # Update health/injury data in the full Rankings sheet.
        #
        # This script does NOT send the daily report email. It used to, via its
        # own send_daily_email(), which quietly kept running after 960ce85 moved
        # the email to GitHub Actions — so on 2026-08-02 Jon got two reports,
        # one at 4:17am from here and one at 6:49am from Actions. Actions is now
        # the sole sender (it's cloud-side, so it doesn't depend on this Mac
        # being awake). Keep it that way.
        token = get_token()
        injuries = fetch_espn_injuries()
        sheet_players = read_sheet_players(token)
        match_and_update(sheet_players, injuries, token)

        log("Daily update complete.")
    except Exception as e:
        log(f"ERROR: {e}")
        err_str = str(e).lower()
        if any(k in err_str for k in ("token", "401", "unauthorized", "invalid_grant", "expired")):
            # Drive/Sheets is the only credential this job holds — get_token()
            # is what raises here. It used to print a Gmail re-auth command,
            # which was the wrong fix for the credential that actually failed.
            create_reminder(
                "Fantasy Baseball: re-auth Drive/Sheets OAuth",
                f"Daily update failed (auth error): {e}\n\n"
                f"Re-auth command:\n{GDRIVE_REAUTH_CMD}",
            )
        raise


if __name__ == "__main__":
    main()
