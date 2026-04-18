"""
send_pending_email.py — Finds and sends the daily report Gmail draft.

Designed to run as a local launchd job ~30 min after the remote agent
creates a Gmail draft via the claude.ai Gmail connector.

1. Connect to Gmail API using local OAuth credentials
2. Search drafts for today's "Fantasy Baseball Daily" subject
3. Extract embedded JSON (yesterday-data, news-data) and write to
   data/yesterday.json, data/news.json, then git commit + push so
   Vercel redeploys the static web interface with fresh data.
4. Send the draft
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

# Subject prefix to match
SUBJECT_PREFIX = "Fantasy Baseball Daily"

# Embedded JSON block IDs written by daily_report.build_html_email
EMBED_BLOCKS = {
    "yesterday-data": "yesterday.json",
    "news-data": "news.json",
}

# Non-interactive git env (launchd has no HOME expansion surprises)
_GIT_ENV_BASE = {"GIT_TERMINAL_PROMPT": "0"}


def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(SEND_LOG, "a") as f:
        f.write(line + "\n")


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


def find_daily_report_draft(service):
    """Find the most recent draft matching today's daily report subject."""
    # Yesterday's date is what the report covers
    yesterday = date.today() - timedelta(days=1)

    # List all drafts
    result = service.users().drafts().list(userId="me", maxResults=20).execute()
    drafts = result.get("drafts", [])

    if not drafts:
        return None

    for draft_info in drafts:
        draft = service.users().drafts().get(
            userId="me", id=draft_info["id"], format="metadata",
        ).execute()

        headers = draft.get("message", {}).get("payload", {}).get("headers", [])
        subject = next((h["value"] for h in headers if h["name"] == "Subject"), "")

        if SUBJECT_PREFIX in subject:
            log(f"Found matching draft: {subject} (id: {draft_info['id']})")
            return draft_info["id"]

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


def write_data_files(blocks: dict) -> list[Path]:
    """Write each known block to data/<name>.json. Returns the paths written."""
    written = []
    for block_id, filename in EMBED_BLOCKS.items():
        if block_id not in blocks:
            log(f"WARN: no '{block_id}' block in draft — skipping {filename}")
            continue
        path = DATA_DIR / filename
        with open(path, "w") as f:
            json.dump(blocks[block_id], f, indent=2, ensure_ascii=False)
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


def sync_web_data(service, draft_id: str):
    """
    Extract embedded JSON from the draft, write data files, commit, push.
    Logs any failure but never raises — the email send should proceed.
    """
    try:
        html = get_draft_html(service, draft_id)
        if not html:
            log("WARN: draft had no HTML body; skipping data sync")
            return
        blocks = extract_json_blocks(html)
        if not blocks:
            log("WARN: no JSON blocks found in draft; skipping data sync")
            return
        written = write_data_files(blocks)
        if not written:
            return
        # Prefer the date from the payload, falling back to today-minus-one.
        report_date = date.today() - timedelta(days=1)
        y = blocks.get("yesterday-data") or {}
        if isinstance(y.get("date"), str):
            try:
                report_date = date.fromisoformat(y["date"])
            except ValueError:
                pass
        git_commit_and_push(written, report_date)
    except Exception as e:
        log(f"ERROR during data sync (continuing to send email): {e}")


def main():
    log("--- Starting send_pending_email ---")

    try:
        service = build_gmail_service()
    except Exception as e:
        log(f"ERROR building Gmail service: {e}")
        sys.exit(1)

    draft_id = find_daily_report_draft(service)

    if not draft_id:
        log("No matching draft found — nothing to send")
        sys.exit(0)

    # Sync structured data to the repo for Vercel before sending.
    # Failures here log but do not block the email.
    sync_web_data(service, draft_id)

    try:
        result = service.users().drafts().send(
            userId="me", body={"id": draft_id}
        ).execute()
        msg_id = result.get("id")
        log(f"Draft sent successfully (message ID: {msg_id})")
    except Exception as e:
        log(f"ERROR sending draft: {e}")
        sys.exit(1)

    log("--- Done ---")


if __name__ == "__main__":
    main()
