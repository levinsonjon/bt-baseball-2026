"""
send_pending_email.py — Finds and sends the daily report Gmail draft.

Designed to run as a local launchd job ~30 min after the remote agent
creates a Gmail draft via the claude.ai Gmail connector.

1. Connect to Gmail API using local OAuth credentials
2. Search drafts for today's "Fantasy Baseball Daily" subject
3. Send the draft
"""

import json
import sys
from pathlib import Path
from datetime import datetime, date, timedelta

SEND_LOG = Path(__file__).parent / "send_email.log"

# Gmail OAuth credentials (same ones used by local MCP server)
GMAIL_CREDS = Path.home() / ".config" / "personal-mcp" / "gmail" / "credentials.json"
GMAIL_OAUTH = Path.home() / ".config" / "personal-mcp" / "gmail" / "gcp-oauth.keys.json"

# Subject prefix to match
SUBJECT_PREFIX = "Fantasy Baseball Daily"


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
