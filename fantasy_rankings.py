"""
Fantasy draft rankings for 2026-27, built from 2025-26 stats.

Run nba_stats_2025_26.py first, then:
    python fantasy_rankings.py

Output: ./fantasy_rankings_2026_27.csv
Every value comes in pairs: the real per-game number, and the same number
normalized to 36 minutes (suffix _36).
    Z_TOTAL / RANK_9CAT  - 9-category value (PTS, REB, AST, STL, BLK, 3PM, FG%, FT%, TOV)
    FPTS / RANK_POINTS   - points-league value (ESPN default scoring)
    FPTS_POST_ASB_DIFF   - after the All-Star break vs. full season
"""

from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
DATA = HERE / "nba_2025_26"
OUT = HERE / "fantasy_rankings_2026_27.csv"

MIN_GP = 50
PER_MINUTES = 36
POOL_SIZE = 156  # 12 teams x 13 roster spots

COUNTING_CATS = ["PTS", "REB", "AST", "STL", "BLK", "FG3M"]
VOLUME_STATS = [*COUNTING_CATS, "TOV", "FGM", "FGA", "FTM", "FTA"]

# ESPN default points scoring
POINTS = {
    "PTS": 1, "FG3M": 1, "FGA": -1, "FGM": 2, "FTA": -1, "FTM": 1,
    "REB": 1, "AST": 2, "STL": 4, "BLK": 4, "TOV": -2,
}


def fantasy_points(df: pd.DataFrame) -> pd.Series:
    return sum(df[col] * w for col, w in POINTS.items())


def per_36(df: pd.DataFrame) -> pd.DataFrame:
    """Scale per-game volume stats to 36 minutes. Percentages are unaffected."""
    df = df.copy()
    df[VOLUME_STATS] = df[VOLUME_STATS].mul(PER_MINUTES / df["MIN"], axis=0)
    return df


def z_scores(df: pd.DataFrame, pool: pd.DataFrame) -> pd.DataFrame:
    """9-cat z-scores relative to a draftable pool. Percentages are weighted by volume."""
    z = pd.DataFrame(index=df.index)
    for cat in COUNTING_CATS:
        z[f"Z_{cat}"] = (df[cat] - pool[cat].mean()) / pool[cat].std()
    z["Z_TOV"] = -(df["TOV"] - pool["TOV"].mean()) / pool["TOV"].std()

    for pct, made, att in [("FG", "FGM", "FGA"), ("FT", "FTM", "FTA")]:
        league_pct = pool[made].sum() / pool[att].sum()
        impact = (df[made] - league_pct * df[att])
        pool_impact = pool[made] - league_pct * pool[att]
        z[f"Z_{pct}_PCT"] = (impact - pool_impact.mean()) / pool_impact.std()

    z["Z_TOTAL"] = z.sum(axis=1)
    return z


def fantasy_values(stats: pd.DataFrame, post: pd.DataFrame) -> pd.DataFrame:
    """Z-scores, fantasy points and ranks for one version of the stats (per game or per 36)."""
    # Pick the pool iteratively: rank everyone, take the top N, re-rank against them
    pool = stats
    for _ in range(3):
        z = z_scores(stats, pool)
        pool = stats.loc[z["Z_TOTAL"].nlargest(POOL_SIZE).index]
    vals = stats[VOLUME_STATS].join(z_scores(stats, pool))

    vals["FPTS"] = fantasy_points(stats)
    post_fpts = fantasy_points(post).set_axis(post["PLAYER_ID"])
    vals["FPTS_POST_ASB"] = stats["PLAYER_ID"].map(post_fpts)
    vals["FPTS_POST_ASB_DIFF"] = vals["FPTS_POST_ASB"] - vals["FPTS"]

    vals["RANK_9CAT"] = vals["Z_TOTAL"].rank(ascending=False).astype(int)
    vals["RANK_POINTS"] = vals["FPTS"].rank(ascending=False).astype(int)
    return vals


def main() -> None:
    stats = pd.read_csv(DATA / "players_base_pergame_regular.csv")
    stats = stats[stats["GP"] >= MIN_GP].reset_index(drop=True)
    post = pd.read_csv(DATA / "players_base_pergame_post_allstar.csv")

    real = fantasy_values(stats, post)
    norm = fantasy_values(per_36(stats), per_36(post)).add_suffix("_36")

    info = stats[["PLAYER_ID", "PLAYER_NAME", "AGE", "TEAM_ABBREVIATION",
                  "GP", "MIN", "FG_PCT", "FT_PCT"]]
    post_gp = post.set_index("PLAYER_ID")["GP"]
    info = info.assign(GP_POST_ASB=info["PLAYER_ID"].map(post_gp))

    # Current team and position for 2026-27
    roster = pd.read_csv(DATA / "player_index_2026_27.csv")
    roster = roster[["PERSON_ID", "TEAM_ABBREVIATION", "POSITION"]].rename(columns={
        "PERSON_ID": "PLAYER_ID", "TEAM_ABBREVIATION": "TEAM_2026_27"})
    out = pd.concat([info, real, norm], axis=1).merge(roster, on="PLAYER_ID", how="left")
    out["TEAM_CHANGED"] = out["TEAM_2026_27"].notna() & (
        out["TEAM_2026_27"] != out["TEAM_ABBREVIATION"])

    paired = [
        "RANK_9CAT", "RANK_POINTS", "Z_TOTAL", "FPTS",
        "PTS", "REB", "AST", "STL", "BLK", "FG3M", "TOV",
        "Z_PTS", "Z_REB", "Z_AST", "Z_STL", "Z_BLK", "Z_FG3M", "Z_FG_PCT",
        "Z_FT_PCT", "Z_TOV", "FPTS_POST_ASB", "FPTS_POST_ASB_DIFF",
    ]
    cols = [
        "PLAYER_NAME", "POSITION", "AGE", "TEAM_ABBREVIATION", "TEAM_2026_27",
        "TEAM_CHANGED", "GP", "MIN", "GP_POST_ASB", "FG_PCT", "FT_PCT",
        *[c for col in paired for c in (col, f"{col}_36")],
    ]
    out = out[cols].sort_values("RANK_9CAT").round(3)
    out.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"Saved {OUT.name} ({len(out)} players)\n")

    view = ["PLAYER_NAME", "TEAM_2026_27", "MIN", "Z_TOTAL", "Z_TOTAL_36", "FPTS", "FPTS_36"]
    print("Top 15 - 9-cat (per game | per 36)")
    print(out[["RANK_9CAT", "RANK_9CAT_36", *view]].head(15).to_string(index=False))
    print("\nTop 15 - points (per game | per 36)")
    print(out.sort_values("RANK_POINTS")[["RANK_POINTS", "RANK_POINTS_36", *view]]
          .head(15).to_string(index=False))


if __name__ == "__main__":
    main()
