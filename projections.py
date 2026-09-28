"""
projections.py — Aggregate projections from all sources, apply scoring formula,
and produce a ranked player list.

Sources:
1. PitcherList Excel export (data/pitcherlist_projections.xlsx) — projected stats
2. players_master.csv — position eligibility for hitters
3. data/history/ (build_history.py) — prior-season playing time, IL placements,
   birthdates, used by playing_time.py to scale counting stats to the playing
   time each player has actually delivered (2027 workstream 1)

Outputs:
- Ranked list of Player objects (written to Google Sheets by sheets.py)
"""

from __future__ import annotations
import csv
import json
import unicodedata
from pathlib import Path
from typing import Optional

from players import Player, rank_players, rank_by_position
import config


def _normalize_name(name: str) -> str:
    """Normalize player name: strip accents, lowercase, remove punctuation."""
    # Decompose unicode, strip combining marks (accents)
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
    return ascii_name.strip().lower()

DATA_DIR = Path(__file__).parent / "data"
MASTER_CSV = DATA_DIR / "players_master.csv"
CACHE_FILE = DATA_DIR / "projections_cache.json"


# ---------------------------------------------------------------------------
# Loading from PitcherList Excel file
# ---------------------------------------------------------------------------

def load_from_pitcherlist() -> list[Player]:
    """
    Load projections from the PitcherList Excel file.
    Returns an empty list if the file is missing or unreadable.
    """
    try:
        from pitcherlist import load_projections
        return load_projections()
    except Exception as e:
        print(f"[projections] PitcherList load failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Loading position eligibility from master CSV
# ---------------------------------------------------------------------------

def load_position_map() -> dict[str, list[str]]:
    """
    Load position eligibility from players_master.csv.
    Returns a dict mapping normalized player name -> list of positions.
    """
    if not MASTER_CSV.exists():
        return {}

    pos_map = {}
    with open(MASTER_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = _normalize_name(row.get("name", ""))
            positions = [p.strip() for p in row.get("positions", "").split("/") if p.strip()]
            if name and positions:
                pos_map[name] = positions

    return pos_map


# ---------------------------------------------------------------------------
# Merge PitcherList projections with position eligibility
# ---------------------------------------------------------------------------

def apply_positions(players: list[Player], pos_map: dict[str, list[str]]) -> list[Player]:
    """
    Update hitter position eligibility from the master CSV.
    Pitchers keep their SP/RP designation from the Excel file.
    """
    for p in players:
        if p.player_type == "hitter":
            key = _normalize_name(p.name)
            if key in pos_map:
                p.positions = pos_map[key]
            # If not in master CSV, the player keeps ["DH"] (set by pitcherlist.py)
    return players


# ---------------------------------------------------------------------------
# Playing time
# ---------------------------------------------------------------------------

def apply_playing_time(players: list[Player], season: int) -> list[Player]:
    """Scale each player's counting stats by the playing-time factor from
    playing_time.py. Idempotent: always scales from raw_projected_stats.
    Skips (with a message) when data/history/ has not been built."""
    try:
        from playing_time import History, playing_time_factor, apply_to_stats, risk_profile
        history = History.load()
    except FileNotFoundError:
        print("[projections] data/history/ missing — run build_history.py; "
              "projections assume full playing time.")
        return players
    for p in players:
        if not p.raw_projected_stats:
            p.raw_projected_stats = dict(p.projected_stats)
        pt = playing_time_factor(history, p.name, p.player_type, p.positions,
                                 season, projected_stats=p.raw_projected_stats)
        p.pt_factor = pt["factor"]
        p.projected_stats = apply_to_stats(p.raw_projected_stats, p.player_type, p.pt_factor)
        risk = risk_profile(pt)
        p.risk_sd, p.risk_tier, p.risk_note = risk["risk_sd"], risk["risk_tier"], risk["risk_note"]
    discounted = sum(1 for p in players if p.pt_factor < 0.999)
    print(f"[projections] Playing-time factors applied ({discounted} of {len(players)} below 1.0).")
    return players


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

def save_cache(players: list[Player]):
    """Persist projection data as JSON for offline use."""
    data = [
        {
            "name": p.name,
            "team": p.team,
            "positions": p.positions,
            "player_type": p.player_type,
            "projected_stats": p.projected_stats,
            "raw_projected_stats": p.raw_projected_stats or p.projected_stats,
            "pt_factor": p.pt_factor,
            "risk_sd": p.risk_sd,
            "risk_tier": p.risk_tier,
            "risk_note": p.risk_note,
            "projected_points": p.projected_points,
            "health_status": p.health_status,
            "injury_note": p.injury_note,
        }
        for p in players
    ]
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print(f"[projections] Saved {len(players)} players to cache.")


def load_cache() -> list[Player]:
    """Load the last cached projection run."""
    if not CACHE_FILE.exists():
        return []
    with open(CACHE_FILE) as f:
        data = json.load(f)
    players = []
    for d in data:
        p = Player(
            name=d["name"],
            team=d["team"],
            positions=d["positions"],
            player_type=d["player_type"],
            projected_stats=d.get("projected_stats", {}),
            health_status=d.get("health_status", "healthy"),
            injury_note=d.get("injury_note", ""),
        )
        p.raw_projected_stats = d.get("raw_projected_stats", {}) or dict(p.projected_stats)
        p.pt_factor = d.get("pt_factor", 1.0)
        p.risk_sd = d.get("risk_sd", 0.25)
        p.risk_tier = d.get("risk_tier", "")
        p.risk_note = d.get("risk_note", "")
        players.append(p)
    print(f"[projections] Loaded {len(players)} players from cache.")
    return players


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_projections(use_cache: bool = False) -> list[Player]:
    """
    Full projection pipeline:
    1. Load projections from PitcherList Excel file (or cache)
    2. Apply position eligibility from master CSV
    2b. Scale counting stats by expected playing time (playing_time.py)
    3. Compute scores
    4. Rank players
    5. Save cache

    Returns ranked list of Player objects.
    """
    print("[projections] Starting projection pipeline...")

    if use_cache:
        players = load_cache()
        if not players:
            print("[projections] Cache empty — loading from file.")
            use_cache = False

    if not use_cache:
        players = load_from_pitcherlist()
        if not players:
            print("[projections] No PitcherList data — falling back to cache.")
            players = load_cache()

        pos_map = load_position_map()
        players = apply_positions(players, pos_map)
        players = apply_playing_time(players, config.SEASON)
        save_cache(players)

    # Apply injury data from ESPN before scoring
    try:
        from update_health import apply_injuries_to_players
        apply_injuries_to_players(players)
    except Exception as e:
        print(f"[projections] Could not fetch injury data: {e}")

    # Re-compute points to pick up any config changes and injury discounts
    for p in players:
        p.compute_projected_points()

    ranked = rank_players(players)
    _ = rank_by_position(ranked)  # populates p.rank_by_position on each player

    print(f"[projections] Ranked {len(ranked)} players. "
          f"Top 5: {[p.name for p in ranked[:5]]}")

    return ranked


if __name__ == "__main__":
    players = run_projections()
    print(f"\nTop 20 overall:")
    for p in players[:20]:
        print(f"  #{p.rank_overall:3d}  {p.name:<25} {p.team:<5} "
              f"{p.position_str:<10} {p.projected_points:7.1f} pts  {p.health_status}")
