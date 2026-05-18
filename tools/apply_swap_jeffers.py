#!/usr/bin/env python3
"""
One-shot swap: Cal Raleigh → Ryan Jeffers (C), effective 2026-05-18.

Run Monday May 18 AFTER the morning pipeline completes (~5:30am ET).
Idempotent: safe to re-run.

What it does:
1. Replace the Cal Raleigh entry in data/my_team.json with the composite
   "Raleigh/Jeffers" entry (current_player="Ryan Jeffers", MIN, projected_points=0).
2. Rename the "Cal Raleigh" key in data/season_stats.json to "Raleigh/Jeffers",
   carrying Raleigh's existing totals forward as the slot's starting balance.
3. Commit and push both files to origin/main.
"""
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MY_TEAM = REPO_ROOT / "data" / "my_team.json"
SEASON  = REPO_ROOT / "data" / "season_stats.json"

NEW_SLOT_NAME = "Raleigh/Jeffers"
OLD_SLOT_NAME = "Cal Raleigh"
NEW_ENTRY = {
    "name": NEW_SLOT_NAME,
    "current_player": "Ryan Jeffers",
    "team": "MIN",
    "positions": ["C"],
    "player_type": "hitter",
    "projected_points": 0,
    "projected_stats": {},
}


def update_my_team():
    data = json.loads(MY_TEAM.read_text())
    players = data["players"]
    for i, p in enumerate(players):
        if p.get("name") == OLD_SLOT_NAME or p.get("name") == NEW_SLOT_NAME:
            players[i] = NEW_ENTRY
            break
    else:
        sys.exit(f"ERROR: no Cal Raleigh or {NEW_SLOT_NAME} entry found in my_team.json")
    data["updated"] = "2026-05-18T00:00:00"
    MY_TEAM.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Updated {MY_TEAM.name}")


def update_season_stats():
    stats = json.loads(SEASON.read_text())
    if NEW_SLOT_NAME in stats:
        print(f"{NEW_SLOT_NAME} already present in season_stats.json — no rename needed")
        return
    if OLD_SLOT_NAME not in stats:
        sys.exit(f"ERROR: '{OLD_SLOT_NAME}' not found in season_stats.json")
    stats[NEW_SLOT_NAME] = stats.pop(OLD_SLOT_NAME)
    SEASON.write_text(json.dumps(stats, indent=2) + "\n")
    print(f"Renamed '{OLD_SLOT_NAME}' → '{NEW_SLOT_NAME}' in {SEASON.name}")


def git(*args, check=True):
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args],
                          capture_output=True, text=True, check=check)


def commit_and_push():
    git("add", "data/my_team.json", "data/season_stats.json")
    diff = git("diff", "--cached", "--quiet", check=False)
    if diff.returncode == 0:
        print("No changes staged — already applied?")
        return
    git("commit", "-m", "Swap Cal Raleigh -> Ryan Jeffers (C), effective 2026-05-18")
    print("Committed swap")
    git("fetch", "origin", "main", check=False)
    rebase = git("rebase", "-X", "ours", "origin/main", check=False)
    if rebase.returncode != 0:
        git("rebase", "--abort", check=False)
        print(f"WARN: rebase failed, pushing anyway: {rebase.stderr.strip()}")
    push = git("push", "origin", "main", check=False)
    if push.returncode != 0:
        sys.exit(f"ERROR: push failed: {push.stderr.strip() or push.stdout.strip()}")
    print("Pushed to origin/main")


if __name__ == "__main__":
    update_my_team()
    update_season_stats()
    commit_and_push()
