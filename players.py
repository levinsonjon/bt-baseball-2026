"""
players.py — Player data model and projected points calculation.

Scoring implemented per BT Baseball Pool 2026 rules:
  Hitters:  round(BA × 1000) + HR + RBI + R + SB  (300 AB minimum rule)
  SP:       RSAR × 3.5  [individual value; team uses top 3 of 6]
  RP:       5 × (W + SV)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import config


@dataclass
class Player:
    """Represents a single player with projected stats and fantasy metadata."""

    # Identity
    name: str
    team: str
    positions: list[str]       # e.g. ["2B", "SS"] for dual-eligible
    player_type: str           # "hitter", "sp", or "rp"

    # Projected stats (keyed by stat name)
    projected_stats: dict = field(default_factory=dict)

    # Health/status
    health_status: str = "healthy"
    injury_note: str = ""

    # Computed fields
    projected_points: float = 0.0
    rsar: float = 0.0                  # SP only: runs saved against replacement
    rank_overall: Optional[int] = None
    rank_by_position: dict = field(default_factory=dict)

    # Draft state
    is_drafted: bool = False
    drafted_by: Optional[str] = None

    def __post_init__(self):
        self.compute_projected_points()

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def compute_projected_points(self) -> float:
        """
        Compute this player's projected fantasy points per league rules.
        Applies a playing-time discount for injured/uncertain players.
        """
        if self.player_type == "hitter":
            raw = self._score_hitter()
        elif self.player_type == "sp":
            raw = self._score_sp()
        elif self.player_type == "rp":
            raw = self._score_rp()
        else:
            raw = 0.0

        discount = config.PLAYING_TIME_DISCOUNTS.get(self.health_status, 1.0)
        self.projected_points = round(raw * discount, 2)
        return self.projected_points

    def _score_hitter(self) -> float:
        """
        Hitter score = round(BA × 1000) + HR + RBI + R + SB

        300 AB minimum rule: if projected AB < 300, the shortfall is added to
        the denominator (AB) without adding hits, which reduces effective BA.

        TODO: Verify that Pitcherlist provides projected AB. If not, AB will be 0
        for all hitters, triggering the 300 AB floor universally and breaking BA
        scoring. May need to derive AB from PA (AB ≈ PA − BB − HBP) or supplement
        from a secondary source. Test and adjust after first Pitcherlist scrape.
        """
        s = self.projected_stats

        # Batting average with 300 AB floor
        ab = s.get("AB", 0)
        hits = s.get("H", 0)
        effective_ab = max(ab, config.HITTER_MIN_AB)  # pad AB up to 300 if needed
        ba = hits / effective_ab if effective_ab > 0 else 0.0
        ba_points = round(ba * 1000)

        hr  = s.get("HR", 0)
        rbi = s.get("RBI", 0)
        r   = s.get("R", 0)
        sb  = s.get("SB", 0)

        return float(ba_points + hr + rbi + r + sb)

    def _score_sp(self) -> float:
        """
        SP score (individual) = RSAR × 3.5

        RSAR = (1.2 × MLB_AVG_ERA − ERA) × (IP / 9)

        Penalty: if IP/G < 3.5, score = 0 (reliever-as-starter rule).

        Note: the team's SP score uses only the top 3 of 6 starters.
        Individual player value here assumes they ARE one of the top 3.
        Draft rankings for the 4th-6th SP picks should be discounted accordingly.
        """
        s = self.projected_stats
        era = s.get("ERA")
        ip  = s.get("IP", 0)
        g   = s.get("G", s.get("GS", 1))   # use GS if G not available

        if era is None or ip == 0:
            self.rsar = 0.0
            return 0.0

        # Reliever penalty: < 3.5 IP/game appearance = 0
        if g > 0 and (ip / g) < config.SP_MIN_IP_PER_GAME:
            self.rsar = 0.0
            return 0.0

        self.rsar = (1.2 * config.MLB_AVG_ERA - era) * (ip / 9)
        return round(self.rsar * config.SP_RSAR_MULTIPLIER, 2)

    def _score_rp(self) -> float:
        """RP score = 5 × (W + SV)"""
        s = self.projected_stats
        return float(config.RP_WIN_SAVE_MULTIPLIER * (s.get("W", 0) + s.get("SV", 0)))

    # ------------------------------------------------------------------
    # Position eligibility
    # ------------------------------------------------------------------

    def eligible_slots(self) -> list[str]:
        """Return all roster slot types this player can fill."""
        slots = set()
        for pos in self.positions:
            for slot in config.POSITION_ELIGIBILITY.get(pos, []):
                slots.add(slot)
        return sorted(slots)

    def can_fill(self, slot: str) -> bool:
        return slot in self.eligible_slots()

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    @property
    def position_str(self) -> str:
        return "/".join(self.positions)

    def stat_summary(self) -> str:
        s = self.projected_stats
        if self.player_type == "hitter":
            ab   = s.get("AB", "-")
            ba   = f"{s.get('H', 0) / max(s.get('AB', 1), 1):.3f}" if s.get("AB") else "-"
            return (f"AB:{ab}  BA:{ba}  HR:{s.get('HR','-')}  "
                    f"RBI:{s.get('RBI','-')}  R:{s.get('R','-')}  SB:{s.get('SB','-')}")
        elif self.player_type == "sp":
            return (f"IP:{s.get('IP','-')}  ERA:{s.get('ERA','-')}  "
                    f"G:{s.get('G','-')}  RSAR:{self.rsar:.1f}")
        else:
            return f"W:{s.get('W','-')}  SV:{s.get('SV','-')}"

    def __repr__(self) -> str:
        return (
            f"<Player {self.name} | {self.team} | {self.position_str} | "
            f"{self.projected_points:.1f} pts | {self.health_status}>"
        )


# ---------------------------------------------------------------------------
# Roster class
# ---------------------------------------------------------------------------

class Roster:
    """Jon's drafted team."""

    def __init__(self):
        self.players: list[Player] = []

    def add(self, player: Player):
        player.drafted_by = "Jon"
        player.is_drafted = True
        self.players.append(player)

    def hitters(self) -> list[Player]:
        return [p for p in self.players if p.player_type == "hitter"]

    def starters(self) -> list[Player]:
        return [p for p in self.players if p.player_type == "sp"]

    def relievers(self) -> list[Player]:
        return [p for p in self.players if p.player_type == "rp"]

    def top_sp_score(self) -> float:
        """
        Team SP score: sum of top-3 starters' RSAR × 3.5.
        RSARs are rounded individually before summing, per rules.
        """
        rsars = sorted([p.rsar for p in self.starters()], reverse=True)
        top3 = rsars[:config.SP_SCORING_COUNT]
        return round(sum(round(r) for r in top3) * config.SP_RSAR_MULTIPLIER, 2)

    def open_slots(self) -> list[str]:
        """Return roster slots not yet filled."""
        needed = []
        for slot, count in config.ACTIVE_SLOTS.items():
            filled = sum(1 for p in self.players if slot in p.eligible_slots())
            needed.extend([slot] * max(count - filled, 0))
        return needed

    def total_projected_points(self) -> float:
        hitter_pts = sum(p.projected_points for p in self.hitters())
        sp_pts = self.top_sp_score()
        rp_pts = sum(p.projected_points for p in self.relievers())
        return round(hitter_pts + sp_pts + rp_pts, 2)

    def to_dict_list(self) -> list[dict]:
        return [
            {
                "name": p.name,
                "team": p.team,
                "positions": p.position_str,
                "player_type": p.player_type,
                "health_status": p.health_status,
                "projected_points": p.projected_points,
                **p.projected_stats,
            }
            for p in self.players
        ]


# ---------------------------------------------------------------------------
# Ranking utilities
# ---------------------------------------------------------------------------

def rank_players(players: list[Player]) -> list[Player]:
    """Sort by projected_points descending and assign overall rank."""
    sorted_players = sorted(players, key=lambda p: p.projected_points, reverse=True)
    for i, p in enumerate(sorted_players, 1):
        p.rank_overall = i
    return sorted_players


def rank_by_position(players: list[Player]) -> dict[str, list[Player]]:
    """
    Return a dict mapping each roster slot to eligible players sorted by
    projected points.
    """
    by_pos: dict[str, list[Player]] = {}
    for slot in config.ACTIVE_SLOTS:
        eligible = [p for p in players if p.can_fill(slot)]
        eligible.sort(key=lambda p: p.projected_points, reverse=True)
        for rank, p in enumerate(eligible, 1):
            p.rank_by_position[slot] = rank
        by_pos[slot] = eligible
    return by_pos
