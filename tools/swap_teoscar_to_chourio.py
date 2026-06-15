"""
swap_teoscar_to_chourio.py — One-shot OF-slot swap on 2026-06-22.

Replaces Teoscar Hernández (LAD, 10-day IL — hamstring) with Jackson
Chourio (MIL) on Jon's roster, carrying forward the Teoscar slot's
accumulated totals into a new "Teoscar/Chourio" slot key (mirrors the
Lindor → McGonigle, Stanton → Rice, and Jeffers → Basallo patterns; see
CLAUDE.md "Mid-season player swaps").

There are THREE OF slots on the roster, so this script targets the slot
by name ("Teoscar Hernandez") rather than by position.

Distinct launchd label (com.jon.fantasy-baseball-swap-of) so it does NOT
collide with the concurrently-armed Bichette → Vargas 3B swap, which owns
com.jon.fantasy-baseball-swap and self-removes the night of Sun 6/21.

Scheduled to run once at 23:00 ET on Monday 2026-06-22 — BEFORE the Tue
06-23 4:35am remote-agent run, so the agent reads the updated
my_team.json and pulls Chourio's Monday 6/22 box score. Chourio starts
counting for us 2026-06-22; first daily email with his data: Tue 06-23.

Idempotent: if the slot has already been renamed, exits successfully
without touching files or git. Self-uninstalls the launchd job on
successful run (whether the swap was applied or already applied).

A freshness guard refuses to swap if the daily pipeline baseline in
yesterday.json is stale (older than EXPECTED_AS_OF). As of arming time
the pipeline was stalled at 2026-05-31; it MUST be revived before
Monday or the swap will refuse to fire (exit 1, job left in place for
manual re-run).

Usage:
    python3 tools/swap_teoscar_to_chourio.py                  # apply, push, email, uninstall
    python3 tools/swap_teoscar_to_chourio.py --dry-run        # preview only, no writes
    python3 tools/swap_teoscar_to_chourio.py --dry-run --ignore-freshness  # structural preview
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

OLD_SLOT_NAME = "Teoscar Hernandez"
OLD_CURRENT_PLAYER = "Teoscar Hernández"  # accented display/lookup name
NEW_SLOT_NAME = "Teoscar/Chourio"
NEW_CURRENT_PLAYER = "Jackson Chourio"
NEW_TEAM = "MIL"
NEW_POSITIONS = ["OF"]
EFFECTIVE_DATE = date(2026, 6, 22)   # Monday — Chourio's games count from here
EXPECTED_AS_OF = date(2026, 6, 21)   # Mon 6/22 5:30am cron processes Sun 6/21

EMAIL_TO = "levinson.jon@gmail.com"
EMAIL_CC = "levinsonlgs@gmail.com"
EMAIL_FROM = "levinson.jon@gmail.com"

PLIST_LABEL = "com.jon.fantasy-baseball-swap-of"
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


def perform_swap(dry_run: bool = False, ignore_freshness: bool = False) -> dict:
    """Apply the swap. Returns a summary dict with 'already_applied', 'dry_run',
    or 'carryover_totals'+'new_slot' depending on what happened."""
    my_team_path = DATA_DIR / "my_team.json"
    season_stats_path = DATA_DIR / "season_stats.json"
    yesterday_path = DATA_DIR / "yesterday.json"

    team = _read_json(my_team_path)
    season_stats = _read_json(season_stats_path)

    # Target the slot by NAME (three OF slots exist; can't filter by position).
    matches = [p for p in team["players"] if p.get("name") == OLD_SLOT_NAME]
    new_matches = [p for p in team["players"] if p.get("name") == NEW_SLOT_NAME]

    # Idempotency: already swapped?
    has_old_in_stats = OLD_SLOT_NAME in season_stats
    has_new_in_stats = NEW_SLOT_NAME in season_stats
    if (
        not matches and new_matches
        and new_matches[0].get("current_player") == NEW_CURRENT_PLAYER
        and has_new_in_stats and not has_old_in_stats
    ):
        log("Swap already applied — exiting (idempotent no-op)")
        return {"already_applied": True}

    # Pre-swap sanity checks
    if len(matches) != 1:
        raise SystemExit(
            f"ERROR: expected exactly 1 slot named {OLD_SLOT_NAME!r}, "
            f"found {len(matches)} (refusing to swap from unexpected state)"
        )
    slot = matches[0]
    if "OF" not in slot.get("positions", []):
        raise SystemExit(
            f"ERROR: slot {OLD_SLOT_NAME!r} is not an OF slot "
            f"(positions={slot.get('positions')})"
        )
    if slot.get("current_player") != OLD_CURRENT_PLAYER:
        raise SystemExit(
            f"ERROR: expected current_player {OLD_CURRENT_PLAYER!r}, "
            f"found {slot.get('current_player')!r}"
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
    if not ignore_freshness and (yest_date is None or yest_date < EXPECTED_AS_OF):
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

    new_slot = {
        "name": NEW_SLOT_NAME,
        "current_player": NEW_CURRENT_PLAYER,
        "team": NEW_TEAM,
        "positions": NEW_POSITIONS,
        "player_type": "hitter",
        "projected_points": 0,
        "projected_stats": {},
    }
    new_players = [
        new_slot if p.get("name") == OLD_SLOT_NAME else p
        for p in team["players"]
    ]
    new_team = {**team, "players": new_players,
                "updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}

    if dry_run:
        log("DRY RUN — no files written, no git push, no email")
        log(f"  Proposed new OF entry: {json.dumps(new_slot, indent=2, ensure_ascii=False)}")
        log(f"  season_stats key rename: {OLD_SLOT_NAME!r} → {NEW_SLOT_NAME!r}")
        return {"dry_run": True, "carryover_totals": carryover_totals,
                "new_slot": new_slot}

    _write_json(my_team_path, new_team)
    log(f"Wrote {my_team_path.relative_to(REPO_ROOT)}")
    _write_json(season_stats_path, new_stats)
    log(f"Wrote {season_stats_path.relative_to(REPO_ROOT)}")

    return {"carryover_totals": carryover_totals, "new_slot": new_slot}


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
        f"Swap Teoscar Hernández -> Jackson Chourio (OF), effective "
        f"{EFFECTIVE_DATE.isoformat()}\n\n"
        f"Mid-season roster swap. Teoscar landed on the 10-day IL (hamstring "
        f"strain, out since 5/27). Chourio (MIL) is healthy (back from a "
        f"L-hand fracture, activated 5/4 and producing), and his blended BT "
        f"projection (496) is the top of the available OF free-agent pool, "
        f"+29 over Teoscar with elite multi-category value (power + 20+ SB).\n\n"
        f"OF slot relabeled \"{NEW_SLOT_NAME}\" with the prior slot's totals "
        f"pre-seeded under that key in season_stats.json so the remote agent's "
        f"daily accumulator adds Chourio's {EFFECTIVE_DATE.isoformat()}-onward "
        f"deltas on top.\n\n"
        f"projected_points zeroed out per option C (CLAUDE.md \"Mid-season "
        f"player swaps\") — Chourio has no preseason projection in our system, "
        f"so the team page's projected season total becomes a lower bound.\n\n"
        f"Applied automatically by tools/swap_teoscar_to_chourio.py / "
        f"com.jon.fantasy-baseball-swap-of launchd job; plist is removed after "
        f"this run.\n\n"
        f"Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
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
    parser.add_argument("--ignore-freshness", action="store_true",
                        help="Skip the stale-baseline guard (structural dry-run only)")
    parser.add_argument("--skip-uninstall", action="store_true",
                        help="Don't remove the launchd plist after running")
    args = parser.parse_args()

    log(f"--- Starting swap_teoscar_to_chourio (dry_run={args.dry_run}) ---")

    try:
        result = perform_swap(dry_run=args.dry_run,
                              ignore_freshness=args.ignore_freshness)
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
            subject="Fantasy Baseball: Teoscar->Chourio swap FAILED at git push",
            body=(
                f"The roster-swap script wrote the data files but failed to "
                f"push to origin/main:\n\n{e}\n\n"
                f"Files have been modified locally. Inspect the repo, fix the "
                f"git issue, and push manually. The launchd job has NOT been "
                f"removed and will not retry — re-run "
                f"tools/swap_teoscar_to_chourio.py manually once unblocked.\n\n"
                f"Log: {LOG_PATH}\n"
            ),
        )
        sys.exit(1)

    totals = result["carryover_totals"]
    body = (
        f"Mid-season roster swap applied automatically.\n\n"
        f"Slot: OF\n"
        f"Out:  Teoscar Hernández (LAD, IL — hamstring)\n"
        f"In:   Jackson Chourio (MIL)\n"
        f"Effective: {EFFECTIVE_DATE.isoformat()}\n\n"
        f"Prior slot totals carried forward into \"{NEW_SLOT_NAME}\" key:\n"
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
        subject="Fantasy Baseball: Teoscar->Chourio swap applied",
        body=body,
    )

    if not args.skip_uninstall:
        uninstall_launchd_job()

    log("--- Done ---")


if __name__ == "__main__":
    main()
