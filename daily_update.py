"""
Daily pull of 2026-27 game logs: every player's box score from every game played so far.

    python daily_update.py

Writes ./nba_2026_27/ :
  game_logs_preseason.csv   one row per player per game (preseason)
  game_logs_regular.csv     same for the regular season (empty until opening night)
  injuries.csv              ESPN injury list (status, injury, expected return)
  last_update.txt           when the pull ran and the latest game date in each file

Each run re-downloads the whole season so far, so a missed day fills itself in and nothing
is ever counted twice. Source: stats.nba.com (the same official feed as the rest of the project).
"""

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from nba_api.stats.endpoints import playergamelogs

from nba_stats_2025_26 import fetch

HERE = Path(__file__).parent
OUT = HERE / "nba_2026_27"
SEASON = "2026-27"
SEASON_TYPES = {"Pre Season": "preseason", "Regular Season": "regular"}
KEEP = ["SEASON_YEAR", "PLAYER_ID", "PLAYER_NAME", "TEAM_ID", "TEAM_ABBREVIATION", "GAME_ID", "GAME_DATE",
        "MATCHUP", "WL", "MIN", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA", "OREB", "DREB", "REB", "AST",
        "TOV", "STL", "BLK", "PF", "PTS", "PLUS_MINUS"]


def pull(season_type: str) -> pd.DataFrame:
    df = fetch(playergamelogs.PlayerGameLogs, season_nullable=SEASON, season_type_nullable=season_type)
    if df.empty:
        return pd.DataFrame(columns=KEEP)
    df = df[KEEP].copy()
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"]).dt.date
    return df.sort_values(["GAME_DATE", "GAME_ID", "TEAM_ABBREVIATION", "PLAYER_NAME"])


def pull_injuries() -> str:
    """ESPN's injury list: status, fantasy status (OUT / OFS / GTD), injury and expected return.
    A failure keeps yesterday's file, so the dashboard never loses its injury badges."""
    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = json.load(urllib.request.urlopen(req, timeout=60))
    except Exception as e:  # noqa: BLE001
        return f"Injuries: pull failed ({e}), kept the previous list"
    rows = []
    for team in data.get("injuries", []):
        for i in team.get("injuries", []):
            d = i.get("details") or {}
            rows.append({
                "PLAYER_NAME": i["athlete"]["displayName"],
                "TEAM": team.get("displayName"),
                "STATUS": i.get("status"),
                "FANTASY_STATUS": (d.get("fantasyStatus") or {}).get("abbreviation"),
                "INJURY": " ".join(x for x in [d.get("type"), d.get("detail")] if x and x != "Not Specified"),
                "RETURN_DATE": d.get("returnDate"),
                "COMMENT": i.get("shortComment"),
                "UPDATED": i.get("date"),
            })
    pd.DataFrame(rows).to_csv(OUT / "injuries.csv", index=False, encoding="utf-8-sig")
    return f"Injuries: {len(rows)} players listed"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    lines = [f"Pulled {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC"]
    msg = pull_injuries()
    print(msg)
    lines.append(msg)
    for season_type, tag in SEASON_TYPES.items():
        df = pull(season_type)
        path = OUT / f"game_logs_{tag}.csv"
        df.to_csv(path, index=False, encoding="utf-8-sig")
        if df.empty:
            msg = f"{season_type}: no games yet"
        else:
            last = df["GAME_DATE"].max()
            msg = (f"{season_type}: {df['GAME_ID'].nunique()} games, {len(df)} player lines, "
                   f"{df['GAME_DATE'].min()} to {last} "
                   f"({df.loc[df['GAME_DATE'] == last, 'GAME_ID'].nunique()} games on {last})")
        print(msg)
        lines.append(msg)
    (OUT / "last_update.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
