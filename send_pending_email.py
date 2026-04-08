"""
send_pending_email.py — Sends a pending daily report email via Gmail API.

Designed to run as a local launchd job ~15 min after the remote agent
builds the report and pushes data/pending_email.json to the repo.

1. git pull to get the latest pending_email.json
2. Read the email payload (to, cc, subject, htmlBody)
3. Send via Gmail API using local OAuth credentials
4. Delete pending_email.json, commit, and push
"""

import json
import sys
import subprocess
import base64
from pathlib import Path
from email.mime.text import MIMEText
from datetime import datetime

# Paths
PROJECT_DIR = Path(__file__).parent
PENDING_EMAIL = PROJECT_DIR / "data" / "pending_email.json"
SEND_LOG = PROJECT_DIR / "send_email.log"

# Gmail OAuth credentials (same ones used by local MCP server)
GMAIL_CREDS = Path.home() / ".config" / "personal-mcp" / "gmail" / "credentials.json"
GMAIL_OAUTH = Path.home() / ".config" / "personal-mcp" / "gmail" / "gcp-oauth.keys.json"


def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(SEND_LOG, "a") as f:
        f.write(line + "\n")


def git_pull():
    result = subprocess.run(
        ["git", "pull", "--rebase"],
        cwd=PROJECT_DIR,
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        log(f"git pull failed: {result.stderr}")
        return False
    log(f"git pull: {result.stdout.strip()}")
    return True


def git_commit_and_push():
    subprocess.run(
        ["git", "add", "data/pending_email.json"],
        cwd=PROJECT_DIR, capture_output=True, timeout=10,
    )
    subprocess.run(
        ["git", "commit", "-m", "Remove pending_email.json after sending"],
        cwd=PROJECT_DIR, capture_output=True, timeout=10,
    )
    result = subprocess.run(
        ["git", "push"],
        cwd=PROJECT_DIR, capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        log(f"git push failed: {result.stderr}")
    else:
        log("Pushed cleanup commit")


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
        # Save refreshed token
        creds_data["access_token"] = creds.token
        with open(GMAIL_CREDS, "w") as f:
            json.dump(creds_data, f)
        log("Refreshed Gmail access token")

    return build("gmail", "v1", credentials=creds)


def send_email(service, to: list[str], cc: list[str], subject: str, html_body: str):
    msg = MIMEText(html_body, "html")
    msg["to"] = ", ".join(to)
    if cc:
        msg["cc"] = ", ".join(cc)
    msg["subject"] = subject

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()
    return result.get("id")


def main():
    log("--- Starting send_pending_email ---")

    if not git_pull():
        log("Aborting: git pull failed")
        sys.exit(1)

    if not PENDING_EMAIL.exists():
        log("No pending_email.json found — nothing to send")
        sys.exit(0)

    with open(PENDING_EMAIL) as f:
        email_data = json.load(f)

    to = email_data.get("to", [])
    cc = email_data.get("cc", [])
    subject = email_data.get("subject", "Fantasy Baseball Daily Report")
    html_body = email_data.get("html", "")

    if not to or not html_body:
        log("ERROR: pending_email.json missing 'to' or 'html'")
        sys.exit(1)

    log(f"Sending: {subject}")
    log(f"  To: {to}, CC: {cc}")

    try:
        service = build_gmail_service()
        msg_id = send_email(service, to, cc, subject, html_body)
        log(f"Sent successfully (message ID: {msg_id})")
    except Exception as e:
        log(f"ERROR sending email: {e}")
        sys.exit(1)

    # Clean up: remove pending_email.json and push
    PENDING_EMAIL.unlink()
    log("Deleted pending_email.json")
    git_commit_and_push()

    log("--- Done ---")


if __name__ == "__main__":
    main()
