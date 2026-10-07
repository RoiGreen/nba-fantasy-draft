"""
How each team's fantasy production is split between key players and the rotation.

    python team_distribution.py

Fantasy points use ESPN default scoring on 2025-26 season totals.
  KEY_SHARE       share of the team's output from its top 3 producers
  ROTATION_SHARE  players 4-8
  BENCH_SHARE     player 9 and beyond
  EFFECTIVE_N     1 / sum(share^2): how many equal contributors the split is worth
                  (high = spread out, low = a few players take most of it)
Two versions:
  2025_26    as the season was played: season totals, each player under the team he finished with
  2026_27    healthy 2026-27 rosters: per-game output (injured players' last full season,
             rookies' model projection), each player under his 2026-27 team, top 13 per team
The two versions are built differently (totals vs per game), so compare teams within a version.

Output: ./team_distribution.csv and ./team_roles_2026_27.csv (key / rotation / bench per player)
"""

from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
DATA = HERE / "nba_2025_26"
OUT = HERE / "team_distribution.csv"
ROLES = HERE / "team_roles_2026_27.csv"  # each player's role on his 2026-27 team

POINTS = {"PTS": 1, "FG3M": 1, "FGA": -1, "FGM": 2, "FTA": -1, "FTM": 1,
          "REB": 1, "AST": 2, "STL": 4, "BLK": 4, "TOV": -2}
KEY, ROTATION = 3, 8
ACTIVE_ROSTER = 13  # 2026-27 camp rosters are cut to the 13 best producers


def split(group: pd.DataFrame) -> pd.Series:
    fp = group["FP_TOTAL"].clip(lower=0).sort_values(ascending=False).reset_index(drop=True)
    total = fp.sum()
    share = fp / total
    top = group.sort_values("FP_TOTAL", ascending=False)["PLAYER_NAME"].head(KEY)
    return pd.Series({
        "KEY_SHARE": share[:KEY].sum(),
        "ROTATION_SHARE": share[KEY:ROTATION].sum(),
        "BENCH_SHARE": share[ROTATION:].sum(),
        "EFFECTIVE_N": 1 / (share ** 2).sum(),
        "KEY_PLAYERS": ", ".join(top),
    })


def fp_per_game(df: pd.DataFrame) -> pd.Series:
    return sum(df[c] * w for c, w in POINTS.items())


def healthy_2026_27(p: pd.DataFrame, roster: pd.Series) -> pd.DataFrame:
    """Per-game output of every rostered player as if healthy: 2025-26 per game, injured players'
    last full season, rookies' model projection."""
    rows = p[["PLAYER_ID", "PLAYER_NAME"]].assign(FP_TOTAL=fp_per_game(p))
    injured = HERE / "injured_last_full_season.csv"
    if injured.exists():
        inj = pd.read_csv(injured)
        inj = inj.assign(FP_TOTAL=fp_per_game(inj))[["PLAYER_NAME", "FP_TOTAL"]]
        last_full = inj.set_index("PLAYER_NAME")["FP_TOTAL"]
        played = rows["PLAYER_NAME"].isin(last_full.index)
        rows.loc[played, "FP_TOTAL"] = rows.loc[played, "PLAYER_NAME"].map(last_full)
        missing = inj[~inj["PLAYER_NAME"].isin(rows["PLAYER_NAME"])]
        if len(missing):
            ids = pd.read_csv(DATA / "player_index_2026_27.csv")
            ids["PLAYER_NAME"] = ids["PLAYER_FIRST_NAME"] + " " + ids["PLAYER_LAST_NAME"]
            missing = missing.merge(ids[["PLAYER_NAME", "PERSON_ID"]], on="PLAYER_NAME").rename(columns={"PERSON_ID": "PLAYER_ID"})
            rows = pd.concat([rows, missing], ignore_index=True)
    rookies = HERE / "rookie_projections_2026_27.csv"
    if rookies.exists():
        rk = pd.read_csv(rookies)
        rows = pd.concat([rows, rk.assign(FP_TOTAL=fp_per_game(rk))[["PLAYER_ID", "PLAYER_NAME", "FP_TOTAL"]]],
                         ignore_index=True)
    rows = rows.assign(TEAM_NEXT=rows["PLAYER_ID"].map(roster)).dropna(subset=["TEAM_NEXT"])
    rows = rows.sort_values("FP_TOTAL", ascending=False).drop_duplicates("PLAYER_ID")
    rows["TEAM_RANK"] = rows.groupby("TEAM_NEXT").cumcount() + 1
    rows["ROLE"] = pd.cut(rows["TEAM_RANK"], [0, KEY, ROTATION, float("inf")], labels=["key", "rotation", "bench"])
    return rows


def main() -> None:
    p = pd.read_csv(DATA / "players_base_pergame_regular.csv")
    p["FP_TOTAL"] = fp_per_game(p) * p["GP"]
    roster = pd.read_csv(DATA / "player_index_2026_27.csv").set_index("PERSON_ID")["TEAM_ABBREVIATION"]

    healthy = healthy_2026_27(p, roster)
    healthy[["PLAYER_ID", "PLAYER_NAME", "TEAM_NEXT", "TEAM_RANK", "ROLE"]].to_csv(
        ROLES, index=False, encoding="utf-8-sig")
    print(f"Saved {ROLES.name}")

    now = split_by(p, "TEAM_ABBREVIATION")
    nxt = split_by(healthy[healthy["TEAM_RANK"] <= ACTIVE_ROSTER], "TEAM_NEXT")
    out = now.join(nxt, lsuffix="_2025_26", rsuffix="_2026_27")
    out = out.sort_values("KEY_SHARE_2026_27", ascending=False)
    out.round(3).to_csv(OUT, encoding="utf-8-sig")
    print(f"Saved {OUT.name}\n")
    view = out[["KEY_SHARE_2025_26", "KEY_SHARE_2026_27", "ROTATION_SHARE_2026_27",
                "BENCH_SHARE_2026_27", "EFFECTIVE_N_2026_27", "KEY_PLAYERS_2026_27"]].copy()
    for c in view.columns[:4]:
        view[c] = (view[c] * 100).round(0).astype(int)
    view["EFFECTIVE_N_2026_27"] = view["EFFECTIVE_N_2026_27"].round(1)
    print(view.to_string())


def split_by(p: pd.DataFrame, col: str) -> pd.DataFrame:
    return p.groupby(col)[["PLAYER_NAME", "FP_TOTAL"]].apply(split)


if __name__ == "__main__":
    main()
