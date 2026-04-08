"""
sheets.py — Google Sheets read/write helpers.

Uses the personal GDrive MCP server (mcp__gdrive-personal__gsheets_*).
This module is designed to be called from within a Claude Code session
where the MCP tools are available.

NOTE: This file provides helper functions that format data for the Sheets API.
Actual MCP calls are made in the entry-point scripts (run_projections.py, etc.)
because MCP tools can only be invoked from within Claude Code sessions.

For standalone execution, see the _mock_write() functions at the bottom.
"""

from __future__ import annotations
from datetime import datetime
from typing import Any
from players import Player
import config


# ---------------------------------------------------------------------------
# Data formatters — convert Player objects to sheet rows
# ---------------------------------------------------------------------------

def _adjusted_points(p: Player) -> float:
    """
    Compute the scarcity-adjusted projected points for a player.
    Uses the highest scarcity multiplier across all eligible slots.
    This is the effective score used during draft recommendations.
    """
    best = max(
        (config.POSITION_SCARCITY.get(slot, 1.0) for slot in p.eligible_slots()),
        default=1.0,
    )
    return round(p.projected_points * best, 1)


def format_rankings_rows(players: list[Player]) -> list[list[Any]]:
    """
    Format all players for the 'Rankings' tab.
    Returns: list of rows, each row is a list of cell values.
    """
    header = [
        "Rank", "Name", "Team", "Positions", "Type",
        "Proj Points", "Adj Points", "Health", "Injury Note",
        # Hitter stats
        "PA", "HR", "R", "RBI", "SB", "AVG",
        # Pitcher stats
        "IP", "W", "SV", "K", "ERA", "WHIP",
        "Last Updated",
    ]

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = [header]

    for p in players:
        stats = p.projected_stats
        row = [
            p.rank_overall,
            p.name,
            p.team,
            p.position_str,
            p.player_type,
            p.projected_points,
            _adjusted_points(p),
            p.health_status,
            p.injury_note,
            # Hitter stats (blank for pitchers)
            stats.get("PA", "") if p.player_type == "hitter" else "",
            stats.get("HR", "") if p.player_type == "hitter" else "",
            stats.get("R", "")  if p.player_type == "hitter" else "",
            stats.get("RBI", "") if p.player_type == "hitter" else "",
            stats.get("SB", "") if p.player_type == "hitter" else "",
            stats.get("AVG", "") if p.player_type == "hitter" else "",
            # Pitcher stats (blank for hitters)
            stats.get("IP", "") if p.player_type in ("sp", "rp") else "",
            stats.get("W", "")  if p.player_type in ("sp", "rp") else "",
            stats.get("SV", "") if p.player_type in ("sp", "rp") else "",
            stats.get("K", "")  if p.player_type in ("sp", "rp") else "",
            stats.get("ERA", "") if p.player_type in ("sp", "rp") else "",
            stats.get("WHIP", "") if p.player_type in ("sp", "rp") else "",
            now,
        ]
        rows.append(row)

    return rows


def format_by_position_rows(players: list[Player]) -> dict[str, list[list[Any]]]:
    """
    Format players grouped by position for the 'By Position' tab.
    Returns a dict mapping position name → list of rows.
    Each position section gets its own header.
    """
    import config
    from players import rank_by_position
    by_pos = rank_by_position(players)

    output = {}
    header = ["Pos Rank", "Overall Rank", "Name", "Team", "Positions", "Proj Points", "Adj Points", "Health"]

    for slot, slot_players in by_pos.items():
        rows = [["=== " + slot + " ==="], header]
        for p in slot_players[:30]:  # cap at top 30 per position
            rows.append([
                p.rank_by_position.get(slot, ""),
                p.rank_overall,
                p.name,
                p.team,
                p.position_str,
                p.projected_points,
                _adjusted_points(p),
                p.health_status,
            ])
        rows.append([])  # blank separator
        output[slot] = rows

    return output


def format_draft_board_rows(
    players: list[Player],
    drafted_players: set[str],
    my_roster: list[Player],
    open_slots: list[str],
    pick_number: int,
) -> list[list[Any]]:
    """
    Format the draft board for the 'Draft Board' tab.
    Shows Jon's roster on the left, recommendations on the right.
    """
    available = [
        p for p in players
        if p.name not in drafted_players and not p.is_drafted
    ]

    # Build roster panel
    roster_header = ["MY ROSTER", "Position", "Pts"]
    roster_rows = [roster_header]
    for p in my_roster:
        roster_rows.append([p.name, p.position_str, p.projected_points])
    roster_rows.append([])
    roster_rows.append(["OPEN SLOTS:"] + open_slots[:5])

    # Build recommendations panel (top 15 available)
    rec_header = [f"TOP AVAILABLE (Pick #{pick_number})", "Pos", "Pts", "Adj Pts", "Health"]
    rec_rows = [rec_header]
    for p in available[:15]:
        rec_rows.append([p.name, p.position_str, p.projected_points, _adjusted_points(p), p.health_status])

    # Interleave the two panels side by side
    max_len = max(len(roster_rows), len(rec_rows))
    combined = []
    for i in range(max_len):
        left = roster_rows[i] if i < len(roster_rows) else ["", "", ""]
        right = rec_rows[i] if i < len(rec_rows) else ["", "", "", "", ""]
        combined.append(left + [""] + right)  # blank column as separator

    return combined


# ---------------------------------------------------------------------------
# Sheet range helpers
# ---------------------------------------------------------------------------

def col_letter(n: int) -> str:
    """Convert column index (0-based) to letter (A, B, ... Z, AA, ...)."""
    result = ""
    while n >= 0:
        result = chr(n % 26 + ord("A")) + result
        n = n // 26 - 1
    return result


def range_for_rows(rows: list[list], start_row: int = 1, start_col: int = 0) -> str:
    """Return an A1-notation range string for a 2D list of rows."""
    if not rows:
        return "A1"
    num_rows = len(rows)
    num_cols = max(len(r) for r in rows)
    top_left = f"{col_letter(start_col)}{start_row}"
    bot_right = f"{col_letter(start_col + num_cols - 1)}{start_row + num_rows - 1}"
    return f"{top_left}:{bot_right}"


def clear_and_write_instructions(sheet_id: str, tab_name: str, rows: list[list]) -> list[dict]:
    """
    Return a list of MCP gsheets_update_cell call specs needed to write `rows`
    to a given tab.

    Because gsheets_update_cell writes one cell at a time, this generates
    a batch. For very large sheets (300+ players) this is slow — consider
    writing in column blocks or using a direct Sheets API call.

    Returns list of dicts: {"spreadsheet_id", "range", "values"}
    """
    calls = []
    for row_i, row in enumerate(rows):
        for col_i, val in enumerate(row):
            if val == "" or val is None:
                continue
            cell = f"{col_letter(col_i)}{row_i + 1}"
            calls.append({
                "spreadsheet_id": sheet_id,
                "range": f"{tab_name}!{cell}",
                "values": [[str(val)]],
            })
    return calls


def print_sheet_preview(rows: list[list], max_rows: int = 10):
    """Print a preview of sheet data to the terminal."""
    for row in rows[:max_rows]:
        print("\t".join(str(c) for c in row))
    if len(rows) > max_rows:
        print(f"... ({len(rows) - max_rows} more rows)")
