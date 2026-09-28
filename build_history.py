"""
build_history.py — Pull the inputs playing_time.py needs from the MLB Stats API.

Writes data/history/{games,il_placements,birthdates}.json:
  games.json          per season+group: games, starts, AB, PA, IP for every player
  il_placements.json  every "placed on the injured list" transaction
  birthdates.json     birthDate + primary position, keyed by MLB id

Run once each off-season (takes a couple of minutes):
    python3 build_history.py --seasons 2024 2025 2026
"""
import argparse, json, time, urllib.request
from pathlib import Path

OUT = Path(__file__).parent / "data" / "history"


def get(url, tries=3):
    err = None
    for _ in range(tries):
        try:
            return json.load(urllib.request.urlopen(url, timeout=90))
        except Exception as e:
            err = e
            time.sleep(2)
    raise err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", nargs="+", type=int, default=[2023, 2024, 2025, 2026])
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    games = {}
    for season in args.seasons:
        for g in ("hitting", "pitching"):
            r = get(f"https://statsapi.mlb.com/api/v1/stats?stats=season&group={g}&season={season}"
                    f"&sportIds=1&limit=4000&gameType=R&playerPool=ALL")
            rows = r["stats"][0]["splits"] if r.get("stats") else []
            games[f"{season}_{g}"] = [{
                "id": s["player"]["id"], "name": s["player"]["fullName"],
                "pos": s.get("position", {}).get("abbreviation"), "team": s.get("team", {}).get("abbreviation"),
                "G": s["stat"].get("gamesPlayed"), "GS": s["stat"].get("gamesStarted"),
                "AB": s["stat"].get("atBats"), "PA": s["stat"].get("plateAppearances"),
                "IP": s["stat"].get("inningsPitched")} for s in rows]
            print(season, g, len(rows))
    (OUT / "games.json").write_text(json.dumps(games))

    il = []
    for y in args.seasons:
        r = get(f"https://statsapi.mlb.com/api/v1/transactions?startDate={y}-01-01&endDate={y}-12-31&sportId=1")
        for t in r.get("transactions", []):
            d = (t.get("description") or "").lower()
            if "placed" in d and "injured list" in d:
                il.append({"year": y, "date": t.get("date"), "pid": t.get("person", {}).get("id"),
                           "name": t.get("person", {}).get("fullName"), "desc": t.get("description")})
        print(y, "IL placements so far", len(il))
    (OUT / "il_placements.json").write_text(json.dumps(il))

    ids = sorted({p["id"] for rows in games.values() for p in rows})
    bd = {}
    for i in range(0, len(ids), 100):
        r = get("https://statsapi.mlb.com/api/v1/people?personIds=" + ",".join(map(str, ids[i:i + 100])))
        for p in r.get("people", []):
            bd[p["id"]] = {"name": p.get("fullName"), "birthDate": p.get("birthDate"),
                           "mlbDebutDate": p.get("mlbDebutDate"),
                           "pos": p.get("primaryPosition", {}).get("abbreviation")}
    (OUT / "birthdates.json").write_text(json.dumps(bd))
    print("people", len(bd))


if __name__ == "__main__":
    main()
