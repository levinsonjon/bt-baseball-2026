# Fantasy Baseball — BT Baseball Pool 2026

## Overview

Fantasy baseball project for Jon's BT Baseball Pool 2026 league. Includes draft tools, player projections, a daily report pipeline that emails Jon every morning, and a responsive web interface at **https://www.btbaseball.com**.

## GitHub

- Repo: `levinsonjon/bt-baseball-2026` (public)
- URL: https://github.com/levinsonjon/bt-baseball-2026

## Web interface

- Domain: `btbaseball.com` (apex redirects to `www.btbaseball.com`)
- Hosted on Vercel (project: `bt-baseball-2026`), static-site preset
- DNS: Squarespace Domains — A record `@` → `76.76.21.21`, CNAME `www` → `cname.vercel-dns.com`
- Three views, all mobile-responsive:
  - `/` — Team Overview (roster + season stats + YTD points + projected season total)
  - `/yesterday` — per-player game stats for the previous day
  - `/news` — synthesized player-level headlines + injury report
- Site is pure static HTML/CSS/JS under `web/`; reads data from `/data/*.json` at page load. Routing via `vercel.json` rewrites.

## Daily pipeline

Two stages with handoff via Gmail drafts:

| Stage | Time (ET) | Where | What |
|-------|-----------|-------|------|
| **Remote agent** | ~4:35am | Anthropic cloud | 64 WebSearches (4 per player × 16), updates season stats, builds HTML email, creates **two** Gmail drafts |
| **Local launchd** | 5:30am | Jon's Mac | Consumes DATA draft → commits+pushes data files → sends email draft |

### Why two drafts

A single Gmail draft with the HTML email **plus** embedded JSON (~45 KB body) stalled the Claude stream past its idle-timeout threshold. Splitting into two smaller drafts keeps every tool call fast. See `pipeline-fix-plan.md` for the full story.

| Draft | Subject prefix | Body | Size |
|-------|---------------|------|------|
| **DATA** | `Fantasy Baseball DATA YYYY-MM-DD` | Minimal HTML with three `<script type="application/json">` blocks (`yesterday-data`, `news-data`, `season-stats-data`) | ~10 KB |
| **Email** | `Fantasy Baseball Daily YYYY-MM-DD (X played, Y injury updates)` | Standard HTML report, no embedded JSON | ~25 KB |

Subject prefixes are load-bearing — the local script routes on them.

### Remote trigger

- **Trigger ID:** `trig_01AWGDMAqyJY5oZNYiqKQQdT`
- **Manage:** https://claude.ai/code/scheduled/trig_01AWGDMAqyJY5oZNYiqKQQdT
- **Model:** claude-sonnet-4-6
- **Gmail connector UUID:** `13aa4679-35c5-4850-aaf8-148682f5ac13` (allowed tool: `mcp__gmail__create_draft`)
- **Read-only for git.** `allow_unrestricted_git_push: true` in the config is misleading — the proxy refuses pushes with 403. API-level PAT injection does not work. Gmail is the handoff, full stop.

### Local launchd jobs

| Job | Plist | Schedule | Script |
|-----|-------|----------|--------|
| Daily email send | `com.jon.fantasy-baseball-send` | 5:30am ET | `send_pending_email.py` |
| Health update | `com.jon.fantasy-baseball-health` | 3:13am ET | `update_health.py` |

Plists live in `~/Library/LaunchAgents/`. Manage with `launchctl load/unload`.

### What `send_pending_email.py` does

1. Finds DATA draft by subject prefix → extracts JSON blocks.
2. **Normalizes** the agent's field names to the site's schema (agent drifts: `player_type` → `type`, `fantasy_points` → `points`, `news` → `summary`, etc.). Roster-looks-up missing `team`/`position`.
3. Writes `data/yesterday.json`, `data/news.json`, `data/season_stats.json`.
4. `git add` → `git fetch origin main` → `git rebase -X ours origin/main` → `git commit -m "Daily data update YYYY-MM-DD"` → `git push origin main`. Triggers Vercel redeploy.
5. Deletes the DATA draft.
6. Finds the email draft and sends it.

### Gmail OAuth

Local scripts use credentials at `~/.config/personal-mcp/gmail/`. The GCP app (`personal-claude-mcp-486922`) is in Testing mode — tokens expire weekly. `update_health.py` creates a macOS Reminder when the token is about to expire (previously emailed a warning, but email warnings are useless when the broken credential is the Gmail one).

### Known failure modes

- **Gmail MCP connector disconnects** on claude.ai. Symptom: no drafts appear. Fix: re-authorize the connector at the trigger URL. Watch for read-only vs. full permissions on the OAuth consent screen — the connector needs draft-write scope.
- **Gmail refresh token revoked (not just age-expired).** Google can invalidate the refresh token before its 7-day age TTL — e.g., if multiple clients race on refresh. Symptom: `send_email.log` shows `invalid_grant: Token has been expired or revoked.` and `data/*.json` stops updating even though remote drafts keep appearing. Fix: run the Gmail re-auth command (same as weekly token expiry). The Reminders warning fires on the next cron run after the failure.
- **Schema drift from the agent.** Normalizer in `send_pending_email.py` covers common cases. If the agent invents a field we don't handle, the site gracefully degrades (falls back or shows empty); update the normalizer.
- **Stream idle timeout** on Gmail MCP calls. Keep each draft body <30 KB. If the email HTML grows past that, split again.

## Scoring

- **Hitters:** BA × 1000 + HR + RBI + R + SB (300 AB minimum rule at season end)
- **Starting Pitchers:** RSAR = (1.2 × MLB_AVG_ERA − ERA) × (IP/9), top 3 of 6 × 3.5 multiplier
- **Relief Pitcher:** 5 × (W + SV)

Team AVG on the site is the **flat mean** of per-player AVGs (because each player's BA×1000 contributes to the team total — so the team AVG represents scoring contribution, not AB-weighted batting average).

## Key files

| File | Purpose |
|------|---------|
| `config.py` | League settings, scoring formula, roster slots, Google Sheet IDs |
| `daily_report.py` | `DayResult`, `build_html_email()`, `build_data_draft_html()`, `export_web_data()` |
| `run_daily.py` | Entry point for the daily report generator (designed for Claude Code sessions) |
| `send_pending_email.py` | Local launchd script: consumes DATA draft → pushes data → sends email |
| `update_health.py` | Daily health/injury updater for Google Sheets |
| `draft.py` | Draft tools: roster loading, draft recommendations |
| `players.py` | Player projections and scoring calculations |
| `vercel.json` | Vercel routing: `/`, `/yesterday`, `/news` rewrites to `web/*.html` |
| `favicon.svg` | ⚾ emoji favicon |
| `pipeline-fix-plan.md` | Design doc for the two-draft split (2026-04-19) |
| `web/` | Static site (3 HTML pages + assets) |
| `data/my_team.json` | Jon's 16-player roster (set at draft; `updated` is draft date) |
| `data/season_stats.json` | Season-to-date stats — schema: `{AB, AVG, HR, RBI, R, SB}` for hitters, `{IP, G, GS, ERA, K, BB, W[, SV]}` for pitchers |
| `data/yesterday.json` | Per-player game stats for the previous day (written by local script from DATA draft) |
| `data/news.json` | Synthesized news + injury report (written by local script from DATA draft) |

## Email recipients

- **To:** levinson.jon@gmail.com
- **CC:** levinsonlgs@gmail.com
