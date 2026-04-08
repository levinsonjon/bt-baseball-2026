"""
push_to_sheets.py — Push rankings to Google Sheets using the Sheets API directly.

Run from terminal (not inside Claude Code sandbox):
    python3 push_to_sheets.py

Requires: openpyxl (pip3 install openpyxl)
Uses the existing gdrive OAuth credentials (no extra packages needed).
"""

import json
import urllib.request
import urllib.error
import urllib.parse
import time
import socket
import subprocess

# ---------------------------------------------------------------------------
# DNS fallback: if the system resolver fails, resolve via nslookup and cache
# ---------------------------------------------------------------------------
_original_getaddrinfo = socket.getaddrinfo
_dns_cache: dict = {}


def _fallback_getaddrinfo(host, port, *args, **kwargs):
    try:
        return _original_getaddrinfo(host, port, *args, **kwargs)
    except socket.gaierror:
        # System resolver failed — try nslookup as fallback
        cache_key = (host, port)
        if cache_key not in _dns_cache:
            try:
                result = subprocess.run(
                    ["nslookup", host], capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.splitlines():
                    if line.strip().startswith("Address:") and "." in line:
                        ip = line.split(":", 1)[1].strip().split("#")[0]
                        if ip and not ip.startswith("8.8"):  # skip the DNS server line
                            _dns_cache[cache_key] = ip
                            break
            except Exception:
                pass
        if cache_key in _dns_cache:
            ip = _dns_cache[cache_key]
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, port or 443))]
        raise


socket.getaddrinfo = _fallback_getaddrinfo
import sys
import os

# Add project dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config

CREDS_PATH = os.path.expanduser("~/.config/personal-mcp/gdrive/.gdrive-server-credentials.json")
OAUTH_PATH = os.path.expanduser("~/.config/personal-mcp/gdrive/gcp-oauth.keys.json")


def get_token():
    """Get a valid access token, refreshing if needed."""
    with open(CREDS_PATH) as f:
        creds = json.load(f)
    with open(OAUTH_PATH) as f:
        oauth = json.load(f)
        oauth_info = oauth.get("installed", oauth.get("web", oauth))

    now_ms = int(time.time() * 1000)
    if now_ms > creds.get("expiry_date", 0):
        print("Refreshing OAuth token...")
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
        print("Token refreshed.")

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
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"API error {e.code}: {error_body[:500]}")
        raise


def main():
    from projections import run_projections
    from sheets import format_rankings_rows, format_by_position_rows
    import config

    token = get_token()
    sheet_id = config.GOOGLE_SHEET_ID

    # Get existing tabs
    print("Fetching spreadsheet info...")
    info = sheets_api(sheet_id, "", token=token)
    existing_tabs = [s["properties"]["title"] for s in info.get("sheets", [])]
    print(f"Existing tabs: {existing_tabs}")

    # Create tabs if needed
    tabs_needed = [config.SHEET_RANKINGS, config.SHEET_BY_POS]
    requests = []
    for tab in tabs_needed:
        if tab not in existing_tabs:
            requests.append({"addSheet": {"properties": {"title": tab}}})
    if requests:
        new_tabs = [r["addSheet"]["properties"]["title"] for r in requests]
        print(f"Creating tabs: {new_tabs}")
        sheets_api(sheet_id, ":batchUpdate", method="POST", body={"requests": requests}, token=token)

    # Run projections
    print("\nRunning projections...")
    players = run_projections()

    # --- Rankings tab ---
    rankings_rows = format_rankings_rows(players)
    tab = config.SHEET_RANKINGS
    print(f"\nClearing '{tab}' tab...")
    sheets_api(sheet_id, f"/values/'{tab}'!A:Z:clear", method="POST", body={}, token=token)

    print(f"Writing '{tab}' tab ({len(rankings_rows)} rows)...")
    body = {
        "valueInputOption": "RAW",
        "data": [{
            "range": f"'{tab}'!A1",
            "majorDimension": "ROWS",
            "values": [[str(v) if v is not None else "" for v in row] for row in rankings_rows],
        }],
    }
    result = sheets_api(sheet_id, "/values:batchUpdate", method="POST", body=body, token=token)
    print(f"  Updated {result.get('totalUpdatedCells', '?')} cells")

    # --- By Position tab ---
    by_pos = format_by_position_rows(players)
    all_pos_rows = []
    for slot_rows in by_pos.values():
        all_pos_rows.extend(slot_rows)

    tab = config.SHEET_BY_POS
    print(f"\nClearing '{tab}' tab...")
    sheets_api(sheet_id, f"/values/'{tab}'!A:Z:clear", method="POST", body={}, token=token)

    print(f"Writing '{tab}' tab ({len(all_pos_rows)} rows)...")
    body = {
        "valueInputOption": "RAW",
        "data": [{
            "range": f"'{tab}'!A1",
            "majorDimension": "ROWS",
            "values": [[str(v) if v is not None else "" for v in row] for row in all_pos_rows],
        }],
    }
    result = sheets_api(sheet_id, "/values:batchUpdate", method="POST", body=body, token=token)
    print(f"  Updated {result.get('totalUpdatedCells', '?')} cells")

    # --- Draft Board tab (pre-draft: empty roster, all players available) ---
    from draft import DraftMonitor
    monitor = DraftMonitor(players=players, pick_number=config.DRAFT_PICK)
    push_draft_board(monitor, players)

    print("\nDone! Rankings pushed to Google Sheets.")
    print(f"https://docs.google.com/spreadsheets/d/{sheet_id}")


def _get_tab_sheet_ids(token):
    """Return a dict mapping tab name -> integer sheetId."""
    info = sheets_api(config.GOOGLE_SHEET_ID, "", token=token)
    return {
        s["properties"]["title"]: s["properties"]["sheetId"]
        for s in info.get("sheets", [])
    }


def _find_player_rows(tab_name, name_col, player_name, token):
    """
    Read all values in the name column of a tab and return 0-indexed row numbers
    where the player name matches (case-insensitive, stripped).
    """
    col_letter = chr(ord("A") + name_col)
    range_str = f"'{tab_name}'!{col_letter}:{col_letter}"
    # Use the values endpoint with the range in the path (no extra quoting)
    url = (f"https://sheets.googleapis.com/v4/spreadsheets/{config.GOOGLE_SHEET_ID}"
           f"/values/{urllib.parse.quote(range_str, safe='!:')}")
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read())
    rows = data.get("values", [])
    needle = player_name.lower().strip()
    matches = []
    for i, row in enumerate(rows):
        if row and row[0].lower().strip() == needle:
            matches.append(i)
    return matches


def _format_row_request(sheet_id, row_index, num_cols, is_mine):
    """
    Build a batchUpdate request to strikethrough and color a row.
    Green (#d9ead3) for Jon's picks, red (#f4cccc) for opponents.
    """
    bg = {"red": 0.85, "green": 0.92, "blue": 0.83} if is_mine \
        else {"red": 0.96, "green": 0.80, "blue": 0.80}
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": row_index,
                "endRowIndex": row_index + 1,
                "startColumnIndex": 0,
                "endColumnIndex": num_cols,
            },
            "cell": {
                "userEnteredFormat": {
                    "textFormat": {"strikethrough": True},
                    "backgroundColor": bg,
                }
            },
            "fields": "userEnteredFormat(textFormat.strikethrough,backgroundColor)",
        }
    }


def mark_drafted_player(player_name, is_mine):
    """
    Strikethrough and highlight a drafted player's row(s) in the Rankings
    and By Position tabs.

    Args:
        player_name: Player name as it appears in the sheet
        is_mine: True if Jon drafted the player (green), False for opponents (red)
    """
    token = get_token()
    tab_ids = _get_tab_sheet_ids(token)

    requests = []

    # Rankings tab: name in column B (index 1), 21 columns wide
    rankings_tab = config.SHEET_RANKINGS
    if rankings_tab in tab_ids:
        rows = _find_player_rows(rankings_tab, 1, player_name, token)
        for row_idx in rows:
            requests.append(_format_row_request(tab_ids[rankings_tab], row_idx, 21, is_mine))

    # By Position tab: name in column C (index 2), 8 columns wide
    by_pos_tab = config.SHEET_BY_POS
    if by_pos_tab in tab_ids:
        rows = _find_player_rows(by_pos_tab, 2, player_name, token)
        for row_idx in rows:
            requests.append(_format_row_request(tab_ids[by_pos_tab], row_idx, 8, is_mine))

    if requests:
        sheets_api(config.GOOGLE_SHEET_ID, ":batchUpdate", method="POST",
                   body={"requests": requests}, token=token)
        color = "green" if is_mine else "red"
        print(f"[draft] Marked {player_name} as drafted ({color}) — "
              f"{len(requests)} row(s) formatted")
    else:
        print(f"[draft] Warning: {player_name} not found in Rankings or By Position tabs")


def push_draft_board(monitor, players):
    """
    Push live draft board (roster + recommendations) to a 'Draft Board' tab
    on the rankings sheet. Called after each poll cycle during the draft.

    Args:
        monitor: DraftMonitor instance with current state
        players: Full ranked player list
    """
    token = get_token()
    sheet_id = config.GOOGLE_SHEET_ID
    tab = "Draft Board"

    # Ensure tab exists
    info = sheets_api(sheet_id, "", token=token)
    existing_tabs = [s["properties"]["title"] for s in info.get("sheets", [])]
    if tab not in existing_tabs:
        sheets_api(sheet_id, ":batchUpdate", method="POST",
                   body={"requests": [{"addSheet": {"properties": {"title": tab}}}]},
                   token=token)

    # Build the board
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    next_pick = monitor.next_my_pick()
    picks_away = monitor.picks_until_mine()
    open_slots = monitor.roster.open_slots()
    recs = monitor.get_recommendations(top_n=15)

    rows = []
    # Status header
    rows.append([f"DRAFT BOARD — Updated {now}"])
    rows.append([f"Total picks: {monitor.current_overall_pick}",
                 "",
                 f"Jon's next pick: #{next_pick}" if next_pick else "Draft complete",
                 "",
                 f"{picks_away} picks away" if picks_away < 999 else ""])
    rows.append([])

    # Jon's roster (left) + Recommendations (right)
    rows.append(["MY ROSTER", "Position", "Type", "Pts", "",
                 "RECOMMENDATIONS", "Position", "Type", "Pts", "Adj Pts", "Health", "Fills Need?"])

    roster_players = monitor.roster.players
    max_len = max(len(roster_players), len(recs), 1)
    urgent = set(open_slots)

    for i in range(max_len):
        left = ["", "", "", ""]
        if i < len(roster_players):
            p = roster_players[i]
            left = [p.name, p.position_str, p.player_type, round(p.projected_points, 1)]

        right = ["", "", "", "", "", "", ""]
        if i < len(recs):
            p, adj = recs[i]
            fills = "YES" if any(s in urgent for s in p.eligible_slots()) else ""
            right = [p.name, p.position_str, p.player_type,
                     round(p.projected_points, 1), adj, p.health_status, fills]

        rows.append(left + [""] + right)

    # SP pair recommendation
    sp_rec = monitor.get_sp_pair_recommendation()
    if sp_rec:
        rows.append([])
        rows.append(["BEST SP PAIR", "", "", "", "",
                     "SP1", "SP2", "Combined RSAR",
                     "This Pair Adds", f"Total SP Value ({sp_rec['pairs_remaining']} pairs left)",
                     "Health"])
        rows.append(["", "", "", "", "",
                     sp_rec["sp1"].name,
                     sp_rec["sp2"].name,
                     sp_rec["pair_rsar"],
                     f"{sp_rec['pair_team_pts']} pts",
                     f"{sp_rec['total_sp_pts']} pts",
                     sp_rec["health"]])

    # Open slots
    rows.append([])
    rows.append(["OPEN SLOTS:"] + open_slots)

    # Clear and write
    sheets_api(sheet_id, f"/values/'{tab}'!A:Z:clear", method="POST", body={}, token=token)
    body = {
        "valueInputOption": "RAW",
        "data": [{
            "range": f"'{tab}'!A1",
            "majorDimension": "ROWS",
            "values": [[str(v) if v is not None else "" for v in row] for row in rows],
        }],
    }
    result = sheets_api(sheet_id, "/values:batchUpdate", method="POST", body=body, token=token)
    print(f"[draft] Draft Board pushed ({result.get('totalUpdatedCells', '?')} cells)")


if __name__ == "__main__":
    main()
