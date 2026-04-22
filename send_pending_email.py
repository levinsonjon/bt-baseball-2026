"""
send_pending_email.py — Finds and sends the daily report Gmail drafts.

Designed to run as a local launchd job ~30 min after the remote agent
creates two Gmail drafts via the claude.ai Gmail connector:

  - DATA draft   ("Fantasy Baseball DATA YYYY-MM-DD")
      Body: <script type="application/json"> payloads only.
      This script extracts them, writes data/{yesterday,news}.json,
      commits + pushes to main (triggering a Vercel redeploy), and
      DELETES the draft.

  - EMAIL draft  ("Fantasy Baseball Daily YYYY-MM-DD (...)")
      Body: the HTML email. This script sends it.

Splitting the payload across two drafts keeps each Gmail-draft API call
small enough to avoid stream-idle timeouts on the remote agent side.
"""

import base64
import json
import re
import subprocess
import sys
from pathlib import Path
from datetime import datetime, date, timedelta

REPO_ROOT = Path(__file__).parent
DATA_DIR = REPO_ROOT / "data"
SEND_LOG = REPO_ROOT / "send_email.log"

# Gmail OAuth credentials (same ones used by local MCP server)
GMAIL_CREDS = Path.home() / ".config" / "personal-mcp" / "gmail" / "credentials.json"
GMAIL_OAUTH = Path.home() / ".config" / "personal-mcp" / "gmail" / "gcp-oauth.keys.json"

# Subject prefixes. startswith-matching keeps DATA and Daily distinct.
DATA_SUBJECT_PREFIX = "Fantasy Baseball DATA"
EMAIL_SUBJECT_PREFIX = "Fantasy Baseball Daily"

# Embedded JSON block IDs in the DATA draft → files in data/.
EMBED_BLOCKS = {
    "yesterday-data":    "yesterday.json",
    "news-data":         "news.json",
    "season-stats-data": "season_stats.json",
}

# Non-interactive git env (launchd has no HOME expansion surprises)
_GIT_ENV_BASE = {"GIT_TERMINAL_PROMPT": "0"}


def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(SEND_LOG, "a") as f:
        f.write(line + "\n")


def notify_reauth_needed(reason: str):
    """Create a persistent macOS Reminder so Jon sees the alert even though
    the cron jobs run while he's asleep. Gmail-based warnings don't work here
    because the failing credential is the Gmail one."""
    reauth_cmd = (
        f"GMAIL_OAUTH_PATH={GMAIL_OAUTH} "
        f"GMAIL_CREDENTIALS_PATH={GMAIL_CREDS} "
        f"npx @gongrzhe/server-gmail-autoauth-mcp auth"
    )
    body = f"{reason}\n\nRe-auth command:\n{reauth_cmd}"
    # AppleScript string-escape: backslashes then double-quotes.
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


# Subject date parsers. DATA draft: "Fantasy Baseball DATA YYYY-MM-DD".
# Email draft: "Fantasy Baseball Daily — Month DD, YYYY (...)".
_DATA_SUBJECT_RE = re.compile(r"Fantasy Baseball DATA (\d{4}-\d{2}-\d{2})")
_EMAIL_SUBJECT_RE = re.compile(
    r"Fantasy Baseball Daily\s+[—\-]\s+([A-Za-z]+ \d{1,2},\s*\d{4})"
)


def _parse_draft_date(subject: str):
    """Return the date encoded in the subject, or None if unparseable."""
    m = _DATA_SUBJECT_RE.search(subject)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            return None
    m = _EMAIL_SUBJECT_RE.search(subject)
    if m:
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(m.group(1), fmt).date()
            except ValueError:
                continue
    return None


def find_drafts_by_prefix(service, prefix: str):
    """Return a list of (draft_date, subject, id) tuples for every draft whose
    subject starts with `prefix`, sorted chronologically (oldest first).
    Drafts with unparseable subjects are skipped with a warning."""
    result = service.users().drafts().list(userId="me", maxResults=50).execute()
    drafts = result.get("drafts", [])
    matches = []
    for draft_info in drafts:
        draft = service.users().drafts().get(
            userId="me", id=draft_info["id"], format="metadata",
        ).execute()
        headers = draft.get("message", {}).get("payload", {}).get("headers", [])
        subject = next((h["value"] for h in headers if h["name"] == "Subject"), "")
        if not subject.startswith(prefix):
            continue
        draft_date = _parse_draft_date(subject)
        if draft_date is None:
            log(f"WARN: could not parse date from subject: {subject!r} — skipping")
            continue
        matches.append((draft_date, subject, draft_info["id"]))
    matches.sort(key=lambda t: t[0])
    return matches


def current_data_watermark():
    """Return the date already represented in data/yesterday.json, or None if
    the file is missing/unparseable. Used to skip stale drafts that would
    otherwise overwrite newer data with older data."""
    path = DATA_DIR / "yesterday.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            payload = json.load(f)
        d = payload.get("date")
        if isinstance(d, str):
            return date.fromisoformat(d)
    except (json.JSONDecodeError, ValueError):
        pass
    return None


# ---------------------------------------------------------------------------
# Data sync: extract embedded JSON from the draft and commit to the repo
# ---------------------------------------------------------------------------

def _walk_parts(payload):
    """Yield every leaf MIME part in a Gmail message payload."""
    parts = payload.get("parts")
    if not parts:
        yield payload
        return
    for part in parts:
        yield from _walk_parts(part)


def get_draft_html(service, draft_id: str) -> str:
    """Return the HTML body of a draft, or empty string if not found."""
    draft = service.users().drafts().get(
        userId="me", id=draft_id, format="full",
    ).execute()
    payload = draft.get("message", {}).get("payload", {})

    html_data = None
    text_data = None
    for part in _walk_parts(payload):
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")
        if not data:
            continue
        if mime == "text/html" and html_data is None:
            html_data = data
        elif mime == "text/plain" and text_data is None:
            text_data = data

    chosen = html_data or text_data
    if not chosen:
        return ""
    return base64.urlsafe_b64decode(chosen).decode("utf-8", errors="replace")


_JSON_BLOCK_RE = re.compile(
    r'<script\b[^>]*?type=["\']application/json["\'][^>]*?id=["\']([^"\']+)["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def extract_json_blocks(html: str) -> dict:
    """Return {block_id: parsed_json} for every embedded JSON script tag."""
    blocks = {}
    for match in _JSON_BLOCK_RE.finditer(html):
        block_id = match.group(1)
        raw = match.group(2).strip()
        try:
            blocks[block_id] = json.loads(raw)
        except json.JSONDecodeError as e:
            log(f"WARN: failed to parse '{block_id}' JSON block: {e}")
    return blocks


def _load_roster_index() -> dict:
    """Return {player_name: {team, position, type}} from data/my_team.json."""
    my_team_path = DATA_DIR / "my_team.json"
    if not my_team_path.exists():
        return {}
    with open(my_team_path) as f:
        team = json.load(f)
    out = {}
    for p in team.get("players", []):
        positions = p.get("positions") or [""]
        out[p.get("name", "")] = {
            "team": p.get("team", ""),
            "position": positions[0] if positions else "",
            "type": p.get("player_type", "hitter"),
        }
    return out


def normalize_yesterday(data: dict, roster: dict) -> dict:
    """Adapt remote agent's yesterday payload to the schema the site reads.

    Handles common field-name drift from the agent:
      - player_type → type, fantasy_points → points
      - opponent "" → null
      - team/position filled in from the roster if missing
      - rebuild totals.{hitters,pitchers} from per-player stats
    """
    tot_hit = {"AB": 0, "H": 0, "R": 0, "HR": 0, "RBI": 0, "SB": 0, "points": 0.0}
    tot_p = {"IP": 0.0, "H": 0, "ER": 0, "K": 0, "BB": 0, "W": 0, "SV": 0, "points": 0.0}
    players_out = []
    empty_stats_played = 0

    for p in data.get("players", []):
        name = p.get("name", "")
        r = roster.get(name, {})
        ptype = p.get("type") or p.get("player_type") or r.get("type", "hitter")
        pts = p.get("points")
        if pts is None:
            pts = p.get("fantasy_points", 0.0)
        stats = p.get("stats") or {}
        dnp = bool(p.get("dnp", False))
        opp = p.get("opponent")
        if opp == "" or opp is None:
            opp = None

        players_out.append({
            "name": name,
            "team": p.get("team") or r.get("team", ""),
            "position": p.get("position") or r.get("position", ""),
            "type": ptype,
            "opponent": opp,
            "dnp": dnp,
            "dnp_reason": p.get("dnp_reason"),
            "stats": stats,
            "points": float(pts or 0),
            "summary": p.get("summary", ""),
        })

        if not dnp:
            if not stats:
                empty_stats_played += 1
            try:
                if ptype == "hitter":
                    for k in ("AB", "H", "R", "HR", "RBI", "SB"):
                        tot_hit[k] += int(stats.get(k, 0) or 0)
                    tot_hit["points"] += float(pts or 0)
                else:
                    tot_p["IP"] += float(stats.get("IP", 0) or 0)
                    for k in ("H", "ER", "K", "BB", "W", "SV"):
                        tot_p[k] += int(stats.get(k, 0) or 0)
                    tot_p["points"] += float(pts or 0)
            except (TypeError, ValueError) as e:
                log(f"WARN: totals skipped for {name}: {e}")

    if empty_stats_played:
        log(f"WARN: {empty_stats_played} non-DNP player(s) had empty stats={{}} — "
            f"agent schema drift; per-player stat columns will render blank on the site")

    return {
        "date": data.get("date", ""),
        "generated_at": data.get("generated_at", ""),
        "totals": {
            "hitters": {**tot_hit, "points": round(tot_hit["points"], 2)},
            "pitchers": {**tot_p, "IP": round(tot_p["IP"], 2), "points": round(tot_p["points"], 2)},
        },
        "players": players_out,
    }


def normalize_news(data: dict, roster: dict) -> dict:
    """Adapt news payload: summary field, roster-backed team/position, preserved sources."""
    players_out = []
    for p in data.get("players", []):
        name = p.get("name", "")
        r = roster.get(name, {})
        players_out.append({
            "name": name,
            "team": p.get("team") or r.get("team", ""),
            "position": p.get("position") or r.get("position", ""),
            "summary": p.get("summary") or p.get("news") or "",
            "sources": p.get("sources") or [],
        })

    injuries_out = []
    for inj in data.get("injuries", []):
        name = inj.get("name", "")
        r = roster.get(name, {})
        injuries_out.append({
            "name": name,
            "team": inj.get("team") or r.get("team", ""),
            "position": inj.get("position") or r.get("position", ""),
            "status": inj.get("status", ""),
            "previous_status": inj.get("previous_status", ""),
            "note": inj.get("note", ""),
            "source": inj.get("source"),
        })

    generated_at = data.get("generated_at") or ""
    if not generated_at and data.get("date"):
        generated_at = data["date"] + "T00:00:00Z"

    return {
        "generated_at": generated_at,
        "window_hours": data.get("window_hours", 24),
        "players": players_out,
        "injuries": injuries_out,
    }


# season_stats.json needs no normalization — its keys already match the site schema.
_NORMALIZERS = {
    "yesterday.json": normalize_yesterday,
    "news.json": normalize_news,
}


def write_data_files(blocks: dict) -> list[Path]:
    """Write each known block to data/<name>.json, normalizing where needed."""
    roster = _load_roster_index()
    written = []
    for block_id, filename in EMBED_BLOCKS.items():
        if block_id not in blocks:
            log(f"WARN: no '{block_id}' block in draft — skipping {filename}")
            continue
        data = blocks[block_id]
        normalizer = _NORMALIZERS.get(filename)
        if normalizer:
            try:
                data = normalizer(data, roster)
            except Exception as e:
                log(f"WARN: normalize {filename} failed ({e}); writing raw payload")
        path = DATA_DIR / filename
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        log(f"Wrote {path.relative_to(REPO_ROOT)}")
        written.append(path)
    return written


def _git(*args, check=True):
    """Run git in the repo root with a non-interactive env. Returns CompletedProcess."""
    import os
    env = {**os.environ, **_GIT_ENV_BASE}
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        env=env, capture_output=True, text=True, check=check,
    )


def git_commit_and_push(paths: list[Path], report_date: date):
    """Stage, commit, and push the given data files. Safe no-op if nothing changed."""
    if not paths:
        log("No data files to commit")
        return

    rels = [str(p.relative_to(REPO_ROOT)) for p in paths]
    _git("add", *rels)

    # Nothing staged? skip commit.
    diff = _git("diff", "--cached", "--quiet", check=False)
    if diff.returncode == 0:
        log("No data changes to commit")
        return

    msg = f"Daily data update {report_date.isoformat()}"
    commit = _git("commit", "-m", msg, check=False)
    if commit.returncode != 0:
        raise RuntimeError(f"git commit failed: {commit.stderr.strip() or commit.stdout.strip()}")
    log(f"Committed: {msg}")

    # Rebase on top of any remote changes before pushing. Data files are
    # generated, so in the rare case of a conflict we keep our version.
    _git("fetch", "origin", "main", check=False)
    rebase = _git("rebase", "-X", "ours", "origin/main", check=False)
    if rebase.returncode != 0:
        _git("rebase", "--abort", check=False)
        log(f"WARN: rebase failed, pushing anyway: {rebase.stderr.strip()}")

    push = _git("push", "origin", "main", check=False)
    if push.returncode != 0:
        raise RuntimeError(f"git push failed: {push.stderr.strip() or push.stdout.strip()}")
    log("Pushed to origin/main")


def consume_data_draft(service, draft_id: str):
    """
    Extract JSON payloads from the data draft, write them to data/*.json,
    commit + push to origin/main, then delete the draft (it has served its
    purpose — no need to clutter Jon's drafts folder).

    Logs and swallows errors. The email send should proceed regardless.
    """
    try:
        html = get_draft_html(service, draft_id)
        if not html:
            log("WARN: data draft had no body; skipping sync")
            return
        blocks = extract_json_blocks(html)
        if not blocks:
            log("WARN: no JSON blocks found in data draft; skipping sync")
            return
        written = write_data_files(blocks)
        if not written:
            return

        report_date = date.today() - timedelta(days=1)
        y = blocks.get("yesterday-data") or {}
        if isinstance(y.get("date"), str):
            try:
                report_date = date.fromisoformat(y["date"])
            except ValueError:
                pass

        git_commit_and_push(written, report_date)

        # Best-effort cleanup — don't error if it fails.
        try:
            service.users().drafts().delete(userId="me", id=draft_id).execute()
            log(f"Deleted data draft {draft_id}")
        except Exception as e:
            log(f"WARN: failed to delete data draft: {e}")
    except Exception as e:
        log(f"ERROR during data draft consumption (continuing): {e}")


def _is_auth_error(exc: Exception) -> bool:
    """Heuristic: does this look like an OAuth refresh/token failure?"""
    s = str(exc).lower()
    return any(k in s for k in (
        "invalid_grant", "refresherror", "token has been expired",
        "token has been revoked", "unauthorized", "401",
    ))


def main():
    log("--- Starting send_pending_email ---")

    try:
        service = build_gmail_service()
    except Exception as e:
        log(f"ERROR building Gmail service: {e}")
        if _is_auth_error(e):
            notify_reauth_needed(f"Gmail auth failed: {e}")
        sys.exit(1)

    watermark = current_data_watermark()
    log(f"On-disk data watermark: {watermark}")

    # Phase 1: consume DATA drafts in chronological order, skipping stale.
    try:
        data_drafts = find_drafts_by_prefix(service, DATA_SUBJECT_PREFIX)
    except Exception as e:
        log(f"ERROR listing data drafts: {e}")
        if _is_auth_error(e):
            notify_reauth_needed(f"Gmail auth failed: {e}")
        sys.exit(1)

    if not data_drafts:
        log("No data draft found; skipping data sync")
    for draft_date, subject, draft_id in data_drafts:
        if watermark is not None and draft_date <= watermark:
            log(f"Skipping stale data draft {subject!r} "
                f"(date {draft_date} <= watermark {watermark})")
            continue
        log(f"Processing data draft: {subject} (id: {draft_id})")
        consume_data_draft(service, draft_id)
        watermark = draft_date  # advance so later drafts on same run compare correctly

    # Phase 2: send EMAIL drafts in chronological order, skipping stale.
    try:
        email_drafts = find_drafts_by_prefix(service, EMAIL_SUBJECT_PREFIX)
    except Exception as e:
        log(f"ERROR listing email drafts: {e}")
        if _is_auth_error(e):
            notify_reauth_needed(f"Gmail auth failed: {e}")
        sys.exit(1)

    email_watermark = current_data_watermark()
    sent_any = False
    for draft_date, subject, draft_id in email_drafts:
        if email_watermark is not None and draft_date < email_watermark:
            log(f"Skipping stale email draft {subject!r} "
                f"(date {draft_date} < watermark {email_watermark})")
            continue
        try:
            result = service.users().drafts().send(
                userId="me", body={"id": draft_id}
            ).execute()
            msg_id = result.get("id")
            log(f"Sent email draft {subject!r} (message ID: {msg_id})")
            sent_any = True
        except Exception as e:
            log(f"ERROR sending email draft {subject!r}: {e}")
            if _is_auth_error(e):
                notify_reauth_needed(f"Gmail auth failed while sending email: {e}")
            sys.exit(1)

    if not sent_any and not email_drafts:
        log("No email draft found — nothing to send")

    log("--- Done ---")


if __name__ == "__main__":
    main()
