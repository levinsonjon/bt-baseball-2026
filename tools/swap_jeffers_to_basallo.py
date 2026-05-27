"""
swap_jeffers_to_basallo.py — One-shot C-slot swap on 2026-05-31.

Replaces Ryan Jeffers (hamate fracture IL) with Samuel Basallo on Jon's
roster, carrying forward the Raleigh/Jeffers composite slot's totals
into a new "Jeffers/Basallo" slot key (mirrors the Lindor → McGonigle
and Stanton → Rice swap patterns; see CLAUDE.md "Mid-season player swaps").

Scheduled by ~/Library/LaunchAgents/com.jon.fantasy-baseball-swap.plist
to run once at 23:00 ET on Sunday 2026-05-31 — BEFORE the Mon 06-01
4:35am remote-agent run, so the agent reads the updated my_team.json
and pulls Basallo's Sunday 5/31 box score (instead of Jeffers's DNP-IL).
First daily email containing Basallo data: Mon 06-01.

Idempotent: if the slot has already been renamed, exits successfully
without touching files or git. Self-uninstalls the launchd job on
successful run (whether the swap was applied or already applied).

Usage:
    python3 tools/swap_jeffers_to_basallo.py            # apply, push, email, uninstall
    python3 tools/swap_jeffers_to_basallo.py --dry-run  # preview only, no writes
"""

import argparse
import base64
import json
import os
import subprocess
import sys
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
LOG_PATH = REPO_ROOT / "swap.log"

OLD_SLOT_NAME = "Raleigh/Jeffers"
OLD_CURRENT_PLAYER = "Ryan Jeffers"
NEW_SLOT_NAME = "Jeffers/Basallo"
NEW_CURRENT_PLAYER = "Samuel Basallo"
NEW_TEAM = "BAL"
NEW_POSITIONS = ["C"]
EFFECTIVE_DATE = date(2026, 6, 1)
EXPECTED_AS_OF = date(2026, 5, 30)  # Sun 5/31 5:30am cron processes Sat 5/30

EMAIL_TO = "levinson.jon@gmail.com"
EMAIL_CC = "levinsonlgs@gmail.com"
EMAIL_FROM = "levinson.jon@gmail.com"

PLIST_LABEL = "com.jon.fantasy-baseball-swap"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"

GMAIL_CREDS = Path.home() / ".config" / "personal-mcp" / "gmail-fb" / "credentials.json"
GMAIL_OAUTH = Path.home() / ".config" / "personal-mcp" / "gmail-fb" / "gcp-oauth.keys.json"

_GIT_ENV_BASE = {"GIT_TERMINAL_PROMPT": "0"}


def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------------------
# Swap logic
# ---------------------------------------------------------------------------

def _read_json(path: Path):
    with open(path) as f:
        return json.load(f)


def _write_json(path: Path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def perform_swap(dry_run: bool = False) -> dict:
    """Apply the swap. Returns a summary dict with 'already_applied', 'dry_run',
    or 'carryover_totals'+'new_c_slot' depending on what happened."""
    my_team_path = DATA_DIR / "my_team.json"
    season_stats_path = DATA_DIR / "season_stats.json"
    yesterday_path = DATA_DIR / "yesterday.json"

    team = _read_json(my_team_path)
    season_stats = _read_json(season_stats_path)

    c_slots = [p for p in team["players"] if "C" in p.get("positions", [])]
    if len(c_slots) != 1:
        raise SystemExit(
            f"ERROR: expected exactly 1 C slot, found {len(c_slots)}"
        )
    c_slot = c_slots[0]

    # Idempotency: already swapped?
    has_old_in_stats = OLD_SLOT_NAME in season_stats
    has_new_in_stats = NEW_SLOT_NAME in season_stats
    if (
        c_slot.get("name") == NEW_SLOT_NAME
        and c_slot.get("current_player") == NEW_CURRENT_PLAYER
        and has_new_in_stats
        and not has_old_in_stats
    ):
        log("Swap already applied — exiting (idempotent no-op)")
        return {"already_applied": True}

    # Pre-swap sanity checks
    if c_slot.get("name") != OLD_SLOT_NAME:
        raise SystemExit(
            f"ERROR: expected C slot name {OLD_SLOT_NAME!r}, "
            f"found {c_slot.get('name')!r} (refusing to swap from unexpected state)"
        )
    if c_slot.get("current_player") != OLD_CURRENT_PLAYER:
        raise SystemExit(
            f"ERROR: expected current_player {OLD_CURRENT_PLAYER!r}, "
            f"found {c_slot.get('current_player')!r}"
        )
    if not has_old_in_stats:
        raise SystemExit(
            f"ERROR: {OLD_SLOT_NAME!r} key missing from season_stats.json"
        )
    if has_new_in_stats:
        raise SystemExit(
            f"ERROR: {NEW_SLOT_NAME!r} key unexpectedly already present in "
            f"season_stats.json (refusing to clobber)"
        )

    # Verify season_stats has been updated through EXPECTED_AS_OF.
    yesterday = _read_json(yesterday_path)
    yest_date_str = yesterday.get("date")
    try:
        yest_date = date.fromisoformat(yest_date_str) if yest_date_str else None
    except ValueError:
        yest_date = None
    if yest_date is None or yest_date < EXPECTED_AS_OF:
        raise SystemExit(
            f"ERROR: yesterday.json date is {yest_date_str!r}, expected "
            f">= {EXPECTED_AS_OF.isoformat()}; daily pipeline hasn't run yet "
            f"for that date — refusing to swap into a stale baseline."
        )

    carryover_totals = season_stats[OLD_SLOT_NAME]
    log(f"Carrying forward {OLD_SLOT_NAME} totals (as of {yest_date_str}): "
        f"{carryover_totals}")

    # Apply the swap (in-memory). Preserve dict insertion order for
    # season_stats so the renamed key sits where the old one was.
    new_stats = {
        (NEW_SLOT_NAME if k == OLD_SLOT_NAME else k): v
        for k, v in season_stats.items()
    }

    new_c_slot = {
        "name": NEW_SLOT_NAME,
        "current_player": NEW_CURRENT_PLAYER,
        "team": NEW_TEAM,
        "positions": NEW_POSITIONS,
        "player_type": "hitter",
        "projected_points": 0,
        "projected_stats": {},
    }
    new_players = [
        new_c_slot if p.get("name") == OLD_SLOT_NAME else p
        for p in team["players"]
    ]
    new_team = {**team, "players": new_players,
                "updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}

    if dry_run:
        log("DRY RUN — no files written, no git push, no email")
        log(f"  Proposed new C entry: {json.dumps(new_c_slot, indent=2)}")
        log(f"  season_stats key rename: {OLD_SLOT_NAME!r} → {NEW_SLOT_NAME!r}")
        return {"dry_run": True, "carryover_totals": carryover_totals,
                "new_c_slot": new_c_slot}

    _write_json(my_team_path, new_team)
    log(f"Wrote {my_team_path.relative_to(REPO_ROOT)}")
    _write_json(season_stats_path, new_stats)
    log(f"Wrote {season_stats_path.relative_to(REPO_ROOT)}")

    return {"carryover_totals": carryover_totals, "new_c_slot": new_c_slot}


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

def _git(*args, check=True):
    env = {**os.environ, **_GIT_ENV_BASE}
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        env=env, capture_output=True, text=True, check=check,
    )


def git_commit_and_push() -> str:
    """Stage data files, fetch+rebase, commit, push. Returns the new commit SHA."""
    _git("add", "data/my_team.json", "data/season_stats.json")
    diff = _git("diff", "--cached", "--quiet", check=False)
    if diff.returncode == 0:
        log("No staged changes — nothing to commit")
        return ""

    msg = (
        f"Swap Ryan Jeffers -> Samuel Basallo (C), effective "
        f"{EFFECTIVE_DATE.isoformat()}\n\n"
        f"Mid-season roster swap. Jeffers landed on the IL with a hamate "
        f"fracture (6-8 wk surgery recovery + power-sapping aftermath). "
        f"Basallo (BAL) is healthy, plays C as his most-frequent position "
        f"(23 G C / 16 DH / 4 1B YTD), and has the highest combined floor + "
        f"ceiling of the available C-eligible free agents.\n\n"
        f"C slot relabeled \"{NEW_SLOT_NAME}\" with the prior slot's totals "
        f"through {EXPECTED_AS_OF.isoformat()} pre-seeded under that key in "
        f"season_stats.json so the remote agent's daily accumulator adds "
        f"Basallo's {EFFECTIVE_DATE.isoformat()}-onward deltas on top.\n\n"
        f"projected_points zeroed out per option C (CLAUDE.md \"Mid-season "
        f"player swaps\") — Basallo has no preseason projection in our "
        f"system, so the team page's projected season total becomes a lower "
        f"bound.\n\n"
        f"Applied automatically by tools/swap_jeffers_to_basallo.py / "
        f"com.jon.fantasy-baseball-swap launchd job; plist is removed after "
        f"this run.\n\n"
        f"Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
    )
    commit = _git("commit", "-m", msg, check=False)
    if commit.returncode != 0:
        raise RuntimeError(
            f"git commit failed: {commit.stderr.strip() or commit.stdout.strip()}"
        )

    sha = _git("rev-parse", "HEAD").stdout.strip()
    log(f"Committed {sha[:8]}")

    _git("fetch", "origin", "main", check=False)
    rebase = _git("rebase", "-X", "ours", "origin/main", check=False)
    if rebase.returncode != 0:
        _git("rebase", "--abort", check=False)
        log(f"WARN: rebase failed, pushing anyway: {rebase.stderr.strip()}")

    push = _git("push", "origin", "main", check=False)
    if push.returncode != 0:
        raise RuntimeError(
            f"git push failed: {push.stderr.strip() or push.stdout.strip()}"
        )
    log("Pushed to origin/main")
    sha = _git("rev-parse", "HEAD").stdout.strip()
    return sha


# ---------------------------------------------------------------------------
# Email confirmation
# ---------------------------------------------------------------------------

def build_gmail_service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    with open(GMAIL_OAUTH) as f:
        oauth = json.load(f)["installed"]
    with open(GMAIL_CREDS) as f:
        creds_data = json.load(f)

    creds = Credentials(
        token=creds_data.get("access_token"),
        refresh_token=creds_data.get("refresh_token"),
        token_uri=oauth["token_uri"],
        client_id=oauth["client_id"],
        client_secret=oauth["client_secret"],
        scopes=["https://www.googleapis.com/auth/gmail.modify"],
    )
    if creds.expired or not creds.valid:
        creds.refresh(Request())
        creds_data["access_token"] = creds.token
        with open(GMAIL_CREDS, "w") as f:
            json.dump(creds_data, f)
        log("Refreshed Gmail access token")
    return build("gmail", "v1", credentials=creds)


def send_confirmation_email(subject: str, body: str):
    try:
        service = build_gmail_service()
        msg = EmailMessage()
        msg["To"] = EMAIL_TO
        msg["Cc"] = EMAIL_CC
        msg["From"] = EMAIL_FROM
        msg["Subject"] = subject
        msg.set_content(body)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        result = service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
        log(f"Sent confirmation email (message ID: {result.get('id')})")
    except Exception as e:
        log(f"WARN: failed to send confirmation email: {e}")


# ---------------------------------------------------------------------------
# Self-uninstall
# ---------------------------------------------------------------------------

def uninstall_launchd_job():
    if not PLIST_PATH.exists():
        log("No launchd plist to remove")
        return
    uid = os.getuid()
    target = f"gui/{uid}/{PLIST_LABEL}"
    bootout = subprocess.run(
        ["launchctl", "bootout", target],
        capture_output=True, text=True,
    )
    if bootout.returncode != 0:
        log(f"WARN: launchctl bootout exited {bootout.returncode}: "
            f"{(bootout.stderr or bootout.stdout).strip()}")
    try:
        PLIST_PATH.unlink()
        log(f"Removed {PLIST_PATH}")
    except OSError as e:
        log(f"WARN: failed to remove plist: {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without writing files or pushing")
    parser.add_argument("--skip-uninstall", action="store_true",
                        help="Don't remove the launchd plist after running")
    args = parser.parse_args()

    log(f"--- Starting swap_jeffers_to_basallo (dry_run={args.dry_run}) ---")

    try:
        result = perform_swap(dry_run=args.dry_run)
    except SystemExit as e:
        log(str(e))
        sys.exit(1)
    except Exception as e:
        log(f"ERROR during swap: {e}")
        sys.exit(1)

    if args.dry_run:
        log("--- Dry run done ---")
        return

    if result.get("already_applied"):
        if not args.skip_uninstall:
            uninstall_launchd_job()
        log("--- Done (no-op) ---")
        return

    try:
        sha = git_commit_and_push()
    except Exception as e:
        log(f"ERROR during git push: {e}")
        send_confirmation_email(
            subject="Fantasy Baseball: Jeffers->Basallo swap FAILED at git push",
            body=(
                f"The roster-swap script wrote the data files but failed to "
                f"push to origin/main:\n\n{e}\n\n"
                f"Files have been modified locally. Inspect the repo, fix the "
                f"git issue, and push manually. The launchd job has NOT been "
                f"removed and will not retry — re-run "
                f"tools/swap_jeffers_to_basallo.py manually once unblocked.\n\n"
                f"Log: {LOG_PATH}\n"
            ),
        )
        sys.exit(1)

    totals = result["carryover_totals"]
    body = (
        f"Mid-season roster swap applied automatically.\n\n"
        f"Slot: C\n"
        f"Out:  Ryan Jeffers (MIN, IL — hamate fracture)\n"
        f"In:   Samuel Basallo (BAL)\n"
        f"Effective: {EFFECTIVE_DATE.isoformat()}\n\n"
        f"Prior slot totals carried forward into \"{NEW_SLOT_NAME}\" key "
        f"(as of {EXPECTED_AS_OF.isoformat()}):\n"
        f"  AB={totals.get('AB')}  H={totals.get('H')}  "
        f"AVG={totals.get('AVG')}  HR={totals.get('HR')}  "
        f"RBI={totals.get('RBI')}  R={totals.get('R')}  "
        f"SB={totals.get('SB')}\n\n"
        f"Commit: {sha}\n"
        f"View: https://www.btbaseball.com\n\n"
        f"The launchd job and one-shot script are auto-removed after this "
        f"run; no further action needed.\n"
    )
    send_confirmation_email(
        subject="Fantasy Baseball: Jeffers->Basallo swap applied",
        body=body,
    )

    if not args.skip_uninstall:
        uninstall_launchd_job()

    log("--- Done ---")


if __name__ == "__main__":
    main()
