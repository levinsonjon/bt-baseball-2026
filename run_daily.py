"""
run_daily.py — Entry point: run the daily fantasy baseball report.

Fetches prior day stats and news for every player on Jon's roster,
computes team points, and emails the report to Jon's personal Gmail.

Usage:
    python run_daily.py                      # report for yesterday
    python run_daily.py --date 2026-04-05    # report for a specific date
    python run_daily.py --preview            # build report but don't send email

NOTE: Sending email requires the mcp__gmail-personal__send_email MCP tool,
available inside Claude Code sessions. Web search also requires Claude's
WebSearch tool. This script is designed to be called from Claude Code,
which will handle the MCP/search calls and pass results back to this module.
"""

import sys
import argparse
from datetime import date, timedelta, datetime
from pathlib import Path

from draft import load_my_team
from daily_report import (
    DayResult,
    build_box_score_query,
    build_news_query,
    build_injury_query,
    parse_box_score_from_search,
    load_season_stats,
    update_season_stats,
    save_season_stats,
    compute_ytd_points,
    compute_pace_points,
    build_html_email,
    build_subject,
)
import config


def main():
    parser = argparse.ArgumentParser(description="Daily fantasy baseball report")
    parser.add_argument("--date", type=str, help="Report date (YYYY-MM-DD), default: yesterday")
    parser.add_argument("--preview", action="store_true", help="Build report without sending")
    args = parser.parse_args()

    if args.date:
        report_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        report_date = date.today() - timedelta(days=1)

    print(f"\n{'='*60}")
    print(f"  FANTASY BASEBALL DAILY REPORT — {report_date.strftime('%B %-d, %Y')}")
    print(f"{'='*60}\n")

    # Load roster
    roster = load_my_team()
    if not roster:
        print("ERROR: No roster found. Has the draft been completed?")
        print(f"Expected roster at: data/my_team.json")
        sys.exit(1)

    print(f"[daily] Roster loaded: {len(roster)} players")

    # Generate search queries for each player
    date_str = report_date.strftime("%B %-d %Y")
    queries = []
    for player in roster:
        name = player["name"]
        ptype = player["player_type"]
        queries.append({
            "player_name": name,
            "player_type": ptype,
            "box_score_query": build_box_score_query(name, date_str),
            "news_query": build_news_query(name, date_str),
            "injury_query": build_injury_query(name),
        })

    print(f"\n[daily] Search queries to run (use Claude's WebSearch tool for each):")
    for q in queries:
        print(f"  [{q['player_type']}] {q['player_name']}")
        print(f"    Box score: {q['box_score_query']}")
        print(f"    News:      {q['news_query']}")

    if args.preview:
        print("\n[preview] Skipping search execution and email send.")
        print("Run from Claude Code session to execute searches and send email.")
        return

    print("\n[daily] This script needs to be run from within a Claude Code session")
    print("to execute web searches and send email via MCP tools.")
    print("\nClaude Code will:")
    print("  1. Run WebSearch for each player's box score and news")
    print("  2. Call parse_box_score_from_search() with each result")
    print("  3. Build the HTML email via build_html_email()")
    print("  4. Send via mcp__gmail-personal__send_email")


def generate_report_from_search_results(
    report_date: date,
    search_results: list[dict],
) -> dict:
    """
    Build the full report from pre-fetched search results.

    Call this from Claude Code after running WebSearch for each player.

    Args:
        report_date: The date being reported on
        search_results: List of dicts, one per player:
            {
                "player_name": str,
                "player_type": str,  # "hitter" or "pitcher"
                "box_score_text": str,   # raw WebSearch result text
                "news_text": str,        # raw WebSearch result text
                "injury_text": str,      # raw WebSearch result text
            }

    Returns:
        {
            "html": str,           # full HTML email body
            "subject": str,        # email subject line
            "day_results": list,   # DayResult objects
        }
    """
    day_results = []

    for sr in search_results:
        result = parse_box_score_from_search(
            player_name=sr["player_name"],
            player_type=sr["player_type"],
            search_text=sr.get("box_score_text", ""),
        )
        result.news = _summarize_news(sr.get("news_text", ""))
        result.injury_note, result.injury_flag = _parse_injury(sr.get("injury_text", ""))
        day_results.append(result)

    # Update cumulative season stats
    season_stats = load_season_stats()
    season_stats = update_season_stats(season_stats, day_results)
    save_season_stats(season_stats)

    html = build_html_email(report_date, day_results, season_stats)
    subject = build_subject(report_date, day_results)

    print(f"\n[daily] Report built: {len(day_results)} players")
    print(f"[daily] Subject: {subject}")
    total_pts = sum(r.fantasy_points for r in day_results)
    print(f"[daily] Team points today: {total_pts:+.1f}")

    return {
        "html": html,
        "subject": subject,
        "day_results": day_results,
        "to": config.REPORT_EMAIL,
        "cc": config.REPORT_EMAIL_CC,
    }


def _summarize_news(news_text: str) -> str:
    """
    Extract a brief 2-3 sentence summary from raw search snippet text.
    In practice, Claude Code handles the summarization during WebSearch processing.
    This is a fallback plain-text truncation.
    """
    if not news_text:
        return ""
    sentences = news_text.replace("\n", " ").split(". ")
    return ". ".join(sentences[:3]).strip() + "." if sentences else ""


def _parse_injury(injury_text: str) -> tuple[str, bool]:
    """
    Check injury search text for red-flag terms.
    Returns (injury_note, is_injured).
    """
    if not injury_text:
        return "", False

    text = injury_text.lower()
    injury_keywords = [
        "placed on il", "injured list", "day-to-day", "sprain", "strain",
        "fracture", "surgery", "shut down", "out indefinitely", "torn",
        "hamstring", "oblique", "elbow", "shoulder", "knee",
    ]
    for kw in injury_keywords:
        if kw in text:
            # Take first 200 chars of the injury section as the note
            note = injury_text[:200].strip()
            return note, True

    return "", False


if __name__ == "__main__":
    main()
