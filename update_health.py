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

CREDS_PATH = os.path.expanduser("~/.config/personal-mcp/gdrive/.gdrive-server-credentials.json")
OAUTH_PATH = os.path.expanduser("~/.config/personal-mcp/gdrive/gcp-oauth.keys.json")

GMAIL_CREDS_PATH = os.path.expanduser("~/.config/personal-mcp/gmail/credentials.json")
GMAIL_OAUTH_PATH = os.path.expanduser("~/.config/personal-mcp/gmail/gcp-oauth.keys.json")
ALERT_EMAIL = "levinson.jon@gmail.com"

# ESPN public injuries API
ESPN_INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/injuries"

# MLB Stats API (public, no auth needed)
MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
MLB_BOXSCORE_URL = "https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"

# Jon's roster file
MY_TEAM_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "my_team.json")

# MLB player ID cache (maps normalized name -> MLB person ID)
MLB_PLAYER_IDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "mlb_player_ids.json")

# MLB people/stats endpoints
MLB_PEOPLE_URL = "https://statsapi.mlb.com/api/v1/people"
MLB_SEARCH_URL = "https://statsapi.mlb.com/api/v1/people/search"
MLB_TRANSACTIONS_URL = "https://statsapi.mlb.com/api/v1/transactions"

# ESPN news
ESPN_NEWS_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/news"

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


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def notify_reauth_needed(reason):
    """Create a persistent macOS Reminder so Jon sees the alert even though
    cron runs while he's asleep. Gmail-based alerts can't be trusted here —
    the failing credential is the Gmail one."""
    reauth_cmd = (
        f"GMAIL_OAUTH_PATH={GMAIL_OAUTH_PATH} "
        f"GMAIL_CREDENTIALS_PATH={GMAIL_CREDS_PATH} "
        f"npx @gongrzhe/server-gmail-autoauth-mcp auth"
    )
    body = f"{reason}\n\nRe-auth command:\n{reauth_cmd}"
    name = "Fantasy Baseball: re-auth Gmail OAuth"
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    script = (
        f'tell application "Reminders" to make new reminder '
        f'with properties {{name:"{esc(name)}", body:"{esc(body)}"}}'
    )
    try:
        subprocess.run(["osascript", "-e", script], check=True, timeout=10,
                       capture_output=True)
        log(f"Created re-auth Reminder: {reason}")
    except Exception as e:
        log(f"WARN: failed to create re-auth Reminder: {e}")


def send_alert_email(subject, body, html=False, cc=True):
    """Send an email via the personal Gmail API. Set html=True for HTML body.
    Set cc=False to skip CC recipients (e.g. for admin-only alerts).
    Returns True on success, False on failure."""
    import base64
    from email.mime.text import MIMEText

    try:
        # Get Gmail token
        with open(GMAIL_CREDS_PATH) as f:
            creds = json.load(f)
        with open(GMAIL_OAUTH_PATH) as f:
            oauth = json.load(f)
            oauth_info = oauth.get("installed", oauth.get("web", oauth))

        now_ms = int(time.time() * 1000)
        if now_ms > creds.get("expiry_date", 0):
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
            with open(GMAIL_CREDS_PATH, "w") as f:
                json.dump(creds, f, indent=2)

        gmail_token = creds["access_token"]

        # Build the message
        msg = MIMEText(body, "html" if html else "plain")
        msg["to"] = ALERT_EMAIL
        msg["from"] = ALERT_EMAIL
        msg["subject"] = subject
        if cc:
            cc_list = getattr(config, "REPORT_EMAIL_CC", [])
            if cc_list:
                msg["cc"] = ", ".join(cc_list)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

        # Send via Gmail API
        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
        req = urllib.request.Request(url, data=json.dumps({"raw": raw}).encode(), method="POST")
        req.add_header("Authorization", f"Bearer {gmail_token}")
        req.add_header("Content-Type", "application/json")
        urllib.request.urlopen(req, timeout=15)
        log("Alert email sent.")
        return True
    except Exception as e:
        log(f"Failed to send alert email: {e}")
        err_str = str(e).lower()
        if any(k in err_str for k in ("invalid_grant", "401", "unauthorized",
                                       "token has been", "refresherror")):
            notify_reauth_needed(f"Gmail send failed: {e}")
        return False


def check_gmail_reauth_needed():
    """
    Check if the Gmail personal MCP refresh token expires tomorrow or sooner.
    Returns a warning message string if re-auth is needed, else None.
    """
    if not os.path.exists(GMAIL_CREDS_PATH):
        return "Gmail credentials file not found — re-auth may be needed now."
    with open(GMAIL_CREDS_PATH) as f:
        creds = json.load(f)
    expiry_ms = creds.get("expiry_date")
    refresh_ttl = creds.get("refresh_token_expires_in")
    if not expiry_ms or not refresh_ttl:
        return None
    access_expires = datetime.fromtimestamp(expiry_ms / 1000)
    authed_at = access_expires - timedelta(hours=1)
    refresh_expires = (authed_at + timedelta(seconds=refresh_ttl)).date()
    days_left = (refresh_expires - datetime.now().date()).days
    if days_left <= 1:
        return (
            f"Gmail personal MCP token expires {'today' if days_left <= 0 else 'tomorrow'} "
            f"(authed {authed_at.strftime('%b %-d')}). "
            f"Re-authenticate to avoid missing tomorrow's email."
        )
    return None


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


def load_my_roster():
    """Load Jon's drafted team from my_team.json."""
    with open(MY_TEAM_FILE) as f:
        data = json.load(f)
    return data.get("players", [])


def fetch_yesterday_boxscores(roster):
    """Fetch yesterday's stats for roster players via MLB Stats API.

    Returns (player_stats dict, display_date, player_ids dict) where player_stats
    maps player name -> {player_type, position, opponent, stats, synopsis} and
    player_ids maps normalized name -> MLB person ID.
    """
    yesterday = datetime.now() - timedelta(days=1)
    date_str = yesterday.strftime("%Y-%m-%d")
    display_date = yesterday.strftime("%b %-d")

    log(f"Fetching MLB boxscores for {date_str}...")

    # 1. Get schedule
    url = f"{MLB_SCHEDULE_URL}?date={date_str}&sportId=1"
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0")
    resp = urllib.request.urlopen(req, timeout=30)
    schedule = json.loads(resp.read())

    game_pks = []
    for date_entry in schedule.get("dates", []):
        for game in date_entry.get("games", []):
            state = game.get("status", {}).get("abstractGameState", "")
            if state == "Final":
                game_pks.append(game["gamePk"])

    if not game_pks:
        log(f"No completed MLB games for {date_str}")
        return {}, display_date, {}

    log(f"Found {len(game_pks)} completed games for {date_str}")

    # Build roster lookup by normalized name
    roster_lookup = {}
    for p in roster:
        roster_lookup[normalize_name(p["name"])] = p

    # 2. Fetch each boxscore, extract roster player stats
    player_stats = {}
    player_ids = {}  # normalized name -> MLB person ID

    for game_pk in game_pks:
        url = MLB_BOXSCORE_URL.format(game_pk=game_pk)
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0")
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            boxscore = json.loads(resp.read())
        except Exception as e:
            log(f"  Failed to fetch boxscore for game {game_pk}: {e}")
            continue

        for side in ("away", "home"):
            team_data = boxscore.get("teams", {}).get(side, {})
            opp_side = "home" if side == "away" else "away"
            opp_abbr = boxscore.get("teams", {}).get(opp_side, {}).get(
                "team", {}
            ).get("abbreviation", "???")

            for pid, pdata in team_data.get("players", {}).items():
                full_name = pdata.get("person", {}).get("fullName", "")
                norm = normalize_name(full_name)

                if norm not in roster_lookup:
                    continue

                rp = roster_lookup[norm]
                mlb_id = pdata.get("person", {}).get("id")
                if mlb_id:
                    player_ids[norm] = mlb_id
                batting = pdata.get("stats", {}).get("batting", {})
                pitching = pdata.get("stats", {}).get("pitching", {})

                if rp["player_type"] == "hitter":
                    ab = int(batting.get("atBats", 0))
                    pa = int(batting.get("plateAppearances", 0))
                    if ab == 0 and pa == 0:
                        continue

                    h = int(batting.get("hits", 0))
                    r = int(batting.get("runs", 0))
                    hr = int(batting.get("homeRuns", 0))
                    rbi = int(batting.get("rbi", 0))
                    sb = int(batting.get("stolenBases", 0))
                    bb = int(batting.get("baseOnBalls", 0))

                    parts = [f"{h}-for-{ab}"]
                    if hr:
                        parts.append(f"{hr} HR")
                    if rbi:
                        parts.append(f"{rbi} RBI")
                    if r:
                        parts.append(f"{r} R")
                    if sb:
                        parts.append(f"{sb} SB")
                    if bb:
                        parts.append(f"{bb} BB")

                    player_stats[rp["name"]] = {
                        "player_type": "hitter",
                        "position": rp["positions"][0] if rp.get("positions") else "",
                        "opponent": opp_abbr,
                        "stats": {
                            "AB": ab, "H": h, "R": r, "HR": hr,
                            "RBI": rbi, "SB": sb, "BB": bb,
                        },
                        "synopsis": f"vs {opp_abbr}: {', '.join(parts)}",
                    }

                elif rp["player_type"] in ("sp", "rp"):
                    ip_str = pitching.get("inningsPitched", "0")
                    ip = float(ip_str) if ip_str else 0.0
                    if ip == 0 and not int(pitching.get("battersFaced", 0)):
                        continue

                    h_allowed = int(pitching.get("hits", 0))
                    er = int(pitching.get("earnedRuns", 0))
                    k = int(pitching.get("strikeOuts", 0))
                    bb_p = int(pitching.get("baseOnBalls", 0))

                    # Decision from note field, e.g. "(W, 1-0)"
                    note = pitching.get("note", "")
                    decision = ""
                    if note:
                        nl = note.lower()
                        if nl.startswith("(w"):
                            decision = "W"
                        elif nl.startswith("(l"):
                            decision = "L"
                        elif nl.startswith("(s"):
                            decision = "SV"
                        elif nl.startswith("(h"):
                            decision = "HLD"
                        elif nl.startswith("(bs"):
                            decision = "BS"

                    parts = [f"{ip_str} IP", f"{k} K", f"{er} ER"]
                    if bb_p:
                        parts.append(f"{bb_p} BB")
                    if h_allowed:
                        parts.append(f"{h_allowed} H")
                    if decision:
                        parts.append(decision)

                    player_stats[rp["name"]] = {
                        "player_type": rp["player_type"],
                        "position": rp["positions"][0] if rp.get("positions") else "",
                        "opponent": opp_abbr,
                        "stats": {
                            "IP": ip, "H": h_allowed, "ER": er, "K": k,
                            "BB": bb_p, "W": 1 if decision == "W" else 0,
                            "L": 1 if decision == "L" else 0,
                            "SV": 1 if decision == "SV" else 0,
                        },
                        "synopsis": f"vs {opp_abbr}: {', '.join(parts)}",
                        "decision": decision,
                    }

    log(f"Found stats for {len(player_stats)} roster players, {len(player_ids)} IDs captured")
    return player_stats, display_date, player_ids


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
        norm = normalize_name(p["name"])
        if norm in boxscore_ids:
            resolved[norm] = boxscore_ids[norm]
            cache[norm] = boxscore_ids[norm]
        elif norm in cache:
            resolved[norm] = cache[norm]
        else:
            to_search.append((norm, p["name"]))

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


def fetch_season_stats(roster, player_ids):
    """Batch-fetch current season stats for all roster players.

    Returns dict: player_name -> {stat_key: value, ...}
    """
    season = datetime.now().year
    all_ids = []
    id_to_name = {}
    for p in roster:
        norm = normalize_name(p["name"])
        mlb_id = player_ids.get(norm)
        if mlb_id:
            all_ids.append(str(mlb_id))
            id_to_name[str(mlb_id)] = p["name"]

    if not all_ids:
        return {}

    # Batch fetch with hydrate — gets both hitting and pitching stats in one call
    ids_str = ",".join(all_ids)
    url = (
        f"{MLB_PEOPLE_URL}?personIds={ids_str}"
        f"&hydrate=stats(group=[hitting,pitching],type=[season],season={season})"
    )
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0")

    try:
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read())
    except Exception as e:
        log(f"Failed to fetch season stats: {e}")
        return {}

    result = {}
    for person in data.get("people", []):
        pid = str(person.get("id", ""))
        name = id_to_name.get(pid)
        if not name:
            continue

        for stat_group in person.get("stats", []):
            splits = stat_group.get("splits", [])
            if splits:
                stat = splits[0].get("stat", {})
                # Merge all stat groups into one dict per player
                if name not in result:
                    result[name] = {}
                result[name].update(stat)

    log(f"Fetched season stats for {len(result)} players")
    return result


# ---------------------------------------------------------------------------
# Point calculations
# ---------------------------------------------------------------------------

def compute_hitter_ytd(stats):
    """Compute hitter fantasy points to date: BA*1000 + HR + RBI + R + SB."""
    ab = int(stats.get("atBats", 0))
    h = int(stats.get("hits", 0))
    ba = h / ab if ab > 0 else 0.0
    hr = int(stats.get("homeRuns", 0))
    rbi = int(stats.get("rbi", 0))
    r = int(stats.get("runs", 0))
    sb = int(stats.get("stolenBases", 0))
    return round(ba * 1000 + hr + rbi + r + sb, 1)


def compute_hitter_pace(stats):
    """Extrapolate hitter points over 162 games (assuming min AB threshold met)."""
    g = int(stats.get("gamesPlayed", 0))
    if g == 0:
        return 0.0
    ab = int(stats.get("atBats", 0))
    h = int(stats.get("hits", 0))
    ba = h / ab if ab > 0 else 0.0
    factor = 162.0 / g
    hr = int(stats.get("homeRuns", 0)) * factor
    rbi = int(stats.get("rbi", 0)) * factor
    r = int(stats.get("runs", 0)) * factor
    sb = int(stats.get("stolenBases", 0)) * factor
    return round(ba * 1000 + hr + rbi + r + sb, 1)


def compute_sp_ytd(stats):
    """Compute SP individual RSAR to date: (1.2*AVG_ERA - ERA) * (IP/9)."""
    ip_raw = stats.get("inningsPitched", "0")
    ip = float(ip_raw) if ip_raw else 0.0
    era_raw = stats.get("era", None)
    if ip == 0 or era_raw is None:
        return 0.0
    era = float(era_raw)
    rsar = (1.2 * config.MLB_AVG_ERA - era) * (ip / 9.0)
    return round(rsar, 1)


def compute_sp_pace(stats):
    """Extrapolate SP RSAR over full season (~32 starts, min IP threshold met)."""
    gs = int(stats.get("gamesStarted", 0))
    ip_raw = stats.get("inningsPitched", "0")
    ip = float(ip_raw) if ip_raw else 0.0
    era_raw = stats.get("era", None)
    if gs == 0 or ip == 0 or era_raw is None:
        return 0.0
    era = float(era_raw)
    ip_per_start = ip / gs
    projected_ip = ip_per_start * 32
    rsar = (1.2 * config.MLB_AVG_ERA - era) * (projected_ip / 9.0)
    return round(rsar, 1)


def compute_rp_ytd(stats):
    """Compute RP points to date: 5 * (W + SV)."""
    w = int(stats.get("wins", 0))
    sv = int(stats.get("saves", 0))
    return round(5.0 * (w + sv), 1)


def compute_rp_pace(stats):
    """Extrapolate RP points over full season (~65 appearances)."""
    g = int(stats.get("gamesPlayed", 0))
    if g == 0:
        return 0.0
    w = int(stats.get("wins", 0))
    sv = int(stats.get("saves", 0))
    factor = 65.0 / g
    return round(5.0 * (w * factor + sv * factor), 1)


def compute_points(player_type, stats):
    """Compute (ytd_points, pace_points) for a player based on type."""
    if player_type == "hitter":
        return compute_hitter_ytd(stats), compute_hitter_pace(stats)
    elif player_type == "sp":
        return compute_sp_ytd(stats), compute_sp_pace(stats)
    elif player_type == "rp":
        return compute_rp_ytd(stats), compute_rp_pace(stats)
    return 0.0, 0.0


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
# Player news
# ---------------------------------------------------------------------------

def fetch_player_news(roster, injuries):
    """Fetch recent news for roster players.

    Sources (in priority order — later sources overwrite earlier):
      1. ESPN general news feed (matched by player full name)
      2. ESPN injury notes (from already-fetched injuries dict)
      3. MLB transactions API (roster moves, IL placements)

    Returns dict: player_name -> short news string.
    """
    news = {}
    roster_lookup = {}  # normalized name -> roster player name
    for p in roster:
        roster_lookup[normalize_name(p["name"])] = p["name"]

    # 1. ESPN general news — scan headlines for roster player names
    try:
        url = f"{ESPN_NEWS_URL}?limit=80"
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0")
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())

        for article in data.get("articles", []):
            headline = article.get("headline", "")
            description = article.get("description", "")
            text = f"{headline} {description}"

            for norm, real_name in roster_lookup.items():
                if real_name in news:
                    continue
                # Match on full name (case-insensitive)
                if real_name.lower() in text.lower():
                    news[real_name] = headline[:100]
    except Exception as e:
        log(f"  ESPN news fetch failed: {e}")

    # 2. ESPN injury notes (already fetched) — overwrite with more specific info
    for espn_name, info in injuries.items():
        norm = normalize_name(espn_name)
        if norm in roster_lookup and info.get("note"):
            note = info["note"]
            if note and note.lower() not in ("unknown",):
                news[roster_lookup[norm]] = note[:120]

    # 3. MLB transactions (last 2 days) — highest priority
    try:
        yesterday = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
        today_str = datetime.now().strftime("%Y-%m-%d")
        url = f"{MLB_TRANSACTIONS_URL}?startDate={yesterday}&endDate={today_str}"
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0")
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())

        for txn in data.get("transactions", []):
            person = txn.get("person", {})
            name = person.get("fullName", "")
            norm = normalize_name(name)
            if norm in roster_lookup:
                desc = txn.get("description", "")
                if desc:
                    news[roster_lookup[norm]] = desc[:120]
    except Exception as e:
        log(f"  MLB transactions fetch failed: {e}")

    log(f"Found news for {len(news)} roster players")
    return news


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


# Status display labels
STATUS_LABELS = {
    "healthy":      "✅ Healthy",
    "day-to-day":   "⚠️ Day-to-Day",
    "probable":     "🟡 Probable",
    "questionable": "🟠 Questionable",
    "IL-10":        "🔴 10-Day IL",
    "IL-60":        "🔴 60-Day IL",
    "IL-season":    "❌ Out/Season",
    "unknown":      "❓ Unknown",
}


def send_daily_email(roster, changes, yesterday_stats, game_date_display,
                     season_stats, player_news):
    """Send combined daily email with hitter/pitcher tables + injury updates."""
    today = datetime.now().strftime("%B %d, %Y")
    sheet_url = f"https://docs.google.com/spreadsheets/d/{config.GOOGLE_SHEET_ID}"

    # Shared table styles
    TH = 'style="padding:6px 10px;text-align:left;border-bottom:2px solid #ddd;white-space:nowrap"'
    TD = 'style="padding:5px 10px;border-bottom:1px solid #eee"'
    TD_NUM = 'style="padding:5px 10px;border-bottom:1px solid #eee;text-align:right"'
    TD_DNP = 'style="padding:5px 10px;border-bottom:1px solid #eee;color:#aaa"'
    TD_NEWS = 'style="padding:5px 10px;border-bottom:1px solid #eee;font-size:11px;color:#555;max-width:180px"'
    TD_TOT = 'style="padding:6px 10px;border-top:2px solid #1a3a5c;font-weight:bold;background:#e8f0fe"'
    TD_TOT_NUM = 'style="padding:6px 10px;border-top:2px solid #1a3a5c;font-weight:bold;background:#e8f0fe;text-align:right"'

    # Filter injury changes to team-only
    team_names = {normalize_name(p["name"]) for p in roster}
    team_changes = [c for c in changes if normalize_name(c["name"]) in team_names]

    # --- Hitters table ---
    hitters = [p for p in roster if p["player_type"] == "hitter"]
    hitter_rows = ""
    tot_h = tot_ab = tot_r = tot_hr = tot_rbi = tot_sb = 0
    tot_pre = tot_ytd = tot_pace = 0.0

    for p in hitters:
        name = p["name"]
        pos = p["positions"][0] if p.get("positions") else ""
        day = yesterday_stats.get(name)
        ss = season_stats.get(name, {})
        pre_proj = p.get("projected_points", 0)
        ytd, pace = compute_points("hitter", ss)
        summary = generate_day_summary("hitter", day)
        news = player_news.get(name, "\u2014")

        tot_pre += pre_proj
        tot_ytd += ytd
        tot_pace += pace

        if day:
            s = day["stats"]
            tot_h += s["H"]; tot_ab += s["AB"]; tot_r += s["R"]
            tot_hr += s["HR"]; tot_rbi += s["RBI"]; tot_sb += s["SB"]
            line = f'{s["H"]}-{s["AB"]}'
            r_val = str(s["R"]) if s["R"] else "\u2014"
            hr_val = str(s["HR"]) if s["HR"] else "\u2014"
            rbi_val = str(s["RBI"]) if s["RBI"] else "\u2014"
            sb_val = str(s["SB"]) if s["SB"] else "\u2014"
            opp = f'vs {day["opponent"]}'
            hitter_rows += f"""<tr>
              <td {TD}><strong>{name}</strong></td><td {TD}>{pos}</td>
              <td {TD}>{opp}</td><td {TD_NUM}>{line}</td>
              <td {TD_NUM}>{r_val}</td><td {TD_NUM}>{hr_val}</td>
              <td {TD_NUM}>{rbi_val}</td><td {TD_NUM}>{sb_val}</td>
              <td {TD}>{summary}</td><td {TD_NEWS}>{news}</td>
              <td {TD_NUM}>{pre_proj:.0f}</td><td {TD_NUM}>{ytd:.1f}</td><td {TD_NUM}>{pace:.1f}</td>
            </tr>"""
        else:
            hitter_rows += f"""<tr style="color:#aaa">
              <td {TD}><strong>{name}</strong></td><td {TD}>{pos}</td>
              <td {TD_DNP} colspan="6">DNP</td>
              <td {TD_DNP}>{summary}</td><td {TD_NEWS}>{news}</td>
              <td {TD_NUM}>{pre_proj:.0f}</td><td {TD_NUM}>{ytd:.1f}</td><td {TD_NUM}>{pace:.1f}</td>
            </tr>"""

    # Total row
    hitter_rows += f"""<tr>
      <td {TD_TOT} colspan="3">TOTAL</td>
      <td {TD_TOT_NUM}>{tot_h}-{tot_ab}</td>
      <td {TD_TOT_NUM}>{tot_r}</td><td {TD_TOT_NUM}>{tot_hr}</td>
      <td {TD_TOT_NUM}>{tot_rbi}</td><td {TD_TOT_NUM}>{tot_sb}</td>
      <td {TD_TOT}></td><td {TD_TOT}></td>
      <td {TD_TOT_NUM}>{tot_pre:.0f}</td><td {TD_TOT_NUM}>{tot_ytd:.1f}</td><td {TD_TOT_NUM}>{tot_pace:.1f}</td>
    </tr>"""

    hitters_html = f"""
    <h2 style="color:#1a3a5c">Hitters \u2014 {game_date_display}</h2>
    <p style="color:#999;font-size:11px;margin-top:0">Scoring: BA&times;1000 + HR + RBI + R + SB (300 AB min)</p>
    <table style="border-collapse:collapse;width:100%;font-size:13px">
      <thead><tr style="background:#f5f5f5">
        <th {TH}>Player</th><th {TH}>Pos</th><th {TH}>Opp</th>
        <th {TH}>H/AB</th><th {TH}>R</th><th {TH}>HR</th><th {TH}>RBI</th><th {TH}>SB</th>
        <th {TH}>Summary</th><th {TH}>News</th><th {TH}>Pre</th><th {TH}>YTD</th><th {TH}>Pace</th>
      </tr></thead>
      <tbody>{hitter_rows}</tbody>
    </table>"""

    # --- Pitchers table ---
    pitchers = [p for p in roster if p["player_type"] in ("sp", "rp")]
    pitcher_rows = ""
    ptot_ip = ptot_h = ptot_er = ptot_k = ptot_bb = 0.0
    # Collect individual SP/RP values for team scoring formula
    sp_pre_vals = []
    sp_ytd_vals = []
    sp_pace_vals = []
    rp_pre = rp_ytd = rp_pace = 0.0

    for p in pitchers:
        name = p["name"]
        pos = p["positions"][0] if p.get("positions") else ""
        ptype = p["player_type"]
        day = yesterday_stats.get(name)
        ss = season_stats.get(name, {})
        pre_proj = p.get("projected_points", 0)
        ytd, pace = compute_points(ptype, ss)
        summary = generate_day_summary(ptype, day)
        news = player_news.get(name, "\u2014")

        if ptype == "sp":
            sp_pre_vals.append(pre_proj)
            sp_ytd_vals.append(ytd)
            sp_pace_vals.append(pace)
        else:  # rp
            rp_pre = pre_proj
            rp_ytd = ytd
            rp_pace = pace

        if day:
            s = day["stats"]
            ptot_ip += s.get("IP", 0); ptot_h += s.get("H", 0)
            ptot_er += s.get("ER", 0); ptot_k += s.get("K", 0)
            ptot_bb += s.get("BB", 0)
            ip_val = s.get("IP", 0)
            ip_display = f'{ip_val:.1f}' if ip_val != int(ip_val) else f'{int(ip_val)}.0'
            k_val = str(s.get("K", 0))
            er_val = str(s.get("ER", 0))
            h_val = str(s.get("H", 0))
            bb_val = str(s.get("BB", 0))
            dec = day.get("decision", "") or "\u2014"
            opp = f'vs {day["opponent"]}'
            pitcher_rows += f"""<tr>
              <td {TD}><strong>{name}</strong></td><td {TD}>{pos}</td>
              <td {TD}>{opp}</td><td {TD_NUM}>{ip_display}</td>
              <td {TD_NUM}>{h_val}</td><td {TD_NUM}>{er_val}</td>
              <td {TD_NUM}>{k_val}</td><td {TD_NUM}>{bb_val}</td><td {TD}>{dec}</td>
              <td {TD}>{summary}</td><td {TD_NEWS}>{news}</td>
              <td {TD_NUM}>{pre_proj:.1f}</td><td {TD_NUM}>{ytd:.1f}</td><td {TD_NUM}>{pace:.1f}</td>
            </tr>"""
        else:
            pitcher_rows += f"""<tr style="color:#aaa">
              <td {TD}><strong>{name}</strong></td><td {TD}>{pos}</td>
              <td {TD_DNP} colspan="7">DNP</td>
              <td {TD_DNP}>{summary}</td><td {TD_NEWS}>{news}</td>
              <td {TD_NUM}>{pre_proj:.1f}</td><td {TD_NUM}>{ytd:.1f}</td><td {TD_NUM}>{pace:.1f}</td>
            </tr>"""

    # Total row — team scoring: top 3 SP RSAR * 3.5 + RP points
    top3_pre = sum(sorted(sp_pre_vals, reverse=True)[:3])
    top3_ytd = sum(sorted(sp_ytd_vals, reverse=True)[:3])
    top3_pace = sum(sorted(sp_pace_vals, reverse=True)[:3])
    ptot_pre = top3_pre * config.SP_RSAR_MULTIPLIER + rp_pre
    ptot_ytd = top3_ytd * config.SP_RSAR_MULTIPLIER + rp_ytd
    ptot_pace = top3_pace * config.SP_RSAR_MULTIPLIER + rp_pace

    ip_tot_display = f'{ptot_ip:.1f}'
    pitcher_rows += f"""<tr>
      <td {TD_TOT} colspan="3">TOTAL</td>
      <td {TD_TOT_NUM}>{ip_tot_display}</td>
      <td {TD_TOT_NUM}>{int(ptot_h)}</td><td {TD_TOT_NUM}>{int(ptot_er)}</td>
      <td {TD_TOT_NUM}>{int(ptot_k)}</td><td {TD_TOT_NUM}>{int(ptot_bb)}</td>
      <td {TD_TOT}></td><td {TD_TOT}></td><td {TD_TOT}></td>
      <td {TD_TOT_NUM}>{ptot_pre:.1f}</td><td {TD_TOT_NUM}>{ptot_ytd:.1f}</td><td {TD_TOT_NUM}>{ptot_pace:.1f}</td>
    </tr>"""

    scoring_note = "SP: RSAR = (1.2&times;AvgERA \u2212 ERA)&times;(IP/9), top 3 &times; 3.5 &middot; RP: 5&times;(W+SV)"
    pitchers_html = f"""
    <h2 style="color:#1a3a5c">Pitchers \u2014 {game_date_display}</h2>
    <p style="color:#999;font-size:11px;margin-top:0">{scoring_note}</p>
    <table style="border-collapse:collapse;width:100%;font-size:13px">
      <thead><tr style="background:#f5f5f5">
        <th {TH}>Player</th><th {TH}>Pos</th><th {TH}>Opp</th>
        <th {TH}>IP</th><th {TH}>H</th><th {TH}>ER</th><th {TH}>K</th><th {TH}>BB</th><th {TH}>Dec</th>
        <th {TH}>Summary</th><th {TH}>News</th><th {TH}>Pre</th><th {TH}>YTD</th><th {TH}>Pace</th>
      </tr></thead>
      <tbody>{pitcher_rows}</tbody>
    </table>"""

    # --- Injury section (team-only) ---
    injury_html = '<h2 style="color:#1a3a5c">Injury Report</h2>'
    if team_changes:
        team_changes_sorted = sorted(
            team_changes, key=lambda c: 1 if c["new_status"] == "healthy" else 0
        )
        inj_rows = ""
        for c in team_changes_sorted:
            old_label = STATUS_LABELS.get(c["old_status"], c["old_status"])
            new_label = STATUS_LABELS.get(c["new_status"], c["new_status"])
            note = c["note"] or "\u2014"
            inj_rows += f"""<tr>
              <td {TD}><strong>{c['name']}</strong></td>
              <td {TD}>{c['team']} \u00b7 {c['pos']}</td>
              <td {TD}>{old_label}</td><td {TD}>{new_label}</td>
              <td {TD} style="color:#555;font-size:12px">{note}</td>
            </tr>"""
        injury_html += f"""
        <p style="color:#555">{len(team_changes)} roster player(s) with status changes.</p>
        <table style="border-collapse:collapse;width:100%;font-size:13px">
          <thead><tr style="background:#f5f5f5">
            <th {TH}>Player</th><th {TH}>Team \u00b7 Pos</th>
            <th {TH}>Previous</th><th {TH}>Current</th><th {TH}>Note</th>
          </tr></thead>
          <tbody>{inj_rows}</tbody>
        </table>"""
    else:
        injury_html += '<p style="color:#888">No injury status changes for your roster.</p>'

    # --- Combine ---
    html = f"""
<html><body style="font-family:Arial,sans-serif;color:#222;max-width:1100px;margin:0 auto">
  <h1 style="color:#1a3a5c;border-bottom:2px solid #1a3a5c;padding-bottom:6px">Fantasy Baseball Daily \u2014 {today}</h1>
  {hitters_html}
  {pitchers_html}
  {injury_html}
  <p style="margin-top:20px;font-size:12px">
    <a href="{sheet_url}" style="color:#1a73e8">View rankings sheet \u2192</a>
    &nbsp;&middot;&nbsp; Pre = preseason projection &nbsp;&middot;&nbsp; YTD = season points to date
    &nbsp;&middot;&nbsp; Pace = 162-game extrapolation
  </p>
</body></html>"""

    played_count = len(yesterday_stats)
    ok = send_alert_email(
        f"Fantasy Baseball Daily \u2014 {today} ({played_count} played, {len(team_changes)} injury updates)",
        html,
        html=True,
    )
    if ok:
        log(f"Daily email sent ({played_count} played, {len(team_changes)} injury changes).")
    else:
        log(f"Daily email FAILED to send ({played_count} played, {len(team_changes)} injury changes) - see 'Failed to send alert email' above.")


def main():
    log("=" * 50)
    log("Starting daily fantasy baseball update...")

    try:
        # Load Jon's roster
        roster = load_my_roster()
        log(f"Loaded roster: {len(roster)} players")

        # Update health/injury data in the full Rankings sheet
        token = get_token()
        injuries = fetch_espn_injuries()
        sheet_players = read_sheet_players(token)
        changes = match_and_update(sheet_players, injuries, token)

        # Fetch yesterday's box scores for roster players
        yesterday_stats, game_date_display, boxscore_ids = fetch_yesterday_boxscores(roster)

        # Resolve MLB player IDs and fetch season stats
        player_ids = resolve_player_ids(roster, boxscore_ids)
        season_stats = fetch_season_stats(roster, player_ids)

        # Fetch player news (ESPN news + MLB transactions + injury notes)
        player_news = fetch_player_news(roster, injuries)

        # Send combined daily email (performance + season context + news + injuries)
        send_daily_email(roster, changes or [], yesterday_stats, game_date_display,
                         season_stats, player_news)

        # Check if Gmail personal MCP token needs re-auth soon
        reauth_msg = check_gmail_reauth_needed()
        if reauth_msg:
            log(f"REAUTH WARNING: {reauth_msg}")
            notify_reauth_needed(reauth_msg)

        log("Daily update complete.")
    except Exception as e:
        log(f"ERROR: {e}")
        err_str = str(e).lower()
        if any(k in err_str for k in ("token", "401", "unauthorized", "invalid_grant", "expired")):
            notify_reauth_needed(f"Daily update failed (auth error): {e}")
        raise


if __name__ == "__main__":
    main()
