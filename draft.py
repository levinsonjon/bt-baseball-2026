"""
draft.py — Draft day tool.

Polls the league draft tracker Google Sheet for new picks, tracks Jon's roster,
and surfaces recommendations for upcoming picks.

Usage (from run_draft.py):
    from draft import DraftMonitor
    monitor = DraftMonitor(players=ranked_players, pick_number=5)

The draft tracker sheet is a roster grid:
    Column A: Position labels (Catcher, 1B, 2B, etc.)
    Columns B-J: Team owners (9 teams)
    Player names are filled into cells as picks are made.
"""

from __future__ import annotations
import time
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

from players import Player, Roster
import config

MY_TEAM_FILE = Path(__file__).parent / "data" / "my_team.json"
POLL_INTERVAL_SECONDS = 30


# ---------------------------------------------------------------------------
# Draft tracker sheet parser
# ---------------------------------------------------------------------------

def parse_tracker_response(mcp_data: list) -> dict[str, list[tuple[str, str]]]:
    """
    Parse the MCP gsheets_read response from the draft tracker sheet.

    The tracker sheet is a roster grid:
        Row 3: header row with team owner names (columns B-J)
        Rows 4+: position labels in column A, player names in team columns

    Args:
        mcp_data: The list returned by mcp__gdrive-personal__gsheets_read.
                  Expected to contain one sheet object with 'data' and 'columnHeaders'.

    Returns:
        Dict mapping team owner name -> list of (position_slot, player_name) tuples.
        Only non-empty cells are included.
    """
    if not mcp_data:
        return {}

    sheet = mcp_data[0]
    rows = sheet.get("data", [])

    # Find the header row: the row where column A contains "Position".
    # Team owner names are in the remaining columns of that row.
    col_to_team: dict[int, str] = {}
    header_row_idx = None

    for i, row in enumerate(rows):
        for cell in row:
            loc = cell.get("location", "")
            val = cell.get("value", "").strip()
            col_idx = _col_letter_to_index(loc)
            if col_idx == 0 and val == "Position":
                header_row_idx = i
                break
        if header_row_idx is not None:
            # Now read team names from this row
            for cell in rows[header_row_idx]:
                loc = cell.get("location", "")
                val = cell.get("value", "").strip()
                if not val or val == "Position":
                    continue
                col_idx = _col_letter_to_index(loc)
                if col_idx is not None and col_idx > 0:
                    col_to_team[col_idx] = val
            break

    if not col_to_team:
        return {}

    # Parse data rows after the header: column A = position label, other columns = player names
    team_rosters: dict[str, list[tuple[str, str]]] = {name: [] for name in col_to_team.values()}
    last_position = None

    for row in rows[header_row_idx + 1:]:
        if not row:
            continue

        # Determine position for this row
        row_position = None
        row_players: dict[int, str] = {}

        for cell in row:
            loc = cell.get("location", "")
            val = cell.get("value", "").strip()
            if not val:
                continue
            col_idx = _col_letter_to_index(loc)
            if col_idx is None:
                continue

            if col_idx == 0:  # Column A = position label
                normalized = config.TRACKER_POSITION_MAP.get(val)
                if normalized:
                    row_position = normalized
                    last_position = normalized
            elif col_idx in col_to_team:
                cleaned = _strip_pick_number(val)
                # Skip purely numeric values (e.g. DH order numbers)
                if cleaned and not cleaned.isdigit():
                    row_players[col_idx] = cleaned

        # If this row has no position label but has player data,
        # inherit the last seen position (handles unlabeled SP pair rows)
        if row_position is None and row_players and last_position:
            row_position = last_position

        # Record players
        if row_position and row_players:
            for col_idx, player_name in row_players.items():
                team_name = col_to_team[col_idx]
                team_rosters[team_name].append((row_position, player_name))

    return team_rosters


def _col_letter_to_index(location: str) -> Optional[int]:
    """Extract 0-based column index from a cell location like 'Sheet1!B3'."""
    import re
    m = re.search(r'!([A-Z]+)\d+', location)
    if not m:
        return None
    letters = m.group(1)
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - ord('A'))
    return idx


class DraftMonitor:
    """
    Tracks draft state and generates pick recommendations.
    """

    def __init__(self, players: list[Player], pick_number: int):
        """
        Args:
            players: Ranked player list from projections.py
            pick_number: Jon's draft position (1-indexed, 1 = first pick)
        """
        self.all_players = players
        self.pick_number = pick_number
        self.league_size = config.LEAGUE_SIZE
        self.roster = Roster()

        # State tracking
        self.drafted_names: set[str] = set()   # all drafted player names (normalized)
        self.draft_log: list[dict] = []         # {"overall_pick": N, "name": str, "team": str}
        self.current_overall_pick: int = 0

        # Pre-compute Jon's pick slots for all rounds
        self.my_pick_slots = self._compute_my_picks(rounds=20)
        print(f"[draft] Jon's pick slots: {self.my_pick_slots[:10]}...")

    def _compute_my_picks(self, rounds: int) -> list[int]:
        """
        Calculate Jon's overall pick numbers for a snake draft.
        Round 1: pick N, Round 2: pick (2*league_size - N + 1), etc.
        """
        picks = []
        n = self.pick_number
        size = self.league_size
        for r in range(1, rounds + 1):
            if r % 2 == 1:  # odd rounds: ascending
                slot = (r - 1) * size + n
            else:           # even rounds: descending
                slot = r * size - n + 1
            picks.append(slot)
        return picks

    def next_my_pick(self) -> Optional[int]:
        """Return the next overall pick number that belongs to Jon."""
        for slot in self.my_pick_slots:
            if slot > self.current_overall_pick:
                return slot
        return None

    def picks_until_mine(self) -> int:
        """How many picks until Jon's next turn."""
        nxt = self.next_my_pick()
        if nxt is None:
            return 999
        return nxt - self.current_overall_pick

    # ------------------------------------------------------------------
    # Ingest picks from the sheet
    # ------------------------------------------------------------------

    def ingest_sheet_data(self, sheet_rows: list[list]) -> int:
        """
        Process raw rows from the draft sheet.
        Returns the number of new picks detected.
        """
        new_picks = 0
        for row in sheet_rows:
            if not row or len(row) < 2:
                continue
            try:
                overall = int(row[0])
            except (ValueError, TypeError):
                continue

            if overall <= self.current_overall_pick:
                continue  # already processed

            name = str(row[1]).strip()
            team = str(row[2]).strip() if len(row) > 2 else "Unknown"

            if not name:
                continue

            pick = {"overall_pick": overall, "name": name, "team": team}
            self.draft_log.append(pick)
            self.drafted_names.add(_normalize_name(name))
            self.current_overall_pick = overall

            # Check if this was Jon's pick
            if overall in self.my_pick_slots:
                player = self._find_player(name)
                if player:
                    self.roster.add(player)
                    print(f"[draft] Jon drafted: {name} (pick #{overall})")
                else:
                    print(f"[draft] Jon drafted: {name} (pick #{overall}) [not in projection list]")

            new_picks += 1

        return new_picks

    # ------------------------------------------------------------------
    # Ingest picks from the roster grid (draft tracker sheet)
    # ------------------------------------------------------------------

    def ingest_roster_grid(self, team_rosters: dict[str, list[tuple[str, str]]]) -> list[dict]:
        """
        Process the roster grid from the draft tracker sheet.

        Args:
            team_rosters: Output of parse_tracker_response().
                          {team_name: [(position, player_name), ...]}

        Returns:
            List of new pick dicts: {"name", "team", "position", "is_mine"}
        """
        # Build the current set of all drafted player names
        current_drafted: set[str] = set()
        jon_team = config.JON_TEAM_NAME
        jon_picks: list[tuple[str, str]] = []

        for team_name, picks in team_rosters.items():
            for pos, player_name in picks:
                # Resolve tracker short names (e.g. "Judge") to full names ("Aaron Judge")
                matched = self._find_player(player_name, position_hint=pos)
                resolved = _normalize_name(matched.name) if matched else _normalize_name(player_name)
                current_drafted.add(resolved)
                if team_name == jon_team:
                    jon_picks.append((pos, player_name))

        # Detect new picks (names that weren't in drafted_names before)
        new_names = current_drafted - self.drafted_names
        new_pick_details: list[dict] = []

        # Update state
        self.drafted_names = current_drafted
        # Count draft picks (not players): SP pairs count as 1 pick, not 2
        total_picks = 0
        for team_name, picks in team_rosters.items():
            sp_count = sum(1 for pos, _ in picks if pos == "SP")
            non_sp = len(picks) - sp_count
            sp_pairs = sp_count // 2  # each pair = 1 draft pick
            total_picks += non_sp + sp_pairs
        self.current_overall_pick = total_picks

        # Update Jon's roster from his column
        self.roster = Roster()
        for pos, player_name in jon_picks:
            player = self._find_player(player_name, position_hint=pos)
            if player:
                self.roster.add(player)

        # Log new picks
        if new_names:
            for name in new_names:
                # Identify which team drafted them
                for team_name, picks in team_rosters.items():
                    for pos, pname in picks:
                        if _normalize_name(pname) == name:
                            pick_info = {
                                "overall_pick": total_picks,
                                "name": pname,
                                "team": team_name,
                                "position": pos,
                                "is_mine": team_name == jon_team,
                            }
                            self.draft_log.append(pick_info)
                            new_pick_details.append(pick_info)
                            break

        return new_pick_details

    def run_once_grid(self, mcp_data: list) -> dict:
        """
        Process one poll cycle using the roster grid format.
        Takes the raw MCP gsheets_read response.
        """
        team_rosters = parse_tracker_response(mcp_data)
        new_pick_details = self.ingest_roster_grid(team_rosters)
        if new_pick_details:
            self.print_status()
            self.save_roster()

        return {
            "current_pick": self.current_overall_pick,
            "next_my_pick": self.next_my_pick(),
            "picks_until_mine": self.picks_until_mine(),
            "my_roster": self.roster.players,
            "open_slots": self.roster.open_slots(),
            "recommendations": self.get_recommendations(top_n=10),
            "new_picks_this_cycle": len(new_pick_details),
            "new_pick_details": new_pick_details,
            "team_rosters": team_rosters,
        }

    def _find_player(self, name: str, position_hint: Optional[str] = None) -> Optional[Player]:
        """Find a player in the ranked list by name (fuzzy).

        Args:
            name: Player name (possibly abbreviated, e.g. "Sanchez")
            position_hint: Roster slot from the tracker (e.g. "SP", "OF") to
                           disambiguate when multiple players share a last name.
        """
        needle = _normalize_name(name)

        def _matches_position(p: Player, hint: str) -> bool:
            if not hint:
                return True
            return hint in p.eligible_slots() or hint == p.player_type.upper()

        # Exact match (position-filtered first, then unfiltered)
        for p in self.all_players:
            if _normalize_name(p.name) == needle and _matches_position(p, position_hint):
                return p
        for p in self.all_players:
            if _normalize_name(p.name) == needle:
                return p

        # Partial match fallback: prefer position-matching candidates
        for p in self.all_players:
            if (needle in _normalize_name(p.name) or _normalize_name(p.name) in needle) \
                    and _matches_position(p, position_hint):
                return p
        for p in self.all_players:
            if needle in _normalize_name(p.name) or _normalize_name(p.name) in needle:
                return p

        # Abbreviation fallback: "J Ramirez" -> matches "Jose Ramirez"
        needle_parts = needle.split()
        if len(needle_parts) >= 2:
            for p in self.all_players:
                player_parts = _normalize_name(p.name).split()
                if len(player_parts) >= len(needle_parts) and all(
                    any(pp.startswith(np) for pp in player_parts)
                    for np in needle_parts
                ) and _matches_position(p, position_hint):
                    return p
            for p in self.all_players:
                player_parts = _normalize_name(p.name).split()
                if len(player_parts) >= len(needle_parts) and all(
                    any(pp.startswith(np) for pp in player_parts)
                    for np in needle_parts
                ):
                    return p
        return None

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------

    def get_recommendations(self, top_n: int = 10) -> list[tuple[Player, float]]:
        """
        Return the top N available non-SP players, weighted by positional need.
        Each entry is (player, adjusted_points) where adjusted_points is the
        scarcity-weighted score used for ranking.

        SP pairs are handled separately via get_sp_pair_recommendation().
        """
        open_slots = self.roster.open_slots()
        urgent_positions = set(open_slots)

        available = [
            p for p in self.all_players
            if _normalize_name(p.name) not in self.drafted_names
               and p.player_type != "sp"
               and any(s in urgent_positions for s in p.eligible_slots())
        ]

        def score(p: Player) -> float:
            base = p.projected_points
            # Apply the best scarcity multiplier across open non-DH slots
            best = max(
                (config.POSITION_SCARCITY.get(slot, 1.0)
                 for slot in p.eligible_slots()
                 if slot in urgent_positions and slot != "DH"),
                default=1.0,
            )
            return base * best

        scored = [(p, round(score(p), 1)) for p in available]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_n]

    def get_sp_pair_recommendation(self) -> Optional[dict]:
        """
        Return the best available SP pair with full context for evaluation.

        Returns None if no SP slots are open, otherwise a dict with:
          - sp1, sp2: the two Player objects
          - pair_rsar: combined RSAR
          - pair_team_pts: team-level SP points this pair contributes
            (marginal points added to the team's top-3 RSAR scoring)
          - total_sp_pts: total projected team SP points if Jon drafts
            the best available SPs for all remaining pair picks
          - pairs_remaining: how many SP pair picks Jon still needs
          - health: worst health status of the two
        """
        open_slots = self.roster.open_slots()
        sp_slots_open = open_slots.count("SP")
        if sp_slots_open < 2:
            return None

        available_sp = sorted(
            [p for p in self.all_players
             if _normalize_name(p.name) not in self.drafted_names
                and p.player_type == "sp"],
            key=lambda p: p.rsar,
            reverse=True,
        )
        if len(available_sp) < 2:
            return None

        sp1, sp2 = available_sp[0], available_sp[1]
        roster_rsars = [p.rsar for p in self.roster.starters()]
        pairs_needed = sp_slots_open // 2

        # Marginal value of THIS pair alone
        candidate_rsars = roster_rsars + [sp1.rsar, sp2.rsar]
        current_top3 = sorted(roster_rsars, reverse=True)[:config.SP_SCORING_COUNT]
        current_sum = sum(round(r) for r in current_top3)
        new_top3 = sorted(candidate_rsars, reverse=True)[:config.SP_SCORING_COUNT]
        new_sum = sum(round(r) for r in new_top3)
        pair_marginal = (new_sum - current_sum) * config.SP_RSAR_MULTIPLIER

        # Total SP value if Jon drafts best available for all remaining pairs
        all_rsars = list(roster_rsars)
        for k in range(0, min(len(available_sp), pairs_needed * 2), 2):
            all_rsars.append(available_sp[k].rsar)
            if k + 1 < len(available_sp):
                all_rsars.append(available_sp[k + 1].rsar)
        full_top3 = sorted(all_rsars, reverse=True)[:config.SP_SCORING_COUNT]
        full_sum = sum(round(r) for r in full_top3)
        total_sp_pts = (full_sum - current_sum) * config.SP_RSAR_MULTIPLIER

        return {
            "sp1": sp1,
            "sp2": sp2,
            "pair_rsar": round(sp1.rsar + sp2.rsar, 1),
            "pair_team_pts": round(pair_marginal, 1),
            "total_sp_pts": round(total_sp_pts, 1),
            "pairs_remaining": pairs_needed,
            "health": _combine_health(sp1, sp2),
        }

    def print_status(self):
        """Print current draft state to the terminal."""
        print("\n" + "="*60)
        print(f"  DRAFT STATUS — Pick #{self.current_overall_pick} just completed")
        print(f"  Jon's next pick: #{self.next_my_pick()} "
              f"({self.picks_until_mine()} picks away)")
        print("="*60)

        print(f"\n  JON'S ROSTER ({len(self.roster.players)} players):")
        for p in self.roster.players:
            print(f"    {p.name:<25} {p.position_str:<12} {p.projected_points:>6.1f} pts")

        open_slots = self.roster.open_slots()
        print(f"\n  OPEN SLOTS: {open_slots}")

        print(f"\n  TOP RECOMMENDATIONS:")
        recs = self.get_recommendations(top_n=10)
        for i, (p, adj) in enumerate(recs, 1):
            flag = " *** URGENT" if any(s in open_slots for s in p.eligible_slots()) else ""
            adj_str = f"  (adj {adj:.1f})" if adj != round(p.projected_points, 1) else ""
            print(f"    {i:2d}. {p.name:<25} {p.position_str:<12} "
                  f"{p.projected_points:>6.1f} pts{adj_str}  {p.health_status}{flag}")

        sp_rec = self.get_sp_pair_recommendation()
        if sp_rec:
            print(f"\n  BEST SP PAIR:")
            print(f"    {sp_rec['sp1'].name} + {sp_rec['sp2'].name}")
            print(f"    Combined RSAR: {sp_rec['pair_rsar']}  |  "
                  f"This pair adds: {sp_rec['pair_team_pts']} pts  |  "
                  f"Total SP value ({sp_rec['pairs_remaining']} pairs left): "
                  f"{sp_rec['total_sp_pts']} pts  |  {sp_rec['health']}")

        print()

    def save_roster(self):
        """Persist Jon's drafted roster to my_team.json."""
        data = {
            "updated": datetime.now().isoformat(),
            "pick_number": self.pick_number,
            "players": [
                {
                    "name": p.name,
                    "team": p.team,
                    "positions": p.positions,
                    "player_type": p.player_type,
                    "projected_points": p.projected_points,
                    "projected_stats": p.projected_stats,
                }
                for p in self.roster.players
            ]
        }
        with open(MY_TEAM_FILE, "w") as f:
            json.dump(data, f, indent=2)
        print(f"[draft] Roster saved to {MY_TEAM_FILE}")

    def run_once(self, sheet_rows: list[list]) -> dict:
        """
        Process one poll cycle. Returns state dict for the caller to write to Sheets.
        """
        new_picks = self.ingest_sheet_data(sheet_rows)
        if new_picks > 0:
            self.print_status()
            self.save_roster()

        return {
            "current_pick": self.current_overall_pick,
            "next_my_pick": self.next_my_pick(),
            "picks_until_mine": self.picks_until_mine(),
            "my_roster": self.roster.players,
            "open_slots": self.roster.open_slots(),
            "recommendations": self.get_recommendations(top_n=10),
            "sp_pair": self.get_sp_pair_recommendation(),
            "new_picks_this_cycle": new_picks,
        }


# ---------------------------------------------------------------------------
# Load existing roster (for post-draft season use)
# ---------------------------------------------------------------------------

def load_my_team() -> list[dict]:
    """Load Jon's roster from my_team.json."""
    if not MY_TEAM_FILE.exists():
        return []
    with open(MY_TEAM_FILE) as f:
        data = json.load(f)
    return data.get("players", [])


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _strip_pick_number(name: str) -> str:
    """Strip trailing pick number from tracker sheet names (e.g., 'Judge 1' -> 'Judge')."""
    import re
    return re.sub(r'\s+\d+$', '', name.strip())


def _normalize_name(name: str) -> str:
    """Lowercase, strip punctuation and accents for fuzzy matching."""
    import unicodedata
    # Decompose accented chars (é → e + combining accent), then drop combining marks
    nfkd = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return stripped.lower().strip().replace(".", "").replace("-", " ")


def _combine_health(sp1: Player, sp2: Player) -> str:
    """Return the worse health status of two players."""
    severity = ["healthy", "probable", "day-to-day", "questionable", "IL-10", "IL-60"]
    i1 = severity.index(sp1.health_status) if sp1.health_status in severity else 0
    i2 = severity.index(sp2.health_status) if sp2.health_status in severity else 0
    return severity[max(i1, i2)]
