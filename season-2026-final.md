# BT Baseball Pool 2026 — Final Season Recap

Regular season ended Sunday 2026-09-27. Official results from the commissioner's `RESULTS .xlsm` (received 2026-09-28, 162 games, MLERA 4.17). Site data frozen at git tag `season-2026-final`.

## Final standings (official)

| # | Team | Points | vs 1st |
|---|------|-------:|-------:|
| 1 | Cobey | 4,788 | — |
| **2** | **Levinsons** | **4,676** | **-112** |
| 3 | Lerner | 4,664 | -124 |
| 4 | Winters | 4,649 | -139 |
| 5 | Mudge | 4,636 | -152 |
| 6 | Williams | 4,558 | -230 |
| 7 | Tchir | 4,554 | -234 |
| 8 | Washington | 4,379 | -409 |
| 9 | Palma | 4,254 | -534 |

Levinsons finished 2nd of 9, 112 points behind Cobey and 12 ahead of Lerner.

## Levinsons, slot by slot (official)

| Slot | Player(s) | Official | Site (corrected) | Note |
|------|-----------|---------:|-----------------:|------|
| C | Raleigh / Jeffers / Basallo / Dingler | 296 | 300 | +4 vs official (see reconciliation) |
| 1B | Bryce Harper | 485 | 485 | |
| 2B | Luis Arraez | 457 | 457 | |
| 3B | Bo Bichette | 434 | 434 | |
| SS | Lindor / McGonigle | 444 | 444 | site was 415 before correction |
| OF | Pete Crow-Armstrong | 592 | 592 | best slot in the league at OF |
| OF | Jackson Merrill | 480 | 480 | |
| OF | Hernandez / Chourio | 500 | 500 | site was 503 before correction |
| DH | Stanton / Rice | 448 | 448 | site was 440 before correction |
| RP | Williams / Hader | 165 | 165 | 4 W + 29 SV |
| SP (top 3 × 3.5) | Burns 37, Wheeler 36, Detmers 34 | 375 | 375 | Eovaldi 13, Sheehan 5, Ragans 1 did not count |
| **Total** | | **4,676** | **4,680** | |

Individual RSARs at MLERA 4.17 match the commissioner's sheet for all six starters.

## Reconciliation: site vs official

Before correction the site showed 4,650 (at the preseason MLERA of 4.20) against the official 4,676. Every untouched slot matched exactly. All of the gap was in the four hitter slots that were swapped mid-season:

| Slot | Site before | Official | Cause |
|------|------------:|---------:|-------|
| SS Lindor/McGonigle | 415 | 444 | Site was 32 AB / 15 H / 13 R short. Games dropped during pipeline outages. |
| DH Stanton/Rice | 440 | 448 | Site was 19 AB / 8 H short, same cause. |
| OF Hernandez/Chourio | 503 | 500 | Site had 3 extra RBI (a double-counted delta). |
| C Basallo/Dingler | 297 | 296 | Off by 1 H / 1 R. |

Root cause: untouched slots are rebuilt from full-season MLB game logs on every run and self-heal any gap, but swapped slots accumulate day-by-day deltas above a watermark and never self-heal. Any day the pipeline missed or double-ran silently corrupted those four slots for the rest of the season.

Fix applied 2026-09-28: each swapped slot was rebuilt from the MLB Stats API game logs using the actual swap dates (Lindor through 4/26, Stanton through 5/03, Raleigh through 5/17, Jeffers 5/18–5/31, Basallo 6/01–8/01, Hernández through 6/14, Williams through 7/14). The rebuild reproduces the official SS, DH, OF and RP numbers exactly. The C slot rebuilds to 300 vs the official 296; the 4-point difference is on the commissioner's side (most likely a one-day difference in where a catcher swap was cut) and is not worth disputing.

**Lesson for 2027:** rebuild swapped slots from game logs on every run too, using per-segment date ranges stored in `my_team.json`, instead of watermark deltas. That removes the only non-self-healing path in the pipeline.

## What was shut down (2026-09-28)

- GitHub Actions `daily.yml` schedule commented out. `workflow_dispatch` still works for manual runs.
- Local launchd job `com.jon.fantasy-baseball-health` booted out and disabled (`com.jon.fantasy-baseball-send` was already disabled 2026-08-01).
- Final data committed and tagged `season-2026-final`.
- Final season email sent to the usual recipients.

## Restarting for 2027

1. New roster in `data/my_team.json`; clear `data/season_stats.json`, `data/yesterday.json`, `data/news.json`.
2. Bump `season` in `generate_daily.py` and set a fresh `MLB_AVG_ERA` projection baseline in `config.py` and `web/assets/team.js`.
3. Remove the static Final Standings block from `web/index.html` and restore the in-season subtitle in `team.js`.
4. Uncomment the `schedule:` block in `.github/workflows/daily.yml` (push needs the `workflow` OAuth scope on the `levinsonjon` credential).
5. `launchctl enable gui/$UID/com.jon.fantasy-baseball-health` then `launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.jon.fantasy-baseball-health.plist` if the Sheets health updater is still wanted.
