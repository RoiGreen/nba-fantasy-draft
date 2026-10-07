"""
Download the data the rookie projection model trains on.

    python fetch_rookie_history.py

- NBA rookie seasons 2015-16 .. 2025-26 (stats.nba.com, per game) with draft position
- College player seasons 2015 .. 2026 from barttorvik.com (every D-I player, includes NBA draft pick)
- Team records and every player's season minutes 2014-15 .. 2025-26, plus positions

Output: ./nba_2025_26/rookies/ and ./nba_2025_26/college/
"""

import time
import urllib.request
from pathlib import Path

import pandas as pd
from nba_api.stats.endpoints import (
    leaguedashplayerbiostats,
    leaguedashplayerstats,
    leaguedashteamstats,
    playerindex,
)

from nba_stats_2025_26 import fetch

HERE = Path(__file__).parent
ROOKIES = HERE / "nba_2025_26" / "rookies"
COLLEGE = HERE / "nba_2025_26" / "college"
FIRST, LAST = 2015, 2025  # draft years


def season_str(draft_year: int) -> str:
    return f"{draft_year}-{(draft_year + 1) % 100:02d}"


def fetch_rookies() -> None:
    ROOKIES.mkdir(parents=True, exist_ok=True)
    for y in range(FIRST, LAST + 1):
        season = season_str(y)
        path = ROOKIES / f"rookies_{season.replace('-', '_')}.csv"
        if path.exists():
            continue
        print(f"Rookies {season}")
        stats = fetch(leaguedashplayerstats.LeagueDashPlayerStats, season=season,
                      per_mode_detailed="PerGame", player_experience_nullable="Rookie")
        bio = fetch(leaguedashplayerbiostats.LeagueDashPlayerBioStats, season=season)
        bio = bio[["PLAYER_ID", "PLAYER_HEIGHT_INCHES", "DRAFT_YEAR", "DRAFT_NUMBER", "COLLEGE", "COUNTRY"]]
        df = stats.merge(bio, on="PLAYER_ID", how="left")
        df["SEASON"] = season
        df.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"  saved {path.name} ({len(df)} rows)")


def fetch_team_context() -> None:
    """Team records and every player's minutes per season, for team strength and open minutes."""
    ROOKIES.mkdir(parents=True, exist_ok=True)
    records = ROOKIES / "team_records.csv"
    if not records.exists():
        frames = []
        for y in range(FIRST - 1, LAST + 1):
            season = season_str(y)
            d = fetch(leaguedashteamstats.LeagueDashTeamStats, season=season)[["TEAM_ID", "TEAM_NAME", "W_PCT"]]
            d["SEASON"] = season
            frames.append(d)
        pd.concat(frames).to_csv(records, index=False, encoding="utf-8-sig")
        print(f"  saved {records.name}")
    for y in range(FIRST - 1, LAST + 1):
        season = season_str(y)
        path = ROOKIES / f"all_players_{season.replace('-', '_')}.csv"
        if path.exists():
            continue
        d = fetch(leaguedashplayerstats.LeagueDashPlayerStats, season=season, per_mode_detailed="Totals")
        d[["PLAYER_ID", "PLAYER_NAME", "TEAM_ID", "GP", "MIN"]].assign(SEASON=season).to_csv(
            path, index=False, encoding="utf-8-sig")
        print(f"  saved {path.name}")
    positions = ROOKIES / "positions.csv"
    if not positions.exists():
        d = fetch(playerindex.PlayerIndex, season=season_str(LAST), historical_nullable="1")
        d[["PERSON_ID", "POSITION"]].to_csv(positions, index=False, encoding="utf-8-sig")
        print(f"  saved {positions.name} ({len(d)} players)")


def fetch_college() -> None:
    COLLEGE.mkdir(parents=True, exist_ok=True)
    for y in range(FIRST, LAST + 2):
        path = COLLEGE / f"barttorvik_{y}.csv"
        if path.exists():
            continue
        req = urllib.request.Request(f"https://barttorvik.com/getadvstats.php?year={y}&csv=1",
                                     headers={"User-Agent": "Mozilla/5.0"})
        path.write_bytes(urllib.request.urlopen(req, timeout=60).read())
        print(f"  saved {path.name}")
        time.sleep(1)


if __name__ == "__main__":
    fetch_college()
    fetch_rookies()
    fetch_team_context()
