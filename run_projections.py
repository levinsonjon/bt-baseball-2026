"""
run_projections.py — Entry point: refresh player projections and write to Google Sheets.

Run this daily (or manually) to update the Rankings sheet.

Usage:
    python run_projections.py            # full refresh from Pitcherlist
    python run_projections.py --cache    # use cached projections (faster, no login needed)

NOTE: Writing to Google Sheets requires the mcp__gdrive-personal__gsheets_update_cell
tool, which is only available inside a Claude Code session. If running standalone,
the script prints the data to the terminal and saves to projections_cache.json instead.
"""

import sys
import argparse
from projections import run_projections
from sheets import format_rankings_rows, format_by_position_rows, print_sheet_preview
import config


def main():
    parser = argparse.ArgumentParser(description="Refresh fantasy baseball projections")
    parser.add_argument("--cache", action="store_true", help="Use cached data instead of scraping")
    parser.add_argument("--preview", action="store_true", help="Print preview without writing to Sheets")
    parser.add_argument("--top", type=int, default=30, help="Number of players to preview")
    args = parser.parse_args()

    # Step 1: Get ranked players
    players = run_projections(use_cache=args.cache)

    # Step 2: Format for Sheets
    rankings_rows = format_rankings_rows(players)
    by_pos_data   = format_by_position_rows(players)

    # Step 3: Preview (always shown)
    print(f"\n{'='*60}")
    print(f"RANKINGS PREVIEW (top {args.top})")
    print(f"{'='*60}")
    print_sheet_preview(rankings_rows, max_rows=args.top + 1)  # +1 for header

    if args.preview:
        print("\n[preview mode] Skipping Sheets write.")
        return

    # Step 4: Write to Google Sheets
    # This section requires MCP tools — it's designed to be called from
    # within a Claude Code session. When running standalone, it will print
    # instructions instead.
    sheet_id = config.GOOGLE_SHEET_ID
    if sheet_id == "TODO: paste-sheet-id-here":
        print("\n[WARNING] GOOGLE_SHEET_ID not configured in config.py.")
        print("Create a Google Sheet, copy the ID from the URL, and set it in config.py.")
        print("Data was saved to data/projections_cache.json instead.")
        return

    print(f"\n[sheets] Would write {len(rankings_rows)} rows to sheet '{config.SHEET_RANKINGS}'")
    print(f"[sheets] Sheet ID: {sheet_id}")
    print("\nTo write to Sheets, run this script from within a Claude Code session")
    print("where the mcp__gdrive-personal__gsheets_update_cell tool is available.")
    print("\nAlternatively, Claude Code can call this function directly:")
    print("  from run_projections import get_sheet_write_data")
    print("  data = get_sheet_write_data()")
    print("  # then use MCP tools to write data['rankings'] to the sheet")


def get_sheet_write_data(use_cache: bool = False) -> dict:
    """
    Return formatted data ready for MCP Sheets writes.
    Call this from a Claude Code session.
    """
    players = run_projections(use_cache=use_cache)
    return {
        "rankings": format_rankings_rows(players),
        "by_position": format_by_position_rows(players),
        "players": players,
        "sheet_id": config.GOOGLE_SHEET_ID,
    }


if __name__ == "__main__":
    main()
