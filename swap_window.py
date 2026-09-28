#!/usr/bin/env python3
"""
swap_window.py — Roster-wide substitution analysis for the BT Baseball Pool.

Reproduces the 2026-07-13 "replace anyone" analysis as a repeatable command:
for every slot on Jon's roster, the expected rest-of-season (ROS) BT points of
the incumbent versus every eligible free agent, ranked by the change in the
slot's season-final score.

    python3 swap_window.py --as-of 2026-07-13 --bbsubs "~/Downloads/BBSUBS (2).xls"
    python3 swap_window.py --as-of 2026-08-01 --bbsubs "~/Downloads/BBSUBS (3).xls" --slot C --top 8

Inputs
  * Draft board          data/draft_board_2026.py (transcribed tracker; paired SPs, DH round)
  * Substitution log     the commissioner's BBSUBS .xls (Drop/Add row pairs under
                         "Effective M/D" headers) — needs xlrd==1.2.0
  * Projections          data/projections_cache.json (beginning-of-season rates)
  * MLB Stats API        stats=byDateRange for YTD (opening day .. as-of-1) and
                         the last 30 days; cached under data/.swap_cache/
  * Slot carryover       data/season_stats.json as committed on/before the as-of
                         date (git history), falling back to the incumbent's YTD

Method (see roster-swap-analysis-2026-07-13 memory)
  * Rates: YTD regressed toward the projection, weight AB/(AB+275) for hitters
    and IP/(IP+80) for pitchers.
  * Playing time: per-team-game usage = 0.65 x last-30-day rate + 0.35 x projected
    rate; fewer than 15 AB (8 IP) in the last 30 days flags the player inactive
    and halves his ROS playing time.
  * Hitters: slot-final BT = round(AVG x 1000) + HR + RBI + R + SB on the slot's
    carryover plus ROS, with the 300 AB floor. Delta is measured on the slot
    total because AVG x 1000 is non-linear in the carryover.
  * SP: RSAR = (1.2 x MLERA - ERA) x IP/9 per slot; team score = 3.5 x best three
    of six. Delta is the change in the team's best-three sum after the swap.
  * RP: 5 x (W + SV); last-30-day saves carry the closer-role signal.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
import unicodedata
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "data"))
import config  # noqa: E402
from draft_board_2026 import OWNERS, parse as parse_board  # noqa: E402

CACHE_DIR = REPO / "data" / ".swap_cache"
OPENING_DAY = date(2026, 3, 26)
SEASON_END = date(2026, 9, 27)
GAMES = 162
HITTER_REGRESS = 275.0
PITCHER_REGRESS = 80.0
RECENT_WEIGHT = 0.65
INACTIVE_AB = 15
INACTIVE_IP = 8.0
INACTIVE_HAIRCUT = 0.5
RETURN_HAIRCUT = 0.9      # --hold: an injured player back from the IL plays this share of his projected rate
MY_TEAM = config.JON_TEAM_NAME

FIRST_ALIASES = {"wm": "william", "jh": "jhoan", "ja": "jarren", "ra": "ranger", "cj": "cj"}
SURNAME_FIXES = {"woodrfuff": "woodruff", "schmidtt": "schmitt", "ledich": "leidich"}
OWNER_ALIASES = {"ashton": "Palma", "ledich": "Tchir", "leidich": "Tchir", "feinman": "Lerner"}
SUFFIXES = {"jr", "jr.", "sr", "ii", "iii", "iv"}
HITTER_SLOTS = {"C", "1B", "2B", "3B", "SS", "OF", "DH"}


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def name_parts(full: str) -> tuple[str, str]:
    toks = [t for t in norm(full).split() if t not in SUFFIXES]
    if not toks:
        return "", ""
    return toks[0], toks[-1]


# ---------------------------------------------------------------------------
# MLB Stats API (cached)
# ---------------------------------------------------------------------------

def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=90) as r:
        return json.load(r)


def ip_float(s) -> float:
    w, _, f = str(s).partition(".")
    return int(w or 0) + int(f or 0) / 3.0


def date_range_stats(group: str, start: date, end: date) -> list[dict]:
    """All players' totals for [start, end] from stats=byDateRange (cached)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f = CACHE_DIR / f"{group}_{start}_{end}.json"
    if f.exists():
        return json.loads(f.read_text())
    url = ("https://statsapi.mlb.com/api/v1/stats?stats=byDateRange&group={g}&season={y}"
           "&sportIds=1&startDate={s}&endDate={e}&limit=4000&playerPool=ALL&gameType=R"
           ).format(g=group, y=start.year, s=start, e=end)
    raw = _get(url)
    splits = raw["stats"][0]["splits"] if raw.get("stats") else []
    rows = []
    for sp in splits:
        st = sp["stat"]
        row = {"id": sp["player"]["id"], "name": sp["player"]["fullName"],
               "team": (sp.get("team") or {}).get("abbreviation", ""),
               "G": st.get("gamesPlayed", 0)}
        if group == "hitting":
            row.update(AB=st.get("atBats", 0), H=st.get("hits", 0), HR=st.get("homeRuns", 0),
                       RBI=st.get("rbi", 0), R=st.get("runs", 0), SB=st.get("stolenBases", 0))
        else:
            row.update(IP=ip_float(st.get("inningsPitched", "0")), ER=st.get("earnedRuns", 0),
                       GS=st.get("gamesStarted", 0), W=st.get("wins", 0), SV=st.get("saves", 0),
                       K=st.get("strikeOuts", 0))
        rows.append(row)
    f.write_text(json.dumps(rows))
    return rows


# ---------------------------------------------------------------------------
# Player universe: projections + MLB rows, keyed by (norm name, type)
# ---------------------------------------------------------------------------

class Universe:
    def __init__(self, as_of: date):
        self.as_of = as_of
        self.proj = {}          # (nname, ptype) -> projection dict
        by_name = {}
        for p in json.loads((REPO / "data" / "projections_cache.json").read_text()):
            self.proj[(norm(p["name"]), p["player_type"])] = p
            by_name.setdefault(norm(p["name"]), []).append(p)
        ytd_end = as_of - timedelta(days=1)
        rec_start = as_of - timedelta(days=30)
        self.ytd_h = {r["id"]: r for r in date_range_stats("hitting", OPENING_DAY, ytd_end)}
        self.ytd_p = {r["id"]: r for r in date_range_stats("pitching", OPENING_DAY, ytd_end)}
        self.rec_h = {r["id"]: r for r in date_range_stats("hitting", rec_start, ytd_end)}
        self.rec_p = {r["id"]: r for r in date_range_stats("pitching", rec_start, ytd_end)}
        # canonical player records
        self.players = {}       # (nname, ptype) -> record
        for r in self.ytd_h.values():
            self._add(r, "hitter")
        for r in self.ytd_p.values():
            t = "rp" if (r["G"] > 0 and r["GS"] / max(r["G"], 1) < 0.5 and r["IP"] / max(r["G"], 1) < 3.5) else "sp"
            self._add(r, t)
            # a pitcher may be projected under the other role; register that key too
            other = "sp" if t == "rp" else "rp"
            if (norm(r["name"]), other) in self.proj and (norm(r["name"]), other) not in self.players:
                self._add(r, other)
        # projected-only players with no 2026 MLB line (still draftable / rosterable)
        for (n, t), p in self.proj.items():
            if (n, t) not in self.players:
                self.players[(n, t)] = {"name": p["name"], "nname": n, "ptype": t, "team": p["team"],
                                        "id": None, "positions": p["positions"]}
        for key, rec in self.players.items():
            p = self.proj.get(key)
            if not rec.get("team") and p:
                rec["team"] = p.get("team", "")
            rec["proj"] = p["projected_stats"] if p else None
            rec["proj_pts"] = p["projected_points"] if p else 0.0
            if p and not rec.get("positions"):
                rec["positions"] = p["positions"]
            rec.setdefault("positions", ["DH"] if key[1] == "hitter" else [key[1].upper()])
        self.by_surname = {}
        for key, rec in self.players.items():
            first, last = name_parts(rec["name"])
            self.by_surname.setdefault(last, []).append(rec)

    def _add(self, r: dict, ptype: str):
        key = (norm(r["name"]), ptype)
        if key in self.players:
            return
        rec = {"name": r["name"], "nname": key[0], "ptype": ptype, "team": r["team"], "id": r["id"]}
        p = self.proj.get(key)
        rec["positions"] = list(p["positions"]) if p else []
        self.players[key] = rec

    # --- stats access
    def ytd(self, rec):
        if rec["id"] is None:
            return None
        return (self.ytd_h if rec["ptype"] == "hitter" else self.ytd_p).get(rec["id"])

    def recent(self, rec):
        if rec["id"] is None:
            return None
        return (self.rec_h if rec["ptype"] == "hitter" else self.rec_p).get(rec["id"])

    # --- resolution of league shorthand ("J Walker", "Muncy (LAD)", "Wm Contreras")
    def resolve(self, label: str, ptype_hint: str, team_hint: str = "", pool=None, log=None):
        """ptype_hint: 'hitter' | 'pitcher' (sp or rp) | 'rp' | 'sp'."""
        raw = label.strip()
        m = re.search(r"\(([A-Z]{2,3})\)", raw)
        if m and m.group(1) not in ("SP", "RP", "OF", "SS", "DH", "1B", "2B", "3B", "C"):
            team_hint = m.group(1)
        raw = re.sub(r"\(.*?\)", "", raw).strip()
        toks = [t for t in norm(raw).split() if t not in SUFFIXES]
        if not toks:
            return None
        last = SURNAME_FIXES.get(toks[-1], toks[-1])
        first = toks[0] if len(toks) > 1 else ""
        first = FIRST_ALIASES.get(first, first)
        types = {"hitter": {"hitter"}, "pitcher": {"sp", "rp"}, "sp": {"sp", "rp"}, "rp": {"rp", "sp"}}[ptype_hint]
        cands = [r for r in (pool if pool is not None else self.by_surname.get(last, [])) if r["ptype"] in types]
        if pool is not None:
            cands = [r for r in cands if name_parts(r["name"])[1] == last]
        if not cands and pool is None:
            close = difflib.get_close_matches(last, list(self.by_surname), n=1, cutoff=0.85)
            if close:
                cands = [r for r in self.by_surname[close[0]] if r["ptype"] in types]
        if first:
            fc = [r for r in cands if name_parts(r["name"])[0].startswith(first) or first.startswith(name_parts(r["name"])[0])]
            if fc:
                cands = fc
        if len(cands) > 1 and team_hint:
            tc = [r for r in cands if r["team"] == team_hint]
            if tc:
                cands = tc
        if len(cands) > 1 and ptype_hint in ("sp", "rp"):
            tc = [r for r in cands if r["ptype"] == ptype_hint]
            if tc:
                cands = tc
        if len(cands) > 1:
            # prefer the one who has actually played this year, then the most-used
            def usage(r):
                y = self.ytd(r) or {}
                return (y.get("AB", 0) or 0) + 10 * (y.get("IP", 0) or 0)
            cands.sort(key=usage, reverse=True)
            if log is not None:
                log.append(f"ambiguous '{label}' -> {cands[0]['name']} ({cands[0]['team']}); "
                           f"others: {', '.join(c['name'] + ' ' + c['team'] for c in cands[1:4])}")
        if not cands:
            if log is not None:
                log.append(f"UNRESOLVED '{label}' ({ptype_hint})")
            return None
        return cands[0]


# ---------------------------------------------------------------------------
# League rosters: draft board + BBSUBS through the as-of date
# ---------------------------------------------------------------------------

def owner_from_label(label: str):
    toks = [t.strip() for t in re.split(r"[/ ]+", label.strip()) if t.strip()]
    for t in toks:
        if t in OWNERS:
            return t
        if t.lower() in OWNER_ALIASES:
            return OWNER_ALIASES[t.lower()]
    return None


def parse_bbsubs(path: Path, as_of: date) -> list[dict]:
    """Yield {effective, owner, ptype_hint, drop, add} for changes effective <= as_of."""
    import xlrd
    ws = xlrd.open_workbook(str(path)).sheet_by_index(0)
    changes, eff, owner, hint, year = [], None, None, "hitter", as_of.year
    pending_drop = None
    for r in range(ws.nrows):
        c0 = str(ws.cell_value(r, 0)).strip()
        c1 = str(ws.cell_value(r, 1)).strip()
        c2 = str(ws.cell_value(r, 2)).strip()
        m = re.search(r"Effective\s+(\d{1,2})/(\d{1,2})", c0)
        if m:
            eff = date(year, int(m.group(1)), int(m.group(2)))
            continue
        if c0 and c0 not in ("Drop", "Add") and c2 in ("AB", "G", "W"):
            owner = owner_from_label(c0)
            hint = {"AB": "hitter", "G": "sp", "W": "rp"}[c2]
            continue
        if c0 == "Drop":
            pending_drop = c1
        elif c0 == "Add" and pending_drop is not None:
            if eff is not None and eff <= as_of and owner:
                changes.append({"effective": eff, "owner": owner, "hint": hint, "drop": pending_drop, "add": c1})
            pending_drop = None
    return changes


def load_draft_picks() -> list[dict]:
    """The draft board as pick dicts {owner, pos, full, pick, pair, ptype}.

    2026: the transcription in data/draft_board_2026.py.
    2027 TODO: read the live tracker instead — Google Sheet config.DRAFT_TRACKER_SHEET_ID,
    tab config.DRAFT_TRACKER_TAB, header row config.TRACKER_HEADER_ROW (owners in B..J,
    positions in column A, cells like "Witt 3"). Reuse draft.parse_tracker_response()
    for the grid, then apply the paired-SP / DH-round pick rules from draft_board_2026
    and resolve abbreviations through Universe.resolve(). Swap this function's body;
    nothing downstream depends on the source.
    """
    return parse_board()


def build_rosters(uni: Universe, bbsubs: Path | None, as_of: date, log: list) -> dict:
    """owner -> list of slot dicts {slot, player(record)}; slot in C,1B,2B,3B,SS,OF,DH,RP,SP."""
    rosters = {o: [] for o in OWNERS}
    for pk in load_draft_picks():
        rec = uni.players.get((norm(pk["full"]), pk["ptype"]))
        if rec is None:
            rec = uni.resolve(pk["full"], "hitter" if pk["ptype"] == "hitter" else pk["ptype"], log=log)
        slot = "OF" if pk["pos"].startswith("OF") else ("SP" if pk["pos"].startswith("SP") else pk["pos"])
        rosters[pk["owner"]].append({"slot": slot, "player": rec, "since": OPENING_DAY})
    if bbsubs is None:
        return rosters
    for ch in parse_bbsubs(bbsubs, as_of):
        roster = rosters[ch["owner"]]
        hint = ch["hint"]
        # drop label may be a chain "Raleigh/Jeffers (Catcher)": the current player is the last part
        drop_label = re.sub(r"\(.*?\)", "", ch["drop"]).strip()
        parts = [p.strip() for p in drop_label.split("/") if p.strip()]
        pool = [s["player"] for s in roster if s["player"] is not None]
        dropped = None
        for part in reversed(parts):
            dropped = uni.resolve(part, hint, pool=pool, log=log)
            if dropped:
                break
        added = uni.resolve(ch["add"], hint, log=log)
        if dropped is None or added is None:
            log.append(f"SKIPPED change {ch['effective']} {ch['owner']}: drop '{ch['drop']}' add '{ch['add']}'")
            continue
        for s in roster:
            if s["player"] is dropped:
                s["player"] = added
                s["since"] = ch["effective"]
                break
        else:
            log.append(f"drop target not on roster: {ch['owner']} '{ch['drop']}' -> {dropped['name']}")
    return rosters


# ---------------------------------------------------------------------------
# Rest-of-season projection
# ---------------------------------------------------------------------------

def remaining_games(as_of: date, season_end: date) -> float:
    total = (season_end - OPENING_DAY).days + 1
    left = max(0, (season_end - as_of).days + 1)
    return GAMES * left / total


def games_in_window(as_of: date) -> float:
    return GAMES * 30 / ((SEASON_END - OPENING_DAY).days + 1)


def blend(w, ytd_rate, proj_rate):
    return w * ytd_rate + (1 - w) * proj_rate


def games_elapsed(as_of: date) -> float:
    total = (SEASON_END - OPENING_DAY).days + 1
    return max(1.0, GAMES * (as_of - OPENING_DAY).days / total)


# Fallback rates for players with no beginning-of-season projection (rookies,
# call-ups): regress toward a league-average line rather than toward nothing.
LEAGUE_AVG_HITTER = {"AVG": 0.245, "HR": 0.030, "RBI": 0.115, "R": 0.120, "SB": 0.016}


def hitter_ros(uni: Universe, rec: dict, games_left: float, projected_pt: bool = False) -> dict | None:
    """ROS AB/H/HR/RBI/R/SB for one hitter, plus usage flags.
    projected_pt=True ignores recent usage (a player on the IL has none) and
    plays him at RETURN_HAIRCUT × his projected per-game rate — the hold case."""
    proj = rec.get("proj") or {}
    y = uni.ytd(rec) or {"AB": 0, "H": 0, "HR": 0, "RBI": 0, "R": 0, "SB": 0, "G": 0}
    r30 = uni.recent(rec) or {"AB": 0, "H": 0, "HR": 0, "RBI": 0, "R": 0, "SB": 0, "G": 0}
    pab = proj.get("AB", 0) or 0
    if pab <= 0 and y["AB"] <= 0:
        return None
    # per-AB rates: projection vs YTD, regressed
    w = y["AB"] / (y["AB"] + HITTER_REGRESS)
    def rate(k):
        pr = (proj.get(k, 0) / pab) if pab else LEAGUE_AVG_HITTER[k]
        yr = (y[k] / y["AB"]) if y["AB"] else pr
        return blend(w, yr, pr)
    proj_avg = (proj.get("AVG") or ((proj.get("H", 0) / pab) if pab else 0)) if pab else LEAGUE_AVG_HITTER["AVG"]
    avg = blend(w, (y["H"] / y["AB"]) if y["AB"] else proj_avg, proj_avg)
    # playing time per team game (no projection: this season's AB per team game so far)
    proj_abpg = pab / GAMES if pab else y["AB"] / games_elapsed(uni.as_of)
    recent_abpg = r30["AB"] / games_in_window(uni.as_of)
    if projected_pt:
        abpg = proj_abpg * RETURN_HAIRCUT
        inactive = False
    else:
        abpg = RECENT_WEIGHT * recent_abpg + (1 - RECENT_WEIGHT) * proj_abpg
        inactive = r30["AB"] < INACTIVE_AB
        if inactive:
            abpg *= INACTIVE_HAIRCUT
    ros_ab = abpg * games_left
    out = {"AB": ros_ab, "H": ros_ab * avg, "HR": ros_ab * rate("HR"), "RBI": ros_ab * rate("RBI"),
           "R": ros_ab * rate("R"), "SB": ros_ab * rate("SB"), "inactive": inactive,
           "ytd": y, "r30": r30, "avg": avg}
    return out


def hitter_bt(carry: dict, ros: dict) -> float:
    ab = carry.get("AB", 0) + ros["AB"]
    h = carry.get("H", 0) + ros["H"]
    avg = h / max(ab, config.HITTER_MIN_AB) if ab > 0 else 0.0
    return round(avg * 1000) + sum(carry.get(k, 0) + ros[k] for k in ("HR", "RBI", "R", "SB"))


def pitcher_ros(uni: Universe, rec: dict, games_left: float, role: str, projected_pt: bool = False) -> dict | None:
    proj = rec.get("proj") or {}
    y = uni.ytd(rec) or {"IP": 0.0, "ER": 0, "G": 0, "GS": 0, "W": 0, "SV": 0}
    r30 = uni.recent(rec) or {"IP": 0.0, "ER": 0, "G": 0, "GS": 0, "W": 0, "SV": 0}
    pip = proj.get("IP", 0) or 0
    if pip <= 0 and y["IP"] <= 0:
        return None
    w = y["IP"] / (y["IP"] + PITCHER_REGRESS)
    proj_era = proj.get("ERA") if proj.get("ERA") is not None else config.MLB_AVG_ERA
    ytd_era = (y["ER"] * 9 / y["IP"]) if y["IP"] else proj_era
    era = blend(w, ytd_era, proj_era)
    proj_ippg = pip / GAMES if pip else y["IP"] / games_elapsed(uni.as_of)
    recent_ippg = r30["IP"] / games_in_window(uni.as_of)
    if projected_pt:
        ippg = proj_ippg * RETURN_HAIRCUT
        inactive = False
    else:
        ippg = RECENT_WEIGHT * recent_ippg + (1 - RECENT_WEIGHT) * proj_ippg
        inactive = r30["IP"] < INACTIVE_IP
        if inactive:
            ippg *= INACTIVE_HAIRCUT
    ros_ip = ippg * games_left
    # appearances: recent rate blended with projection
    pg = proj.get("G", 0) or 0
    proj_gpg = pg / GAMES if pg else y["G"] / games_elapsed(uni.as_of)
    recent_gpg = r30["G"] / games_in_window(uni.as_of)
    gpg = (proj_gpg * RETURN_HAIRCUT) if projected_pt else (RECENT_WEIGHT * recent_gpg + (1 - RECENT_WEIGHT) * proj_gpg)
    ros_g = gpg * games_left * (INACTIVE_HAIRCUT if inactive else 1.0)
    out = {"IP": ros_ip, "ER": era * ros_ip / 9, "G": ros_g, "era": era, "inactive": inactive, "ytd": y, "r30": r30}
    if role == "rp":
        # W+SV per team game: recent is the closer-role signal
        pw = (proj.get("W", 0) or 0) + (proj.get("SV", 0) or 0)
        proj_rate = pw / GAMES
        recent_rate = (r30["W"] + r30["SV"]) / games_in_window(uni.as_of)
        ytd_rate = (y["W"] + y["SV"]) / max(games_in_window(uni.as_of) * ((uni.as_of - OPENING_DAY).days / 30.0), 1)
        if projected_pt:
            rate = (0.5 * proj_rate + 0.5 * ytd_rate) * RETURN_HAIRCUT
        else:
            rate = RECENT_WEIGHT * recent_rate + (1 - RECENT_WEIGHT) * (0.5 * proj_rate + 0.5 * ytd_rate)
            if inactive:
                rate *= INACTIVE_HAIRCUT
        out["WSV"] = rate * games_left
    return out


def slot_rsar(carry: dict, ros: dict, mlera: float) -> float:
    ip = carry.get("IP", 0) + ros["IP"]
    er = carry.get("ERA", 0) * carry.get("IP", 0) / 9 + ros["ER"]
    g = carry.get("G", 0) + ros["G"]
    if ip <= 0:
        return 0.0
    if g > 0 and ip / g < config.SP_MIN_IP_PER_GAME:
        return 0.0
    return round((1.2 * mlera - er * 9 / ip) * ip / 9)


def team_sp_points(rsars: list[float]) -> float:
    top = sorted(rsars, reverse=True)[:config.SP_SCORING_COUNT]
    return sum(top) * config.SP_RSAR_MULTIPLIER


# ---------------------------------------------------------------------------
# Slot carryover (Levinsons only): season_stats.json as of the as-of date
# ---------------------------------------------------------------------------

def carryover_as_of(as_of: date) -> dict:
    try:
        sha = subprocess.run(["git", "log", "-1", f"--before={as_of.isoformat()}T23:59:59", "--format=%H",
                              "--", "data/season_stats.json"], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
        if sha:
            raw = subprocess.run(["git", "show", f"{sha}:data/season_stats.json"], cwd=REPO,
                                 capture_output=True, text=True, check=True).stdout
            return json.loads(raw)
    except Exception:
        pass
    return {}


def carry_for_slot(uni: Universe, carry_all: dict, slot_entry: dict) -> dict:
    """Slot carryover in the season_stats schema. Prefer the committed slot record
    whose key ends with the incumbent's surname; else the incumbent's YTD line."""
    rec = slot_entry["player"]
    _, last = name_parts(rec["name"])
    for k, v in carry_all.items():
        if name_parts(k.split("/")[-1])[1] == last and (("AB" in v) == (rec["ptype"] == "hitter")):
            return dict(v)
    y = uni.ytd(rec)
    if not y:
        return {}
    if rec["ptype"] == "hitter":
        return {k: y[k] for k in ("AB", "H", "HR", "RBI", "R", "SB")}
    out = {"IP": y["IP"], "G": y["G"], "GS": y["GS"], "ERA": (y["ER"] * 9 / y["IP"]) if y["IP"] else 0.0, "W": y["W"]}
    if y["SV"]:
        out["SV"] = y["SV"]
    return out


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def eligible_for(rec: dict, slot: str) -> bool:
    if slot == "DH":
        return rec["ptype"] == "hitter"
    if slot in HITTER_SLOTS:
        return rec["ptype"] == "hitter" and any(config.POSITION_ELIGIBILITY.get(p, [p]) and slot in config.POSITION_ELIGIBILITY.get(p, [p]) for p in rec["positions"])
    return rec["ptype"] == slot.lower()


def fmt_hit(y):
    if not y or not y.get("AB"):
        return "no AB"
    return f"{y['AB']} AB .{int(round(y['H'] / y['AB'] * 1000)):03d} {y['HR']} HR {y['RBI']} RBI {y['R']} R {y['SB']} SB"


def fmt_pit(y):
    if not y or not y.get("IP"):
        return "no IP"
    era = y["ER"] * 9 / y["IP"]
    return f"{y['IP']:.1f} IP {era:.2f} ERA {y['G']} G {y['W']} W {y['SV']} SV"


def analyze(as_of: date, bbsubs: Path | None, season_end: date, only_slot: str | None, top: int, mlera: float):
    global SEASON_END
    SEASON_END = season_end
    log: list[str] = []
    uni = Universe(as_of)
    rosters = build_rosters(uni, bbsubs, as_of, log)
    rostered = {id(s["player"]) for r in rosters.values() for s in r if s["player"] is not None}
    mine = rosters[MY_TEAM]
    games_left = remaining_games(as_of, season_end)
    carry_all = carryover_as_of(as_of)

    print(f"\nSWAP WINDOW — {MY_TEAM} — as of {as_of} — {games_left:.0f} team games left (season ends {season_end}), MLERA {mlera}")
    print(f"Rosters: draft board + {bbsubs.name if bbsubs else 'no BBSUBS'}; FA pool = {len(uni.players) - len(rostered)} of {len(uni.players)} players")
    if log:
        print("\nResolution notes:")
        for line in log:
            print("  -", line)

    # --- precompute my SP slot RSARs (for the top-3 marginal logic)
    sp_slots = [s for s in mine if s["slot"] == "SP"]
    sp_rsar = {}
    for s in sp_slots:
        carry = carry_for_slot(uni, carry_all, s)
        ros = pitcher_ros(uni, s["player"], games_left, "sp") or {"IP": 0, "ER": 0, "G": 0, "era": 0, "inactive": True, "ytd": None, "r30": None}
        sp_rsar[id(s)] = slot_rsar(carry, ros, mlera)
    base_sp = team_sp_points(list(sp_rsar.values()))

    summary = []
    for s in mine:
        slot = s["slot"]
        if only_slot and slot != only_slot.upper():
            continue
        inc = s["player"]
        carry = carry_for_slot(uni, carry_all, s)
        rows = []
        if slot in HITTER_SLOTS:
            inc_ros = hitter_ros(uni, inc, games_left) or {"AB": 0, "H": 0, "HR": 0, "RBI": 0, "R": 0, "SB": 0, "inactive": True, "ytd": None, "r30": None, "avg": 0}
            base = hitter_bt(carry, inc_ros)
            for key, rec in uni.players.items():
                if id(rec) in rostered or not eligible_for(rec, slot):
                    continue
                ros = hitter_ros(uni, rec, games_left)
                if ros is None or ros["AB"] < 30:
                    continue
                rows.append((hitter_bt(carry, ros) - base, rec, ros))
            inc_line = f"{fmt_hit(inc_ros['ytd'])} | 30d: {fmt_hit(inc_ros['r30'])} | ROS {inc_ros['AB']:.0f} AB .{int(round(inc_ros['avg']*1000)):03d}{' INACTIVE' if inc_ros['inactive'] else ''}"
            def cand_line(rec, ros):
                return f"{fmt_hit(ros['ytd'])} | 30d: {fmt_hit(ros['r30'])} | ROS {ros['AB']:.0f} AB .{int(round(ros['avg']*1000)):03d} {ros['HR']:.0f}/{ros['RBI']:.0f}/{ros['R']:.0f}/{ros['SB']:.0f}{' INACTIVE' if ros['inactive'] else ''}"
        elif slot == "SP":
            inc_ros = pitcher_ros(uni, inc, games_left, "sp") or {"IP": 0, "ER": 0, "G": 0, "era": 0, "inactive": True, "ytd": None, "r30": None}
            others = [v for k, v in sp_rsar.items() if k != id(s)]
            base = base_sp
            for key, rec in uni.players.items():
                if id(rec) in rostered or rec["ptype"] != "sp":
                    continue
                ros = pitcher_ros(uni, rec, games_left, "sp")
                if ros is None or ros["IP"] < 15:
                    continue
                cand_rsar = slot_rsar(carry, ros, mlera)
                rows.append((team_sp_points(others + [cand_rsar]) - base, rec, ros))
            inc_line = f"{fmt_pit(inc_ros['ytd'])} | 30d: {fmt_pit(inc_ros['r30'])} | ROS {inc_ros['IP']:.0f} IP {inc_ros['era']:.2f} ERA | slot RSAR {sp_rsar[id(s)]:.0f}{' INACTIVE' if inc_ros['inactive'] else ''}"
            def cand_line(rec, ros):
                return f"{fmt_pit(ros['ytd'])} | 30d: {fmt_pit(ros['r30'])} | ROS {ros['IP']:.0f} IP {ros['era']:.2f} ERA | slot RSAR {slot_rsar(carry, ros, mlera):.0f}{' INACTIVE' if ros['inactive'] else ''}"
        else:  # RP
            inc_ros = pitcher_ros(uni, inc, games_left, "rp") or {"WSV": 0, "inactive": True, "ytd": None, "r30": None, "IP": 0, "era": 0}
            base = config.RP_WIN_SAVE_MULTIPLIER * inc_ros["WSV"]
            for key, rec in uni.players.items():
                if id(rec) in rostered or rec["ptype"] != "rp":
                    continue
                ros = pitcher_ros(uni, rec, games_left, "rp")
                if ros is None or (ros["ytd"] or {}).get("IP", 0) < 5:
                    continue
                rows.append((config.RP_WIN_SAVE_MULTIPLIER * ros["WSV"] - base, rec, ros))
            inc_line = f"{fmt_pit(inc_ros['ytd'])} | 30d: {fmt_pit(inc_ros['r30'])} | ROS {inc_ros['WSV']:.1f} W+SV = {base:.0f} pts{' INACTIVE' if inc_ros['inactive'] else ''}"
            def cand_line(rec, ros):
                return f"{fmt_pit(ros['ytd'])} | 30d: {fmt_pit(ros['r30'])} | ROS {ros['WSV']:.1f} W+SV = {config.RP_WIN_SAVE_MULTIPLIER * ros['WSV']:.0f} pts{' INACTIVE' if ros['inactive'] else ''}"

        # ties (common for SP slots outside the best three) break on the candidate's own value
        def own_value(t):
            if slot in HITTER_SLOTS:
                return hitter_bt({}, t[2])
            if slot == "SP":
                return slot_rsar(carry, t[2], mlera)
            return t[2]["WSV"]
        rows.sort(key=lambda t: (-t[0], -own_value(t)))
        print(f"\n== {slot}: {inc['name']} ({inc['team']}) since {s['since']}")
        print(f"   incumbent: {inc_line}")
        if slot == "SP":
            third = sorted(sp_rsar.values(), reverse=True)[min(config.SP_SCORING_COUNT, len(sp_rsar)) - 1]
            if sp_rsar[id(s)] < third:
                print(f"   (outside the best three: a replacement only scores if its slot RSAR beats {third:.0f})")
        for delta, rec, ros in rows[:top]:
            print(f"   {delta:+6.0f}  {rec['name']:24s} {rec['team']:4s} {cand_line(rec, ros)}")
        if rows:
            summary.append((rows[0][0], slot, inc["name"], rows[0][1]["name"], rows[0][1]["team"],
                            rows[1][0] if len(rows) > 1 else None, rows[1][1]["name"] if len(rows) > 1 else ""))

    print("\n== Best move per slot (delta = change in slot-final BT points; SP through the best-three rule)")
    for delta, slot, inc, fa, team, d2, fa2 in sorted(summary, key=lambda t: -t[0]):
        runner = f"   (next: {fa2} {d2:+.0f})" if d2 is not None else ""
        print(f"   {delta:+6.0f}  {slot:3s}  {inc:22s} -> {fa} ({team}){runner}")


# ---------------------------------------------------------------------------
# Hold vs replace (2027 workstream 4)
# ---------------------------------------------------------------------------

def _slot_points(uni, s, carry, rec, games_left, mlera, others_rsar, projected_pt=False):
    """Slot-final BT points if `rec` fills slot `s` for `games_left` team games."""
    slot = s["slot"]
    if slot in HITTER_SLOTS:
        ros = hitter_ros(uni, rec, games_left, projected_pt)
        return None if ros is None else hitter_bt(carry, ros), ros
    if slot == "SP":
        ros = pitcher_ros(uni, rec, games_left, "sp", projected_pt)
        return None if ros is None else team_sp_points(others_rsar + [slot_rsar(carry, ros, mlera)]), ros
    ros = pitcher_ros(uni, rec, games_left, "rp", projected_pt)
    return None if ros is None else config.RP_WIN_SAVE_MULTIPLIER * ros["WSV"], ros


def hold_vs_replace(as_of: date, bbsubs: Path | None, season_end: date, slot: str,
                    return_date: date, mlera: float, top: int = 3):
    """Should an injured incumbent be held through the IL stint or replaced?

    Held  = carryover + his production from `return_date` to season end at
            RETURN_HAIRCUT × projected per-game playing time (regressed rates).
    Swap  = carryover + the best free agent's production from `as_of`.
    Also prints the break-even return date: the latest return for which
    holding still beats the best swap. Motivated by the 2026 catcher chain
    (Raleigh held would have scored 325; the three-catcher chain scored 296).
    """
    global SEASON_END
    SEASON_END = season_end
    slot = slot.upper()
    log: list[str] = []
    uni = Universe(as_of)
    rosters = build_rosters(uni, bbsubs, as_of, log)
    rostered = {id(x["player"]) for r in rosters.values() for x in r if x["player"] is not None}
    mine = rosters[MY_TEAM]
    carry_all = carryover_as_of(as_of)
    games_left = remaining_games(as_of, season_end)
    slots = [x for x in mine if x["slot"] == slot]
    if not slots:
        sys.exit(f"no {slot} slot on the {MY_TEAM} roster")
    s = slots[0]
    inc = s["player"]
    carry = carry_for_slot(uni, carry_all, s)
    others_rsar = []
    if slot == "SP":
        for x in mine:
            if x["slot"] == "SP" and x is not s:
                c2 = carry_for_slot(uni, carry_all, x)
                r2 = pitcher_ros(uni, x["player"], games_left, "sp")
                others_rsar.append(slot_rsar(c2, r2, mlera) if r2 else 0.0)

    # best free agents from as_of
    cands = []
    for rec in uni.players.values():
        if id(rec) in rostered or rec is inc:
            continue
        if slot in HITTER_SLOTS and not eligible_for(rec, slot):
            continue
        if slot == "SP" and rec["ptype"] != "sp":
            continue
        if slot == "RP" and rec["ptype"] != "rp":
            continue
        pts, ros = _slot_points(uni, s, carry, rec, games_left, mlera, others_rsar)
        if pts is None or ros.get("inactive"):
            continue
        cands.append((pts, rec, ros))
    cands.sort(key=lambda t: -t[0])
    swap_pts, best, best_ros = cands[0]

    def held_at(ret: date):
        g = remaining_games(ret, season_end) if ret <= season_end else 0.0
        pts, _ = _slot_points(uni, s, carry, inc, g, mlera, others_rsar, projected_pt=True)
        return pts if pts is not None else _slot_points(uni, s, carry, inc, 0.0, mlera, others_rsar, projected_pt=True)[0]

    held_pts = held_at(return_date)
    # break-even: latest return date at which holding still beats the swap
    breakeven = None
    d = as_of
    while d <= season_end:
        if held_at(d) >= swap_pts:
            breakeven = d
        else:
            break
        d += timedelta(days=7)

    print(f"\nHOLD vs REPLACE — {slot} — {inc['name']} ({inc['team']}) — as of {as_of}, expected return {return_date}, season ends {season_end}")
    print(f"   carryover in the slot: {carry}")
    print(f"   HOLD    {inc['name']:22s} back {return_date}: slot-final {held_pts:6.0f} pts")
    print(f"   REPLACE {best['name']:22s} from {as_of}:  slot-final {swap_pts:6.0f} pts")
    print(f"   verdict: {'HOLD' if held_pts >= swap_pts else 'REPLACE'} by {abs(held_pts - swap_pts):.0f} pts")
    if breakeven is None:
        print(f"   break-even: holding never beats the swap, even with an immediate return")
    else:
        print(f"   break-even: holding wins if he is back by about {breakeven} (weekly steps); later than that, replace")
    print(f"   next-best replacements: " + "; ".join(f"{r['name']} {p:.0f}" for p, r, _ in cands[1:top + 1]))
    if log:
        print("   resolution notes: " + " | ".join(log[:3]))
    return {"held": held_pts, "swap": swap_pts, "best": best["name"], "breakeven": breakeven}


def main():
    ap = argparse.ArgumentParser(description="Roster-wide swap-window analysis")
    ap.add_argument("--as-of", required=True, help="Analysis date YYYY-MM-DD (stats through the day before)")
    ap.add_argument("--bbsubs", help="Path to the commissioner's BBSUBS .xls (omit = draft rosters only)")
    ap.add_argument("--slot", help="Only this slot: C 1B 2B 3B SS OF DH SP RP")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--season-end", default=SEASON_END.isoformat())
    ap.add_argument("--mlera", type=float, default=config.MLB_AVG_ERA)
    ap.add_argument("--hold", action="store_true", help="Hold-vs-replace mode for an injured incumbent (needs --slot and --return-date)")
    ap.add_argument("--return-date", help="Expected return date YYYY-MM-DD for --hold")
    a = ap.parse_args()
    as_of = date.fromisoformat(a.as_of)
    bb = Path(a.bbsubs).expanduser() if a.bbsubs else None
    if bb and not bb.exists():
        sys.exit(f"BBSUBS not found: {bb}")
    if a.hold:
        if not (a.slot and a.return_date):
            sys.exit("--hold needs --slot and --return-date")
        hold_vs_replace(as_of, bb, date.fromisoformat(a.season_end), a.slot,
                        date.fromisoformat(a.return_date), a.mlera, a.top)
        return
    analyze(as_of, bb, date.fromisoformat(a.season_end), a.slot, a.top, a.mlera)


if __name__ == "__main__":
    main()
