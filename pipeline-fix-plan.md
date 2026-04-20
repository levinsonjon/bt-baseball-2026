# Pipeline Fix Plan — Split Gmail Draft into Data + Email

**Status:** drafted 2026-04-19 after two failed manual runs hit `API Error: Stream idle timeout - partial response received`.
**Root cause:** The single `mcp__gmail__create_draft` call with a ~45–50KB body (HTML email + two embedded JSON blocks) stalls the Claude stream past the idle threshold. Prompt trimming did not help — the bottleneck is the tool call itself.

---

## The fix

Have the remote agent create **two separate Gmail drafts** per run:

| Draft | Subject | Body | Size |
|-------|---------|------|------|
| **A — data** | `Fantasy Baseball DATA YYYY-MM-DD` | Minimal HTML wrapper containing only the two `<script type="application/json">` blocks (`id="yesterday-data"`, `id="news-data"`) | ~10 KB |
| **B — email** | `Fantasy Baseball Daily YYYY-MM-DD (X played, Y injury updates)` | The HTML email **without** embedded JSON. Same format as today's `build_html_email()`. | ~25–30 KB |

Two small tool_use blocks instead of one large one — each completes well under the stream-idle budget.

---

## Concrete changes

### 1. Trigger prompt (via `RemoteTrigger(action="update")`)

Replace step 10 ("Embed BOTH JSON payloads in the HTML...") and step 11 ("Create a Gmail draft...") with:

```
10. Create Gmail Draft A using `mcp__gmail__create_draft`:
    - to: "levinson.jon@gmail.com"
    - cc: (none — data draft is internal, gets auto-deleted by local script)
    - subject: "Fantasy Baseball DATA {YYYY-MM-DD}"
    - contentType: "text/html"
    - body:
        <html><body>
        <script type="application/json" id="yesterday-data">{...yesterday JSON...}</script>
        <script type="application/json" id="news-data">{...news JSON...}</script>
        </body></html>

11. Create Gmail Draft B using `mcp__gmail__create_draft`:
    - to: "levinson.jon@gmail.com"
    - cc: "levinsonlgs@gmail.com"
    - subject: "Fantasy Baseball Daily — {Month DD, YYYY} (X played, Y injury updates)"
    - contentType: "text/html"
    - body: the HTML email from build_html_email() — NO embedded JSON

Two distinct subject prefixes so the local script can tell them apart:
  - "Fantasy Baseball DATA" → data draft
  - "Fantasy Baseball Daily" → email draft
```

Also **remove** the JSON embedding from `build_html_email()` in `daily_report.py` — it's now injected directly into Draft A's body, separate from the email.

### 2. `send_pending_email.py`

Add a new phase before the existing send logic:

```python
DATA_SUBJECT_PREFIX = "Fantasy Baseball DATA"
EMAIL_SUBJECT_PREFIX = "Fantasy Baseball Daily"

def find_draft_by_prefix(service, prefix: str) -> str | None:
    """Generalize find_daily_report_draft to accept any subject prefix."""
    # (same as existing find_daily_report_draft but parameterized)

def consume_data_draft(service, draft_id: str):
    """Extract JSON from data draft, write files, commit+push, delete the draft."""
    html = get_draft_html(service, draft_id)
    blocks = extract_json_blocks(html)
    if blocks:
        written = write_data_files(blocks)
        report_date = ... # from blocks["yesterday-data"]["date"]
        git_commit_and_push(written, report_date)
    # delete the data draft regardless — it has served its purpose
    service.users().drafts().delete(userId="me", id=draft_id).execute()

def main():
    ...
    # Phase 1: consume the data draft (writes files, pushes to GitHub)
    data_draft_id = find_draft_by_prefix(service, DATA_SUBJECT_PREFIX)
    if data_draft_id:
        try:
            consume_data_draft(service, data_draft_id)
        except Exception as e:
            log(f"ERROR consuming data draft: {e}")

    # Phase 2: send the email draft (existing logic)
    email_draft_id = find_draft_by_prefix(service, EMAIL_SUBJECT_PREFIX)
    ...
```

Remove the `sync_web_data()` function — obsolete once the data draft handles it.

### 3. `daily_report.py`

`build_html_email()` should STOP auto-embedding the `<script>` blocks. The HTML email goes back to the format it had before the web interface — just the human-readable report.

Add a small helper to build the data-draft HTML wrapper:

```python
def build_data_draft_html(report_date, day_results) -> str:
    yesterday, news = export_web_data(report_date, day_results)
    return (
        '<html><body>'
        f'<script type="application/json" id="yesterday-data">{json.dumps(yesterday, ensure_ascii=False)}</script>'
        f'<script type="application/json" id="news-data">{json.dumps(news, ensure_ascii=False)}</script>'
        '</body></html>'
    )
```

---

## Testing

1. Apply prompt update + code changes.
2. Fire `RemoteTrigger(action="run")`.
3. Monitor for **both** drafts appearing in Gmail. Expected elapsed: ~12–18 min (one additional tool call, both smaller).
4. Run `python3 send_pending_email.py` manually to verify:
   - Finds data draft, extracts JSON, writes files, commits, pushes, deletes data draft.
   - Finds email draft, sends it.
5. Check Vercel redeploys and `bt-baseball-2026.vercel.app` shows today's data.

## Rollback

If two-draft approach still times out (unlikely but possible), fall back to manually running the daily report locally via Claude Code (which is what Jon was doing April 10–17). That bypasses the remote trigger entirely.

## Context for tomorrow-me

- Trigger ID: `trig_01AWGDMAqyJY5oZNYiqKQQdT`
- Manage URL: https://claude.ai/code/scheduled/trig_01AWGDMAqyJY5oZNYiqKQQdT
- Remote agent is **read-only for git** — confirmed 2026-04-19 via 403 from git proxy. See `memory/remote_agent_git_limitation.md`. The `allow_unrestricted_git_push` flag is misleading; API-level PAT injection does not work.
- The trimmed prompt (as of 2026-04-19T19:59Z) is the baseline to modify.
- Local send script and `daily_report.export_web_data()` already do the JSON extraction heavy lifting. The changes are mostly rewiring, not new code.
