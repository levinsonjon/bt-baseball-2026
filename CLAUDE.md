# Fantasy Baseball — BT Baseball Pool 2026

## Overview

Fantasy baseball project for Jon's BT Baseball Pool 2026 league. Includes draft tools, player projections, daily report generation, health tracking, and Google Sheets integration.

## GitHub

- Repo: `levinsonjon/bt-baseball-2026` (public)
- URL: https://github.com/levinsonjon/bt-baseball-2026

## Daily Report Pipeline

The daily report runs as a two-stage pipeline:

| Stage | Time (ET) | Where | What |
|-------|-----------|-------|------|
| **Remote agent** | 4:30am | Anthropic cloud | Clones repo, WebSearches stats/news/injuries for all 16 players, builds HTML email, creates Gmail draft via claude.ai Gmail connector |
| **Local launchd** | 5:30am | Jon's Mac | Finds draft by subject prefix ("Fantasy Baseball Daily"), sends it via Gmail API using local OAuth credentials |

### Remote Trigger

- **Trigger ID:** `trig_01AWGDMAqyJY5oZNYiqKQQdT`
- **Manage:** https://claude.ai/code/scheduled/trig_01AWGDMAqyJY5oZNYiqKQQdT
- **Model:** claude-sonnet-4-6
- **Gmail connector UUID:** `13aa4679-35c5-4850-aaf8-148682f5ac13`
- The remote agent cannot push to GitHub (read-only git proxy). The Gmail draft is the handoff mechanism.
- **Known issue:** The claude.ai Gmail MCP connector can silently disconnect. When this happens, the remote agent falls back to writing `data/pending_draft.json`, which can't be delivered (git push is read-only). If the morning email doesn't arrive, check connector status at the trigger management URL and re-authorize.

### Local launchd Jobs

| Job | Plist | Schedule | Script |
|-----|-------|----------|--------|
| Daily email send | `com.jon.fantasy-baseball-send` | 5:30am ET | `send_pending_email.py` |
| Health update | `com.jon.fantasy-baseball-health` | 3:13am ET | `update_health.py` |

Plists live in `~/Library/LaunchAgents/`. Manage with `launchctl load/unload`.

### Gmail OAuth

Local scripts use credentials at `~/.config/personal-mcp/gmail/`. The GCP app (`personal-claude-mcp-486922`) is in Testing mode — tokens expire weekly. `update_health.py` sends a warning email when the token is about to expire.

## Key Files

| File | Purpose |
|------|---------|
| `config.py` | League settings, scoring formula, roster slots, Google Sheet IDs |
| `daily_report.py` | Report builder: DayResult class, HTML email formatter, season stats |
| `run_daily.py` | Entry point for daily report (designed for Claude Code sessions) |
| `send_pending_email.py` | Local script: finds and sends Gmail draft via Gmail API |
| `update_health.py` | Daily health/injury updater for Google Sheets |
| `draft.py` | Draft tools: roster loading, draft recommendations |
| `players.py` | Player projections and scoring calculations |
| `data/my_team.json` | Jon's 16-player roster |
| `data/season_stats.json` | Cumulative season stats (updated by daily report) |

## Scoring

- **Hitters:** BA x 1000 + HR + RBI + R + SB (300 AB minimum rule)
- **Starting Pitchers:** RSAR = (1.2 x AvgERA - ERA) x (IP/9), top 3 of 6 x 3.5
- **Relief Pitcher:** 5 x (W + SV)

## Email Recipients

- **To:** levinson.jon@gmail.com
- **CC:** levinsonlgs@gmail.com
