"""
Pull each player's fantasy positions (PG / SG / SF / PF / C) from ESPN Fantasy into
./nba_2026_27/positions_espn.csv.

    python positions.py

A player is listed under every position he is eligible for in ESPN fantasy lineups (e.g. "PG/SG").
Eligibility grows during the season, so the daily run and the GitHub workflow refresh it.
Needs only pandas; a failed pull keeps the previous file.
"""

import json
import urllib.request
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
OUT = HERE / "nba_2026_27"
SEASON = 2027  # ESPN names a season by the year it ends: 2027 = 2026-27
URL = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{SEASON}/players?scoringPeriodId=0&view=players_wl"
SLOTS = {0: "PG", 1: "SG", 2: "SF", 3: "PF", 4: "C"}  # ESPN lineup slot ids; 5 = G, 6 = F and the rest are combined slots


def pull_positions() -> str:
    try:
        req = urllib.request.Request(URL, headers={
            "User-Agent": "Mozilla/5.0",
            "X-Fantasy-Filter": json.dumps({"filterActive": {"value": True}}),
        })
        data = json.load(urllib.request.urlopen(req, timeout=60))
    except Exception as e:  # noqa: BLE001
        return f"Positions: pull failed ({e}), kept the previous list"
    rows = []
    for p in data:
        pos = [SLOTS[s] for s in sorted(p.get("eligibleSlots", [])) if s in SLOTS]
        if pos:
            rows.append({"PLAYER_NAME": p["fullName"], "POSITIONS": "/".join(pos)})
    if not rows:
        return "Positions: ESPN returned no players, kept the previous list"
    OUT.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT / "positions_espn.csv", index=False, encoding="utf-8-sig")
    return f"Positions: {len(rows)} players"


if __name__ == "__main__":
    print(pull_positions())
