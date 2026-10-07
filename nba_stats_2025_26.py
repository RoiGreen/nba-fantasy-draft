"""
Pull official NBA stats (stats.nba.com) for the 2025-26 season and save to CSV,
plus 2026-27 rosters and schedule for fantasy draft prep.

Setup:
    pip install nba_api pandas

Run:
    python nba_stats_2025_26.py

Output folder: ./nba_2025_26/ (next to this script)
"""

import time
from pathlib import Path

import pandas as pd
from nba_api.stats.endpoints import (
    leaguedashplayerbiostats,
    leaguedashplayerstats,
    leaguedashteamstats,
    leaguehustlestatsplayer,
    leaguestandingsv3,
    playergamelogs,
    playerindex,
    scheduleleaguev2,
)

SEASON = "2025-26"
NEXT_SEASON = "2026-27"
# Earlier seasons, for players who missed most of SEASON injured
PREVIOUS_SEASONS = ["2024-25", "2023-24"]
SEASON_TYPES = ["Regular Season", "Playoffs"]
OUT = Path(__file__).parent / "nba_2025_26"
OUT.mkdir(exist_ok=True)

# stats.nba.com is slow and rate-limits aggressively
TIMEOUT = 60
PAUSE = 1.5
RETRIES = 3


def fetch(endpoint_cls, index: int = 0, **kwargs) -> pd.DataFrame:
    """Call an nba_api endpoint with retries and return one result set."""
    for attempt in range(1, RETRIES + 1):
        try:
            df = endpoint_cls(timeout=TIMEOUT, **kwargs).get_data_frames()[index]
            time.sleep(PAUSE)
            return df
        except Exception as e:  # noqa: BLE001
            print(f"  attempt {attempt} failed: {e}")
            time.sleep(PAUSE * attempt * 2)
    raise RuntimeError(f"{endpoint_cls.__name__} failed after {RETRIES} attempts")


def save(df: pd.DataFrame, name: str) -> None:
    path = OUT / f"{name}.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"  saved {path.name}  ({len(df)} rows, {len(df.columns)} cols)")


def fetch_previous_seasons() -> None:
    for season in PREVIOUS_SEASONS:
        tag = season.replace("-", "_")
        for measure in ["Base", "Advanced"]:
            print(f"Players {measure} PerGame {season}")
            df = fetch(
                leaguedashplayerstats.LeagueDashPlayerStats,
                season=season,
                per_mode_detailed="PerGame",
                measure_type_detailed_defense=measure,
            )
            save(df, f"players_{measure.lower()}_pergame_regular_{tag}")


def main() -> None:
    for st in SEASON_TYPES:
        tag = "regular" if st == "Regular Season" else "playoffs"
        print(f"\n=== {SEASON} {st} ===")

        # Player stats: per-game and totals, base + advanced
        for per_mode in ["PerGame", "Totals"]:
            for measure in ["Base", "Advanced"]:
                print(f"Players {measure} {per_mode}")
                df = fetch(
                    leaguedashplayerstats.LeagueDashPlayerStats,
                    season=SEASON,
                    season_type_all_star=st,
                    per_mode_detailed=per_mode,
                    measure_type_detailed_defense=measure,
                )
                save(df, f"players_{measure.lower()}_{per_mode.lower()}_{tag}")

        # Team stats: per-game, base + advanced
        for measure in ["Base", "Advanced"]:
            print(f"Teams {measure} PerGame")
            df = fetch(
                leaguedashteamstats.LeagueDashTeamStats,
                season=SEASON,
                season_type_all_star=st,
                per_mode_detailed="PerGame",
                measure_type_detailed_defense=measure,
            )
            save(df, f"teams_{measure.lower()}_pergame_{tag}")

        # Every player's game-by-game box score
        print("Player game logs")
        df = fetch(
            playergamelogs.PlayerGameLogs,
            season_nullable=SEASON,
            season_type_nullable=st,
        )
        save(df, f"player_game_logs_{tag}")

    print(f"\n=== {SEASON} regular season extras ===")

    # Usage share, misc (2nd-chance, fast break), scoring mix
    for measure in ["Usage", "Misc", "Scoring"]:
        print(f"Players {measure} PerGame")
        df = fetch(
            leaguedashplayerstats.LeagueDashPlayerStats,
            season=SEASON,
            per_mode_detailed="PerGame",
            measure_type_detailed_defense=measure,
        )
        save(df, f"players_{measure.lower()}_pergame_regular")

    # Late-season form
    print("Players Base PerGame post All-Star")
    df = fetch(
        leaguedashplayerstats.LeagueDashPlayerStats,
        season=SEASON,
        per_mode_detailed="PerGame",
        season_segment_nullable="Post All-Star",
    )
    save(df, "players_base_pergame_post_allstar")

    print("Teams Opponent PerGame")
    df = fetch(
        leaguedashteamstats.LeagueDashTeamStats,
        season=SEASON,
        per_mode_detailed="PerGame",
        measure_type_detailed_defense="Opponent",
    )
    save(df, "teams_opponent_pergame_regular")

    print("Player bio (age, height, draft)")
    df = fetch(leaguedashplayerbiostats.LeagueDashPlayerBioStats, season=SEASON)
    save(df, "players_bio")

    print("Player hustle (deflections, charges, loose balls)")
    df = fetch(leaguehustlestatsplayer.LeagueHustleStatsPlayer, season=SEASON)
    save(df, "players_hustle_regular")

    print("\nStandings")
    df = fetch(leaguestandingsv3.LeagueStandingsV3, season=SEASON)
    save(df, "standings")

    print("\n=== Previous seasons ===")
    fetch_previous_seasons()

    print(f"\n=== {NEXT_SEASON} ===")

    # Current rosters and positions (reflects off-season moves)
    print("Player index / rosters")
    df = fetch(playerindex.PlayerIndex, season=NEXT_SEASON)
    save(df, f"player_index_{NEXT_SEASON.replace('-', '_')}")

    print("Schedule")
    df = fetch(scheduleleaguev2.ScheduleLeagueV2, season=NEXT_SEASON)
    save(df, f"schedule_{NEXT_SEASON.replace('-', '_')}")

    print(f"\nDone. Files are in {OUT}")


if __name__ == "__main__":
    main()
