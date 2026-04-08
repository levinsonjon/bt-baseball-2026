"""
config.py — League settings, scoring formula, and position eligibility.
Based on BT Baseball Pool 2026 rules (BBRULES_2026.doc).
"""

# ---------------------------------------------------------------------------
# LEAGUE SETTINGS
# ---------------------------------------------------------------------------

LEAGUE_NAME = "BT Baseball Pool 2026"
LEAGUE_SIZE = 9
DRAFT_TYPE = "snake"
DRAFT_PICK = 9           # 9th pick (last in round 1, first in round 2, etc.)

# ---------------------------------------------------------------------------
# SCORING FORMULA — BT Baseball Pool 2026
#
# HITTERS (per player, rounded to nearest point before summing):
#   BA × 1000  +  HR  +  RBI  +  R  +  SB
#   Minimum 300 AB rule: if a player has fewer than 300 AB, the shortfall
#   is added to their AB (without adding hits), reducing their effective BA.
#
# STARTING PITCHERS (6 drafted in pairs, only top 3 count for scoring):
#   RSAR = (1.2 × MLB_AVG_ERA − ERA) × (IP / 9)
#   Team SP score = (RSAR_1 + RSAR_2 + RSAR_3) × 3.5  [top 3 starters]
#   Each RSAR rounded to nearest point before summing.
#   Penalty: if IP/G < 3.5, player scores 0 (reliever-as-starter prevention).
#
# RELIEF PITCHER (1 drafted):
#   Score = 5 × (W + SV)
# ---------------------------------------------------------------------------

# MLB average ERA used in RSAR formula. Update annually.
# 2024 MLB ERA was ~4.25; using 4.20 as 2026 projection baseline.
MLB_AVG_ERA = 4.20

# RSAR multiplier (applied to sum of top-3 starters)
SP_RSAR_MULTIPLIER = 3.5

# SP minimum IP/G to avoid zero-score penalty (reliever rule)
SP_MIN_IP_PER_GAME = 3.5

# Minimum at-bats per hitter position before BA penalty kicks in
HITTER_MIN_AB = 300

# Relief pitcher scoring
RP_WIN_SAVE_MULTIPLIER = 5

# Simple per-stat weights for hitters (BA handled separately in players.py)
HITTER_SCORING = {
    "HR":  1.0,
    "RBI": 1.0,
    "R":   1.0,
    "SB":  1.0,
    # BA is NOT a simple multiplier — it's computed per-player (BA × 1000)
    # with the 300 AB minimum rule applied. See players.py: compute_projected_points()
}

# SP scoring is formula-based (RSAR) for full-season projections.
# See players.py: compute_projected_points() for the implementation.
# These keys tell the scraper which stats to collect for SPs.
SP_STAT_KEYS = ["ERA", "IP", "G", "GS"]

# RP scoring keys
RP_STAT_KEYS = ["W", "SV"]

# ---------------------------------------------------------------------------
# ROSTER SLOTS — 16-man roster, no bench
# ---------------------------------------------------------------------------

ROSTER_SLOTS = {
    "C":  1,
    "1B": 1,
    "2B": 1,
    "3B": 1,
    "SS": 1,
    "OF": 3,   # any combo of LF, CF, RF
    "SP": 6,   # drafted in pairs; only top 3 count for scoring
    "RP": 1,
    "DH": 1,   # last round only; any player eligible; separate draw for order
}

# Slots counted for draft tracking (all 16)
ACTIVE_SLOTS = dict(ROSTER_SLOTS)

# Number of starters that actually score
SP_SCORING_COUNT = 3

# ---------------------------------------------------------------------------
# POSITION ELIGIBILITY
# Which roster slot(s) each position tag can fill.
# Per rules: all players are eligible for DH regardless of assigned position,
# but DH is only drafted in the final round.
# ---------------------------------------------------------------------------

POSITION_ELIGIBILITY = {
    "C":   ["C", "DH"],
    "1B":  ["1B", "DH"],
    "2B":  ["2B", "DH"],
    "3B":  ["3B", "DH"],
    "SS":  ["SS", "DH"],
    "LF":  ["OF", "DH"],
    "CF":  ["OF", "DH"],
    "RF":  ["OF", "DH"],
    "OF":  ["OF", "DH"],   # generic OF tag
    "DH":  ["DH"],
    "SP":  ["SP", "DH"],   # SP can also be drafted as DH (Ohtani rule)
    "RP":  ["RP"],
}

# ---------------------------------------------------------------------------
# POSITION SCARCITY WEIGHTS
# Used by draft.py to boost recommendations when Jon needs a specific position.
# ---------------------------------------------------------------------------

POSITION_SCARCITY = {
    "C":   1.10,
    "SS":  1.05,
    "2B":  1.05,
    "3B":  1.05,
    "1B":  0.95,
    "OF":  1.00,
    "SP":  1.00,
    "RP":  1.05,
    "DH":  0.50,
}

# ---------------------------------------------------------------------------
# PLAYING TIME DISCOUNT FACTORS
# Applied to projected points when a player has injury/uncertainty flags.
# ---------------------------------------------------------------------------

PLAYING_TIME_DISCOUNTS = {
    "healthy":      1.0,
    "day-to-day":   0.98,
    "probable":     0.99,
    "questionable": 0.96,
    "IL-10":        0.85,
    "IL-60":        0.45,
    "IL-season":    0.0,
    "unknown":      0.90,
}

# ---------------------------------------------------------------------------
# GOOGLE SHEETS
# ---------------------------------------------------------------------------

# Rankings/projections sheet (maintained by push_to_sheets.py)
GOOGLE_SHEET_ID = "1WJ_DovsnvpRxUccDS4FPyxMBvIt3l8Dpl8Y3mKEmb1w"

SHEET_RANKINGS    = "Rankings"
SHEET_BY_POS      = "By Position"

# ---------------------------------------------------------------------------
# DRAFT TRACKER SHEET (official league draft board)
# Roster grid format: positions in column A, team owners in columns B-J.
# Player names are filled in during the draft.
# ---------------------------------------------------------------------------

DRAFT_TRACKER_SHEET_ID = "1BMZk1b3IFyek48tngRlK_FpqMGErgKpuFjEe7jwjQcE"
DRAFT_TRACKER_TAB = "Sheet1"
JON_TEAM_NAME = "Levinsons"

# Header row (1-indexed) containing team owner names
TRACKER_HEADER_ROW = 3

# Position label normalization (column A values -> roster slot keys)
TRACKER_POSITION_MAP = {
    "Catcher": "C",
    "C":       "C",
    "1B":      "1B",
    "2B":      "2B",
    "3B":      "3B",
    "SS":      "SS",
    "OF":      "OF",
    "RP":      "RP",
    "SP":      "SP",
    "DH":      "DH",
}

# ---------------------------------------------------------------------------
# DAILY REPORT
# ---------------------------------------------------------------------------

# TODO: Jon's personal email address
REPORT_EMAIL = "levinson.jon@gmail.com"
REPORT_EMAIL_CC = ["levinsonlgs@gmail.com"]
REPORT_SUBJECT_PREFIX = "Fantasy Baseball Daily"
