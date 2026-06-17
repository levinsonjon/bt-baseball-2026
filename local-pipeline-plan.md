# Plan: Move daily generation fully local

**Status:** Approved design, not yet built. Start when ready — there is no deadline.
**Author:** drafted 2026-06-17 after the Nth empty-DATA-draft incident.
**Goal:** Retire the remote Claude trigger and generate the daily report locally, eliminating the empty-DATA-draft failure class permanently.

---

## Why

The daily pipeline's only reason for being remote is historical: the report was built around Claude's `WebSearch` tool, which needs a Claude session. Everything stat-critical can come from the **free MLB Stats API**, locally, deterministically — proven on 2026-06-17 when the entire 16-player slate (box scores + season stats) was pulled in ~10 seconds with zero web searches.

The remote path has failed repeatedly (empty DATA drafts ~6/02–6/16/2026, plus earlier outages). Root cause: the remote run does ~64 WebSearches on a long horizon and runs out of headroom before creating the drafts, leaving an empty/missing draft. We have patched the prompt 3+ times; guards can't fix a run that dies. An **interim** fix is in place (2 searches/player + opus-4-8 model, applied 2026-06-17) but the durable fix is to stop depending on a long remote run for load-bearing data.

### Failure classes this eliminates
- Empty DATA drafts (agent ships skeleton/empty body).
- Missing email draft (run dies mid-step-10).
- Gmail-draft handoff fragility (two-draft split, subject-prefix routing).
- Stream idle-timeouts on large `create_draft` bodies.
- Remote read-only-git workaround (the whole reason the Gmail handoff exists).
- Schema drift from the agent (normalizer in `send_pending_email.py`).

### What still remains after the move
- Weekly Gmail OAuth re-auth — still needed to **send** the email (`gmail-fb` creds). Unchanged.
- launchd scheduling on Jon's Mac. Unchanged.
- DNS/offline-at-cron-time fragility — same as today; next run self-heals.

---

## Architecture

One new local launchd job, **~5:00am ET** (before the existing 5:30am send job, or merged into it).

```
generate_local.py  (NEW orchestrator)
  1. Load roster (data/my_team.json)
  2. Resolve MLB player IDs        ← reuse update_health.py resolver + cache
  3. Pull yesterday box scores     ← MLB Stats API gameLog
  4. Refresh season stats          ← MLB Stats API season totals (+ swap-delta logic)
  5. Pull injuries                 ← ESPN injuries API (already used by update_health.py)
  6. Thin Claude news call         ← Anthropic API + server-side web_search (news ONLY)
  7. Compute points                ← reuse daily_report.compute_points / export_web_data
  8. Write data/{yesterday,news,season_stats}.json
  9. Build HTML email              ← reuse daily_report.build_html_email
 10. git add/commit/push           ← reuse send_pending_email.py push path
 11. Send email                    ← reuse send_pending_email.py gmail-fb send path
```

No Gmail drafts. No subject-prefix routing. No JSON-in-email-body. The data files are written directly and pushed; the email is sent directly.

---

## Data sources (detail)

### Box scores — MLB Stats API
- Endpoint: `https://statsapi.mlb.com/api/v1/people/{id}/stats?stats=gameLog&season=2026&group={hitting|pitching}&gameType=R`
- Filter splits to `split.date == yesterday`. If none → DNP.
- Hitter fields: `atBats, hits, homeRuns, rbi, runs, stolenBases, baseOnBalls`.
- Pitcher fields: `inningsPitched, earnedRuns, strikeOuts, baseOnBalls, hits, wins, saves, gamesStarted`.
- Opponent/home-away available on the split (`opponent.name`, `isHome`) for the "Opp" column.
- **Reference implementation:** the 2026-06-17 catch-up script (logic captured below in Appendix A).

### Player IDs
- Reuse `update_health.py`: `load_player_id_cache()` / `search_mlb_player_id()` / `resolve_player_ids()`.
- Cache file `data/mlb_player_ids.json`. NOTE: cache currently holds some pre-swap IDs (Stanton, Lindor, Cal Raleigh). The resolver should key on `current_player or name` and refresh missing/swapped entries. Confirmed working IDs as of 6/17: Basallo 694212, McGonigle 805808, Rice 700250.

### Season stats
- **Non-swapped slots:** pull season totals from MLB Stats API
  `…/people/{id}/stats?stats=season&season=2026&group={hitting|pitching}` and overwrite stored values
  (AB/AVG/HR/RBI/R/SB for hitters; IP/G/GS/ERA/K/BB/W[/SV] for pitchers).
- **Swapped slots (`current_player` set):** do NOT use season totals (double-counts pre-swap games).
  Read existing `season_stats.json[slot_name]`, add yesterday's deltas, recompute AVG = H/AB and
  ERA = ER×9/IP (derive existing_ER = ERA×IP/9 since ER isn't stored). Same logic as the remote prompt step 7
  and the 6/17 catch-up.
- Guardrail: never let a counting stat go backwards vs. stored value (self-heals from a missed run).

### Injuries — ESPN API
- `https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/injuries` — already fetched in `update_health.py`.
- Match to roster by normalized `current_player or name`. Produce the `injuries[]` array for news.json.

### News — thin Claude API call (the one LLM dependency)
- **Scope:** news prose ONLY. All stat-critical data comes from APIs above; news is cosmetic and degrades gracefully.
- **How:** Anthropic Messages API with the server-side web search tool. Read the `claude-api` skill before
  implementing (model ids, web search tool block, pricing, SDK usage).
  - Model: a cheap/fast tier is fine — `claude-haiku-4-5` or `claude-sonnet-4-6`. News quality at haiku is
    acceptable; bump to sonnet if blurbs feel thin.
  - Tool: server-side web search (`web_search` tool type — confirm current version id via the claude-api skill).
  - One call, batched: pass the 16 players + their box-score lines, ask for a 1–2 sentence blurb per player and
    up to 1 source URL each, returned as strict JSON. Feeding the box score in keeps it grounded and cuts searches.
  - API key: store outside the repo (e.g. `~/.config/personal-mcp/anthropic/key` or a launchd env var). Do NOT
    commit it.
- **Graceful degradation:** if the news call fails (no key, API down, timeout), fall back to a templated summary
  from the box score ("2-for-4 with a HR and 2 RBI vs MIA") so the site still publishes. News failure must NEVER
  block the stat/email pipeline.

---

## Reuse map (≈80% reused)

| Reused as-is | From |
|---|---|
| `compute_points`, `export_web_data`, `build_html_email`, scoring constants | `daily_report.py`, `config.py` |
| git fetch/rebase/commit/push path | `send_pending_email.py` |
| gmail-fb send path | `send_pending_email.py` |
| MLB ID cache + resolver | `update_health.py` |
| ESPN injuries fetch | `update_health.py` |
| Data file schemas | existing `data/*.json` |

New code is essentially the 6/17 catch-up script generalized to "yesterday" + the thin news call + wiring.

---

## Migration / cutover

1. Build `generate_local.py`; run it with `--preview` (write to a temp dir, diff against the remote-produced files) for a few days **in parallel** with the remote trigger.
2. When the local output matches (stats identical, news acceptable), switch the launchd send job to consume local output instead of the DATA draft.
3. Disable the remote trigger: `RemoteTrigger update` with `enabled: false` (keep the config for rollback). Trigger ID `trig_01AWGDMAqyJY5oZNYiqKQQdT`.
4. Simplify `send_pending_email.py` (or fold it into `generate_local.py`): drop DATA-draft discovery, JSON extraction, normalizer, empty-draft detection — all dead once there's no draft handoff.
5. Update `CLAUDE.md`: replace the two-stage remote+local description with the single local pipeline; move the remote-trigger and two-draft sections to a "Retired" note.
6. Keep `update_health.py`'s freshness Reminder (`check_pipeline_freshness`) — still the safety net if the local job fails to update `data/yesterday.json`.

## Rollback
- Re-enable the remote trigger (`enabled: true`) and restore the prior `send_pending_email.py`. The Gmail-draft handoff is unchanged and resumes immediately. Keep the remote trigger config untouched until local has run clean for ~2 weeks.

---

## Decisions made
- **News = thin Claude API call with web search** (not fully templated). Stats/injuries stay API-driven; news is the only LLM dependency and degrades to templated box-score summaries on failure.

## Open questions (resolve at build time)
- Merge `generate_local.py` into the 5:30am send job, or keep a separate ~5:00am job? (Separate is cleaner for parallel-run testing.)
- Where to store the Anthropic API key (config file vs. launchd `EnvironmentVariables`).
- Confirm the current `web_search` tool version id and haiku-vs-sonnet news quality via the `claude-api` skill.
- Refresh/repair `data/mlb_player_ids.json` for swapped slots as part of step 2.

## Effort
~Half a day to build + a few days of parallel-run validation before cutover.

---

## Appendix A — proven 6/17 catch-up logic (box score fetch)

```python
# Resolve missing IDs via people/search?names=, then per player:
url = f"https://statsapi.mlb.com/api/v1/people/{pid}/stats?stats=gameLog&season=2026&group={grp}&gameType=R"
splits = data["stats"][0]["splits"]
day = [s for s in splits if s.get("date") == YESTERDAY]   # empty -> DNP
# hitting:  st = day[0]["stat"] -> atBats, hits, homeRuns, rbi, runs, stolenBases, baseOnBalls
# pitching: st -> inningsPitched, earnedRuns, strikeOuts, baseOnBalls, hits, wins, saves, gamesStarted
# opponent: day[0]["opponent"]["name"], home/away: day[0]["isHome"]
```
Scoring (from `daily_report.compute_points`): hitters = HR+RBI+R+SB; SP = (1.2×4.20 − (ER/IP×9))×(IP/9); RP = 5×(W+SV).
Season swap-delta: existing_ER = ERA×IP/9; new_ERA = (existing_ER+today_ER)×9/(IP+today_IP); AVG = H/AB.
