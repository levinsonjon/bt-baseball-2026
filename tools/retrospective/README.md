# Retrospective page builders

Regenerate the two published artifacts from the 2026 season wrap.

| Script | Builds | Published at |
|--------|--------|--------------|
| `build_artifact.py` | `bt-2026-retrospective.html` from `../../season-2026-retrospective.md` plus `players.json` | https://claude.ai/artifact/5TKxjHSPT4Zqb2tgQVYKEj (personal) |
| `build_league.py` | `bt-2026-season-review.html` from `players.json` + `league_rows.json` (and the CSS of the first page, so build that first) | https://claude.ai/artifact/6HawM6b1fjtZGYL3KzikMU (league, "BT 2026 Season Analysis") |

`players.json` is the 144 drafted players with projection, actual and stat line (derived from `data/backtests/2026/actuals.json`); `league_rows.json` is the per-team table. Run both scripts from this folder, then republish the HTML with the Artifact tool using the URL above to keep the link.
