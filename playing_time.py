"""
playing_time.py — Expected playing time for projections (2027 workstream 1).

The 2026 retrospective found the projections assumed a full season for everyone:
drafted hitters were over-projected by ~42 BT points each, almost entirely lost
playing time (Stanton, Rooker, Judge, Raleigh, Lindor...). This module turns a
player's history into an expected fraction of the projected playing time and the
projections scale their counting stats by it. Rates (AVG, ERA) are untouched.

Deliberately a transparent discount table, not a fitted model. Every factor is a
named constant below so the backtest (backtest_2026.py) can show what each one
buys. Inputs come from data/history/ (built by build_history.py from the MLB
Stats API): games played per season, IL placements, birthdates.

    factor = clamp(AVAIL_WEIGHT * hist_frac + (1 - AVAIL_WEIGHT) * 1.0, ...)
             * age_multiplier * il_multiplier
    expected_AB = projected_AB * min(1, factor)          (hitters)
    expected_IP = projected_IP * min(1, factor)          (starters)
    expected_G  = projected_G  * min(1, factor)          (relievers)

hist_frac = recency-weighted mean over the prior three seasons of
    min(1, delivered playing time / the projection's own playing time)
i.e. AB vs projected AB for hitters, IP vs projected IP for starters, G vs
projected G for relievers. Measuring against the projection (not a generic
full season) matters: pitcher projections already assume realistic innings,
and discounting them twice was the first backtest's main error. A debut
season counts no lower than PARTIAL_HISTORY_FLOOR (a call-up is not an
availability record). Rookies with no MLB history get ROOKIE_FRAC.
"""
from __future__ import annotations
import json
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

HISTORY_DIR = Path(__file__).parent / "data" / "history"

# ---------------------------------------------------------------------------
# Tunables (backtested on 2026 — see backtest_2026.py)
# ---------------------------------------------------------------------------

# Fallback denominators when a projection carries no playing-time figure.
FULL_SEASON = {"hitter_AB": 560.0, "C_AB": 470.0, "sp_IP": 175.0, "rp_G": 62.0}
RECENCY_WEIGHTS = (0.5, 0.3, 0.2)      # most recent season first
# Per-type weights, chosen on the 2026 backtest (backtest_2026.py). Pitcher
# projections already price durability into projected IP, so starters take no
# continuous history discount, only a small IL/red-flag one; hitters and
# relievers do not, so their history counts.
AVAIL_WEIGHT = {"hitter": 0.75, "sp": 0.0, "rp": 1.0}   # weight on history vs. regression to the projection
ROOKIE_FRAC = 0.85                      # no MLB history (prospects, NPB/KBO arrivals)
PARTIAL_HISTORY_FLOOR = 0.70            # a debut season counts no lower than this
SP_RED_FLAG = 0.60                      # a starter whose history is below this fraction of projected IP...
SP_RED_FLAG_RATE = 0.5                  # ...loses this share of the shortfall
AGE_KNEE = {"hitter": 32, "sp": 33, "rp": 34}
AGE_RATE = {"hitter": 0.035, "sp": 0.0, "rp": 0.0}     # per year past the knee
AGE_FLOOR = 0.75
IL_RATE = {"hitter": 0.06, "sp": 0.02, "rp": 0.02}     # per IL placement in the prior two seasons
IL_CAP = 0.20
FACTOR_FLOOR = 0.40


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower().replace(".", "").strip()


@dataclass
class History:
    """Loaded once; keyed by normalized full name (and MLB id where known)."""
    games: dict          # (season, group) -> {norm name: {"G","GS","AB","IP","id"}}
    il: dict             # norm name -> {season: count}
    birth: dict          # norm name -> date
    debut: dict          # norm name -> debut year

    @classmethod
    def load(cls, history_dir: Path = HISTORY_DIR) -> "History":
        g = json.loads((history_dir / "games.json").read_text())
        games = {}
        for key, rows in g.items():
            season, group = key.split("_")
            games[(int(season), group)] = {_norm(r["name"]): r for r in rows}
        il = {}
        for r in json.loads((history_dir / "il_placements.json").read_text()):
            il.setdefault(_norm(r["name"]), {}).setdefault(r["year"], 0)
            il[_norm(r["name"])][r["year"]] += 1
        birth, debut = {}, {}
        for r in json.loads((history_dir / "birthdates.json").read_text()).values():
            if r.get("birthDate"):
                birth[_norm(r["name"])] = date.fromisoformat(r["birthDate"])
            if r.get("mlbDebutDate"):
                debut[_norm(r["name"])] = int(r["mlbDebutDate"][:4])
        return cls(games, il, birth, debut)


def _ip_float(s) -> float:
    if s in (None, ""):
        return 0.0
    w, _, f = str(s).partition(".")
    return int(w) + int(f or 0) / 3


def _projected_pt(stats: dict, ptype: str, positions: list[str]) -> float:
    """The playing-time figure the projection itself assumes."""
    if ptype == "hitter":
        return stats.get("AB") or (FULL_SEASON["C_AB"] if "C" in positions else FULL_SEASON["hitter_AB"])
    if ptype == "sp":
        return stats.get("IP") or FULL_SEASON["sp_IP"]
    return stats.get("G") or FULL_SEASON["rp_G"]


def hist_fraction(h: History, name: str, ptype: str, positions: list[str], season: int,
                  projected_stats: dict | None = None) -> tuple[float | None, list]:
    """Recency-weighted fraction of the projected playing time the player has
    actually delivered over the three prior seasons.
    Returns (fraction or None if no history, per-season detail)."""
    n = _norm(name)
    group = "hitting" if ptype == "hitter" else "pitching"
    denom = _projected_pt(projected_stats or {}, ptype, positions)
    detail, fracs, weights = [], [], []
    debut_year = h.debut.get(n)
    for w, back in zip(RECENCY_WEIGHTS, (1, 2, 3)):
        yr = season - back
        row = h.games.get((yr, group), {}).get(n)
        if not row:
            detail.append((yr, None))
            continue
        if debut_year is not None and yr < debut_year:
            detail.append((yr, None))
            continue
        if ptype == "sp":
            delivered = _ip_float(row.get("IP"))
        elif ptype == "hitter":
            delivered = row.get("AB") or 0
        else:
            delivered = row.get("G") or 0
        frac = min(delivered / denom, 1.0) if denom else 1.0
        # A debut season is a call-up, not an availability record: floor it.
        if debut_year is not None and yr == debut_year:
            frac = max(frac, PARTIAL_HISTORY_FLOOR)
        detail.append((yr, round(frac, 2)))
        fracs.append(frac)
        weights.append(w)
    if not fracs:
        return None, detail
    frac = sum(f * w for f, w in zip(fracs, weights)) / sum(weights)
    if len(fracs) == 1:
        frac = max(frac, PARTIAL_HISTORY_FLOOR)
    return frac, detail


def age_on(h: History, name: str, as_of: date) -> float | None:
    b = h.birth.get(_norm(name))
    if not b:
        return None
    return (as_of - b).days / 365.25


def il_count(h: History, name: str, season: int) -> int:
    d = h.il.get(_norm(name), {})
    return d.get(season - 1, 0) + d.get(season - 2, 0)


def playing_time_factor(h: History, name: str, ptype: str, positions: list[str],
                        season: int, as_of: date | None = None,
                        projected_stats: dict | None = None) -> dict:
    """Return {"factor", "hist_frac", "age", "age_mult", "il", "il_mult", "detail"}."""
    as_of = as_of or date(season, 3, 30)
    hf, detail = hist_fraction(h, name, ptype, positions, season, projected_stats)
    aw = AVAIL_WEIGHT[ptype]
    base = ROOKIE_FRAC if hf is None else aw * hf + (1 - aw) * 1.0
    if ptype == "sp" and hf is not None and hf < SP_RED_FLAG:
        # Continuous history scaling hurts starters (their projected IP already
        # prices durability), but a starter who has not come close to his
        # projected innings lately is a real red flag.
        base *= 1 - SP_RED_FLAG_RATE * (SP_RED_FLAG - hf) / SP_RED_FLAG
    age = age_on(h, name, as_of)
    knee, rate = AGE_KNEE[ptype], AGE_RATE[ptype]
    age_mult = 1.0 if age is None or age <= knee else max(AGE_FLOOR, 1 - rate * (age - knee))
    il = il_count(h, name, season)
    il_mult = 1 - min(IL_CAP, IL_RATE[ptype] * il)
    factor = max(FACTOR_FLOOR, min(1.0, base * age_mult * il_mult))
    return {"factor": round(factor, 3), "hist_frac": None if hf is None else round(hf, 3),
            "age": None if age is None else round(age, 1), "age_mult": round(age_mult, 3),
            "il": il, "il_mult": round(il_mult, 3), "detail": detail}


def risk_profile(pt: dict) -> dict:
    """A visible risk read for the draft board (2027 workstream 2).

    Backtested on 2026: subtracting a risk penalty from the projection did not
    improve the top of the board (at most 2 of the 7 biggest busts left the
    top 20, and none of the breakouts entered it), so risk is *shown*, never
    used to re-rank. sd = spread of the prior seasons' playing-time fractions.
    """
    fr = [f for _, f in pt.get("detail", []) if f is not None]
    if len(fr) >= 2:
        m = sum(fr) / len(fr)
        sd = (sum((f - m) ** 2 for f in fr) / len(fr)) ** 0.5
    else:
        sd = 0.25   # rookie / one season: unknown is risky
    il = pt.get("il", 0)
    age = pt.get("age")
    score = min(1.0, 0.5 * sd / 0.25 * 0.5 + 0.15 * il + (0.05 * max(0.0, (age or 30) - 32)))
    flags = []
    if sd >= 0.2:
        flags.append("uneven seasons")
    if il >= 2:
        flags.append(f"{il} IL stints")
    if age is not None and age >= 33:
        flags.append(f"age {age:.0f}")
    if pt.get("hist_frac") is None:
        flags.append("no MLB history")
    tier = "high" if score >= 0.5 else "medium" if score >= 0.25 else "low"
    return {"risk_sd": round(sd, 3), "risk_score": round(score, 2), "risk_tier": tier, "risk_note": ", ".join(flags)}


def apply_to_stats(stats: dict, ptype: str, factor: float) -> dict:
    """Scale playing-time-dependent stats by `factor`; leave rates alone."""
    out = dict(stats)
    f = min(1.0, factor)
    if ptype == "hitter":
        for k in ("AB", "PA", "H", "HR", "RBI", "R", "SB", "BB", "HBP"):
            if k in out and out[k] is not None:
                out[k] = round(out[k] * f, 1)
    elif ptype == "sp":
        for k in ("IP", "G", "GS", "W"):
            if k in out and out[k] is not None:
                out[k] = round(out[k] * f, 1)
    else:
        for k in ("IP", "G", "W", "SV"):
            if k in out and out[k] is not None:
                out[k] = round(out[k] * f, 1)
    return out


if __name__ == "__main__":
    import sys
    h = History.load()
    season = int(sys.argv[1]) if len(sys.argv) > 1 else 2027
    for name, ptype, pos in [("Aaron Judge", "hitter", ["OF"]), ("Giancarlo Stanton", "hitter", ["OF"]),
                             ("Pete Crow-Armstrong", "hitter", ["OF"]), ("Cal Raleigh", "hitter", ["C"]),
                             ("Zack Wheeler", "sp", ["SP"]), ("Cole Ragans", "sp", ["SP"]), ("Devin Williams", "rp", ["RP"])]:
        print(f"{name:22s} {playing_time_factor(h, name, ptype, pos, season)}")
