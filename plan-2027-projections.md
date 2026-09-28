# 2027 Plan: Turning the 2026 Retrospective into Model and Process Changes

Status: **approved 2026-09-28; all six workstreams built and backtested the same day.** What remains is the March 2027 step: a fresh PitcherList export, `python3 build_history.py --seasons 2024 2025 2026`, then `run_projections.py` and the draft. Written from the findings in `season-2026-retrospective.md`. Per-workstream status is in the table at the bottom.

## What 2026 taught us, in one line each

1. Hitters were over-projected by 42 points per player because the projections assume full playing time.
2. Above pick 20 the board's ordering had no edge; the busts at the top were injuries.
3. Innings, not ERA, separated the late starters who mattered (Detmers) from the ones who did not (Ragans, Sheehan).
4. The one bad swap of the year (the catcher chain, -29) was a hold-versus-replace decision that was never modelled.
5. In-season moves were worth 2,302 points league-wide; the tools for them were rebuilt ad hoc three times.
6. The site under-reported swapped slots by 34 points because those slots do not self-heal.

## The plan

Six workstreams, ordered so that each one can be validated against 2026 data before the next begins. The 2026 season is now a complete backtest: every projection, pick, swap and outcome is in the repo.

### 1. Playing-time model (largest expected gain)

**Goal:** replace "everyone plays a full season" with an expected-games figure per player, and scale counting stats by it.

- **Inputs:** games played in each of the prior three seasons (MLB Stats API, already used by the pipeline), age, IL stints in the prior two seasons (ESPN injuries feed, already scraped by `update_health.py`), and position (catchers rest more).
- **Method:** expected AB = projected per-game AB rate × expected games, where expected games starts at a positional baseline (about 148 for a regular, 125 for a catcher) and is discounted by age over 32, by each IL stint in the prior two years, and by any current spring injury flag. Same for starters with IP.
- **Where:** `projections.py`, a new `playing_time.py` module, and a new column in the projections cache so the draft tool and `/bt-substitute` both see it.
- **Validation:** rerun the 2026 draft board with the new model and check whether the hitter bias drops toward zero and whether Stanton, Rooker and Judge move down the board. Target: mean hitter miss within 15 points; correlation above 0.35 on the drafted pool.
- **Effort:** about two working sessions. The data pulls exist; the work is the discount table and the backtest.

### 2. Top-of-board risk discount

**Goal:** stop treating a 590 projection as worth 100 points more than a 490 projection when the extra 100 is mostly variance.

- **Method:** rank the first three rounds by a risk-adjusted score: projection minus a penalty proportional to the player's projection standard deviation from the playing-time model. Show both numbers on the draft board so the choice is visible on draft day.
- **Where:** `draft.py` recommendation scorer and the Rankings sheet pushed by `push_to_sheets.py`.
- **Validation:** on the 2026 board, does the risk-adjusted top 20 contain fewer of the seven biggest busts? Does it still contain Crow-Armstrong and Alvarez in the top 20?
- **Effort:** one session, after workstream 1 exists.

### 3. Innings-weighted late starters

**Goal:** for the second starter in each drafted pair, prefer the pitcher likely to throw 180 innings at a 3.5 ERA over one projected for 120 at 3.1.

- **Method:** the RSAR formula already rewards innings; the fix is on the projection side, where expected IP comes from workstream 1 and the recommendation boosts starters whose expected IP is above 160. Add a "three that count" simulator to the draft tool: given the starters already drafted, how much does each candidate raise the expected best-three sum?
- **Where:** `draft.py` (the SP pairing logic at lines 450 to 490 is the natural home), `config.py` for the IP threshold.
- **Validation:** the 2026 second-of-pair starters for all nine teams; Detmers and Rasmussen should rank above Ragans and Sheehan under the new score.
- **Effort:** one session.

### 4. Hold-versus-replace calculator for injured starters

**Goal:** answer the question the catcher chain never asked: given a star on the IL with an expected return date, does swapping to the best free agent beat holding him?

- **Inputs:** expected return date (from the injury feed or entered by hand), the incumbent's rest-of-season projection after return, the best free agent's rest-of-season projection, the 300 AB floor for hitters, and the swap cost (a used substitution).
- **Method:** points if held = incumbent's production from return date to season end. Points if swapped = replacement's production from swap date to season end. Recommend the higher, and show the break-even return date so Jon can judge the injury news himself.
- **Where:** extend the `/bt-substitute` skill with a `--hold` comparison, reusing its rest-of-season projection code and the 30-day-usage method from the 7/13 analysis.
- **Validation:** the 2026 Raleigh case (should recommend hold at a mid-June return date), the Lindor case (swap), the Stanton case (swap).
- **Effort:** one session. Most of the pieces exist in the skill.

### 5. Make the swap-window method the standard tool

**Goal:** the 7/13 roster-wide analysis was the best decision tool of the year and lives only in a memory file. Turn it into a repeatable command.

- **Method:** a `swap_window.py` script that reconstructs all nine rosters from the draft tracker plus the latest BBSUBS file, builds the true free-agent pool, projects rest-of-season points for every incumbent and every free agent using the blended-rate and 30-day-usage method, and prints the per-slot upgrade table. Run it before every substitution window, not just the unrestricted one.
- **Where:** new script in the repo, plus the surname-collision guard already noted in memory. The `/bt-substitute` skill becomes a thin wrapper that calls it for one slot.
- **Validation:** rerun on the 7/13 snapshot and confirm it reproduces the Hader recommendation.
- **Effort:** two sessions, including the roster reconstruction code.

### 6. Pipeline fix: rebuild swapped slots from game logs

**Goal:** remove the only non-self-healing path in the daily pipeline.

- **Method:** store each slot's segments in `my_team.json` as a list of `{player, from, to}` date ranges instead of a composite name plus a watermark. `generate_daily.py` rebuilds every slot from full-season game logs filtered by segment, exactly as the 9/28 reconciliation script did. The watermark and `apply_swap_deltas` go away.
- **Where:** `generate_daily.py`, `my_team.json` schema, `team.js` (display of composite names).
- **Validation:** rebuild the 2026 season from the final `my_team.json` and confirm the totals match the official sheet within the known 4-point catcher variance.
- **Effort:** one session. This one is independent of the others and can go first.

## Proposed order and timing

| When | Workstream | Why then |
|------|-----------|----------|
| October | 6. Pipeline fix | Independent, small, and the 2026 data makes the test trivial |
| November | 1. Playing-time model | Everything else depends on it |
| December | 2. Risk discount, 3. Innings weighting | Both consume workstream 1's output; both validate on the 2026 board |
| January | 5. Swap-window tool | Needs no new projections; needs the roster reconstruction code |
| February | 4. Hold-versus-replace | Reuses 5's rest-of-season code |
| March | Refresh projections for 2027, rerun the whole board, draft | |

## Status (updated 2026-09-28)

| Workstream | Status | Result on the 2026 backtest |
|-----------|--------|------------------------------|
| 6. Pipeline fix | **Done** (`generate_daily.py` segments) | Rebuild reproduces all 16 official slot scores |
| 1. Playing-time model | **Done** (`playing_time.py`, `build_history.py`, `backtest_2026.py`) | Hitter bias −42 → −10, MAE 66 → 59, corr 0.20 → 0.28; RP corr 0.28 → 0.50; SP unchanged (starters take only an IL/red-flag discount, since continuous history scaling made them worse); team-total miss vs drafted-16 actuals 374 → 193. The corr ≥ 0.35 target was not reached. |
| 2. Risk discount | **Done, as a visible read only** (`playing_time.risk_profile`, shown in `draft.py`) | Subtracting a risk penalty removed at most 2 of the 7 biggest busts from the top 20 and added no breakouts, so risk is displayed (tier + note + PT factor) and never re-ranks. |
| 3. Innings weighting | **Done, as a simulator** (`DraftMonitor.sp_depth_value`) | Regressing ERA toward league average made SP correlation worse (0.27 → 0.20; second-of-pair starters corr 0.03), so the formula is untouched. Instead the second of each SP pair is chosen by expected marginal top-3 points under innings variance. |
| 5. Swap-window tool | **Done** (`swap_window.py`, `data/draft_board_2026.py`) | Reproduces the 7/13 analysis: Hader +54 (memory +48), Duran +39 (+32), every slot's top pick identical, magnitudes within 6 |
| 4. Hold-vs-replace | **Done** (`swap_window.py --hold --slot X --return-date D`) | Lindor 4/27: replace by 62 (actual +83). Stanton 5/03: replace by 175 (actual +345). Raleigh 5/18: replace by 35 with Jeffers projected 389, which was the defensible ex-ante call; hindsight favoured holding (325 vs 296) only because Jeffers then broke his hamate. The tool prints the break-even return date so the injury read stays Jon's. |

## Explicitly out of scope

- Replacing the projection source. The rate-stat projections were fine (Merrill, Arraez, Harper within 6). The misses were playing time and variance, not rates.
- Any automation of the substitution itself. Recommendations only; Jon makes and files the move.
- League-facing tooling. Everything here is for Jon's own draft and roster decisions.

## Decisions needed from Jon before starting

1. Approve the order above, or reorder.
2. Whether the playing-time model should use a simple discount table (fast, transparent) or a fitted model on prior seasons (more accurate, more work). Recommendation: discount table first, fit later if the backtest disappoints.
3. Whether to keep the 2026 projections cache and draft board as a permanent backtest fixture in the repo (recommended; it is 530 KB and the repo is public, but the data is public too).
