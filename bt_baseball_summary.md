# BT Baseball Pool 2026 — Draft & Season Management Tool

A custom Python app built to manage the full lifecycle of a fantasy baseball season: pre-draft player rankings, live draft-day pick tracking, and daily in-season stat reporting.

---

## What It Does

**Before the Draft**
- Loads projected player stats from PitcherList (Excel export)
- Applies the league's custom scoring formula to rank every player
- Pushes ranked player lists to a shared Google Sheet with tabs for Overall Rankings, By Position, and Draft Board

**On Draft Day**
- Monitors the shared Google Sheet for new picks in real time (polls every 30 seconds)
- Auto-tracks whose turn it is based on the snake draft order
- Surfaces live recommendations: best available overall, plus positional boosts when the roster has open slots
- Logs all picks and saves the final roster to a local file

**During the Season**
- Runs a daily report that pulls box scores and injury news via web search
- Computes each player's daily points using the league scoring rules
- Emails a formatted HTML summary showing today's stats, season totals, and injury flags
- Runs a nightly health update job that checks ESPN for injury changes and updates the shared Google Sheet

---

## League Settings

- 9-team snake draft, 16-man rosters (9 hitters, 6 SP, 1 RP)
- **Hitter scoring:** BA×1000 (300 AB minimum) + HR + RBI + R + SB
- **SP scoring:** RSAR×3.5 (top 3 of 6 starters only)
- **RP scoring:** 5×(Wins + Saves)
- Injury flags reduce projections proportionally (e.g., IL-60 = 20% of projection)
- Dual-position eligibility supported (e.g., a 2B/SS fills either slot)

---

## Tech Stack

| Layer | Tool |
|---|---|
| Language | Python 3 |
| Player data | PitcherList Excel projections |
| Injury data | ESPN public injuries API |
| Shared draft board | Google Sheets API |
| Daily stat lookups | Web search (automated queries) |
| Email reports | Gmail API |

---

## Setup Requirements

1. Python 3 + dependencies
2. PitcherList projection export (Excel) placed in the data folder
3. Google Sheet ID and OAuth credentials configured
4. League draft pick number set before draft day

---

*This is a single-user tool — built around one person's roster and scoring preferences — but the projection engine, draft monitor, and daily reporting can all be adapted for other leagues by updating the scoring parameters.*
