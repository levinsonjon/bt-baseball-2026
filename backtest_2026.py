"""
backtest_2026.py — Score the 2026 draft board with and without the playing-time
model and compare both to what actually happened.

Fixture: data/backtests/2026/{projections_cache.json (draft-day projections),
actuals.json (144 drafted players, full-season BT points + stat lines),
team_results.json (official per-team totals)}. History for the model comes from
data/history/ restricted to seasons before 2026.

    python3 backtest_2026.py            # summary
    python3 backtest_2026.py --show 20  # also list the 20 largest factor effects
"""
from __future__ import annotations
import argparse, json, statistics as st, unicodedata
from datetime import date
from pathlib import Path

import config
from players import Player
from playing_time import History, playing_time_factor, apply_to_stats

FIX = Path(__file__).parent / "data" / "backtests" / "2026"
SEASON = 2026
DRAFT_DAY = date(2026, 3, 30)


def norm(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower().replace(".", "").strip()


def corr(x, y):
    mx, my = st.mean(x), st.mean(y)
    sx = sum((a - mx) ** 2 for a in x) ** .5
    sy = sum((b - my) ** 2 for b in y) ** .5
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy) if sx and sy else 0.0


def score(name, team, positions, ptype, stats):
    return Player(name=name, team=team, positions=positions, player_type=ptype,
                  projected_stats=stats).projected_points


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=0)
    args = ap.parse_args()

    cache = {(norm(p["name"]), p["player_type"]): p for p in json.load(open(FIX / "projections_cache.json"))}
    actuals = json.load(open(FIX / "actuals.json"))
    teams = {t["team"]: t for t in json.load(open(FIX / "team_results.json"))}
    h = History.load()

    rows = []
    for a in actuals:
        c = cache.get((norm(a["n"]), a["t"]))
        if not c:
            continue
        raw = score(c["name"], c["team"], c["positions"], c["player_type"], c["projected_stats"])
        pt = playing_time_factor(h, c["name"], c["player_type"], c["positions"], SEASON, DRAFT_DAY, c["projected_stats"])
        adj = score(c["name"], c["team"], c["positions"], c["player_type"],
                    apply_to_stats(c["projected_stats"], c["player_type"], pt["factor"]))
        rows.append(dict(name=c["name"], owner=a["o"], t=a["t"], raw=raw, adj=adj, act=a["ac"], pt=pt))

    print(f"2026 backtest: {len(rows)} drafted players, history through {SEASON - 1}, MLERA {config.MLB_AVG_ERA}\n")
    print(f"{'type':7s} {'n':>3s} {'bias raw':>9s} {'bias adj':>9s} {'MAE raw':>8s} {'MAE adj':>8s} {'corr raw':>9s} {'corr adj':>9s}")
    for t in ("hitter", "sp", "rp"):
        r = [x for x in rows if x["t"] == t]
        raw, adj, act = [x["raw"] for x in r], [x["adj"] for x in r], [x["act"] for x in r]
        print(f"{t:7s} {len(r):3d} {st.mean(act) - st.mean(raw):+9.1f} {st.mean(act) - st.mean(adj):+9.1f} "
              f"{st.mean(abs(a - b) for a, b in zip(raw, act)):8.1f} {st.mean(abs(a - b) for a, b in zip(adj, act)):8.1f} "
              f"{corr(raw, act):9.3f} {corr(adj, act):9.3f}")

    # team totals: hitters + top-3 SP + RP, raw vs adjusted vs the drafted 16 on
    # full-season actuals (no swaps) — the fair test of a draft-day model.
    print(f"\n{'team':11s} {'drafted16':>9s} {'raw proj':>9s} {'adj proj':>9s} {'raw miss':>9s} {'adj miss':>9s}")
    tot_raw, tot_adj, offs = [], [], []
    for o, t in sorted(teams.items(), key=lambda kv: -kv[1]["noswap"]):
        mine = [x for x in rows if x["owner"] == o]
        def team_total(key):
            hit = sum(x[key] for x in mine if x["t"] == "hitter")
            rp = sum(x[key] for x in mine if x["t"] == "rp")
            sp = sum(sorted([x[key] for x in mine if x["t"] == "sp"], reverse=True)[:3])
            return hit + sp + rp
        r, a = team_total("raw"), team_total("adj")
        tot_raw.append(r); tot_adj.append(a); offs.append(t["noswap"])
        print(f"{o:11s} {t['noswap']:9d} {r:9.0f} {a:9.0f} {t['noswap'] - r:+9.0f} {t['noswap'] - a:+9.0f}")
    print(f"team-total corr with drafted16: raw {corr(tot_raw, offs):.3f}  adj {corr(tot_adj, offs):.3f}")
    print(f"team-total mean abs miss:      raw {st.mean(abs(a - b) for a, b in zip(tot_raw, offs)):.0f}  adj {st.mean(abs(a - b) for a, b in zip(tot_adj, offs)):.0f}")

    if args.show:
        print(f"\nLargest playing-time adjustments:")
        for x in sorted(rows, key=lambda x: x["adj"] - x["raw"])[:args.show]:
            p = x["pt"]
            print(f"  {x['name']:22s} {x['t']:6s} raw {x['raw']:6.0f} adj {x['adj']:6.0f} act {x['act']:6.0f}  factor {p['factor']:.2f} "
                  f"(hist {p['hist_frac']}, age {p['age']}, IL {p['il']}) {p['detail']}")
        print(f"\nBiggest remaining misses after adjustment:")
        for x in sorted(rows, key=lambda x: abs(x["act"] - x["adj"]), reverse=True)[:args.show]:
            p = x["pt"]
            print(f"  {x['name']:22s} {x['t']:6s} adj {x['adj']:6.0f} act {x['act']:6.0f} miss {x['act'] - x['adj']:+6.0f}  factor {p['factor']:.2f}")


if __name__ == "__main__":
    main()
