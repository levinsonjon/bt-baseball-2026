"""
run_draft.py — Entry point: launch the draft day monitor.

Run this on draft day (March 30, 2026) AFTER confirming:
  - Jon's pick number in config.py (DRAFT_PICK = 9)
  - The draft tracker sheet ID in config.py (DRAFT_TRACKER_SHEET_ID)

Usage (from Claude Code session):
    python run_draft.py              # live mode — polls tracker sheet via MCP
    python run_draft.py --cache      # live mode, skip projection recalc
    python run_draft.py --test       # offline simulation with test CSV

The draft tracker is the official league Google Sheet (roster grid format):
  - Column A: position labels, Columns B-J: team owners
  - Player names are filled in as picks are made
  - Jon's column: "Levinsons" (column J)

NOTE: Live mode requires mcp__gdrive-personal__gsheets_read (Claude Code session).
"""

import sys
import time
import argparse
import csv
from pathlib import Path

from projections import run_projections
from draft import DraftMonitor, POLL_INTERVAL_SECONDS
import config

TEST_DRAFT_CSV = Path(__file__).parent / "data" / "test_draft_picks.csv"


def main():
    parser = argparse.ArgumentParser(description="Draft day monitor")
    parser.add_argument("--pick", type=int, help="Jon's draft pick number (1-indexed)")
    parser.add_argument("--test", action="store_true", help="Use test CSV instead of live sheet")
    parser.add_argument("--cache", action="store_true", help="Use cached projections")
    args = parser.parse_args()

    # Resolve pick number
    pick_number = args.pick or config.DRAFT_PICK
    if not pick_number:
        print("ERROR: Draft pick number not set.")
        print("Either set DRAFT_PICK in config.py or pass --pick N")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  FANTASY BASEBALL DRAFT MONITOR")
    print(f"  Jon's pick: #{pick_number} of {config.LEAGUE_SIZE}")
    print(f"  Tracker sheet: {config.DRAFT_TRACKER_SHEET_ID}")
    print(f"  Jon's column: {config.JON_TEAM_NAME}")
    print(f"{'='*60}\n")

    # Load projections
    print("[draft] Loading player projections...")
    players = run_projections(use_cache=args.cache)
    print(f"[draft] Loaded {len(players)} ranked players.\n")

    # Initialize monitor
    monitor = DraftMonitor(players=players, pick_number=pick_number)

    if args.test:
        _run_test_mode(monitor)
    else:
        _run_live_mode(monitor)


def _run_live_mode(monitor: DraftMonitor):
    """
    Poll the draft tracker sheet. Designed to be run from a Claude Code session
    where the gsheets_read MCP tool is available.

    In practice, Claude Code orchestrates the polling loop:
      1. Calls gsheets_read on the tracker sheet
      2. Passes the response to monitor.run_once_grid(mcp_data)
      3. Displays recommendations to Jon
      4. Waits POLL_INTERVAL_SECONDS and repeats
    """
    print(f"[draft] Draft tracker sheet: {config.DRAFT_TRACKER_SHEET_ID}")
    print(f"[draft] Tab: {config.DRAFT_TRACKER_TAB}")
    print(f"[draft] Jon's team: {config.JON_TEAM_NAME}")
    print(f"[draft] Poll interval: {POLL_INTERVAL_SECONDS}s")
    print()
    print("[draft] Ready for live draft polling.")
    print("[draft] Claude Code will poll the tracker sheet and call")
    print("[draft]   monitor.run_once_grid(mcp_data)")
    print("[draft] to process each cycle.")
    print()
    print("[draft] To start: ask Claude to begin polling the draft tracker.")


def _run_test_mode(monitor: DraftMonitor):
    """Simulate a draft using test_draft_picks.csv."""
    if not TEST_DRAFT_CSV.exists():
        _create_test_csv()

    print(f"[draft] TEST MODE — reading picks from {TEST_DRAFT_CSV}")
    print(f"[draft] Simulating picks with a 1-second delay...\n")

    all_rows = []
    with open(TEST_DRAFT_CSV, newline="") as f:
        reader = csv.reader(f)
        next(reader, None)  # skip header
        all_rows = list(reader)

    # Feed picks one at a time
    for i, row in enumerate(all_rows):
        time.sleep(1)
        state = monitor.run_once([row])
        if i < len(all_rows) - 1 and state["picks_until_mine"] <= 3:
            print(f"  >> Jon picks in {state['picks_until_mine']} picks — make your selection!")

    print("\n[draft] Draft simulation complete.")
    monitor.save_roster()


def _create_test_csv():
    """Create a sample test draft CSV for simulation."""
    sample_picks = [
        ["pick", "player", "team"],
        ["1", "Ronald Acuna Jr.", "Team A"],
        ["2", "Mookie Betts", "Team B"],
        ["3", "Freddie Freeman", "Team C"],
        ["4", "Trea Turner", "Team D"],
        ["5", "Yordan Alvarez", "Jon"],
        ["6", "Aaron Judge", "Team F"],
        ["7", "Julio Rodriguez", "Team G"],
        ["8", "Juan Soto", "Team H"],
        ["9", "Spencer Strider", "Team I"],
        ["10", "Marcus Semien", "Team I"],
        ["11", "Paul Goldschmidt", "Team H"],
        ["12", "Jose Altuve", "Team G"],
        ["13", "Mike Trout", "Team F"],
        ["14", "Austin Riley", "Jon"],
    ]
    TEST_DRAFT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(TEST_DRAFT_CSV, "w", newline="") as f:
        csv.writer(f).writerows(sample_picks)
    print(f"[draft] Created test CSV at {TEST_DRAFT_CSV}")


if __name__ == "__main__":
    main()
