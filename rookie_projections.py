"""
Project 2026-27 stat lines for the 2026 draft class.

Run fetch_rookie_history.py first, then:
    python rookie_projections.py

Model, trained on the 2015-2025 draft classes:
  - Per-36 rates (PTS, REB, AST, STL, BLK, 3PM, TOV, FGA, FTA, FG%, FT%): ridge regression on
    the player's final college season (per-40 production, shooting, usage, BPM), age, height
    and draft slot.
  - Minutes per game and games played: ridge regression on draft slot, age, college BPM, the
    team's win % the season before, and minutes that opened up at the rookie's position
    (players who left minus players who arrived).
  - Players without a D-I college season (international, G League) use a draft-slot-only model.
  - Scouting adjustments from rookie_scouting.csv are applied last (minutes and per-category
    multipliers), each with its reason.

Output: ./rookie_projections_2026_27.csv
"""

import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
DATA = HERE / "nba_2025_26"
COLLEGE = DATA / "college"
ROOKIES = DATA / "rookies"
SCOUTING = HERE / "rookie_scouting.csv"
OUT = HERE / "rookie_projections_2026_27.csv"

TRAIN_YEARS = range(2015, 2026)
DRAFT_YEAR = 2026
MIN_TRAIN_MINUTES = 300  # rookies need this many total minutes for their rates to count
RIDGE = 5.0

BT_COLS = {
    0: "name", 1: "team", 2: "conf", 3: "gp", 4: "min_pct", 6: "usg", 8: "ts", 9: "orb_pct",
    10: "drb_pct", 11: "ast_pct", 12: "to_pct", 13: "ftm", 14: "fta", 15: "ft_pct", 16: "p2m",
    17: "p2a", 19: "p3m", 20: "p3a", 22: "blk_pct", 23: "stl_pct", 25: "cls", 26: "ht",
    31: "year", 37: "rim_att", 45: "pick", 50: "bpm", 54: "mpg", 59: "reb", 60: "ast",
    61: "stl", 62: "blk", 63: "pts", 64: "role", 66: "dob",
}

RATE_TARGETS = ["PTS", "REB", "AST", "STL", "BLK", "FG3M", "TOV", "FGA", "FTA"]
PCT_TARGETS = ["FG_PCT", "FT_PCT"]
COLLEGE_FEATURES = [
    "pts40", "reb40", "ast40", "stl40", "blk40", "p3m40", "p3a40", "fta40", "fga40", "rim40",
    "ft_pct", "p2_pct", "usg", "to_pct", "orb_pct", "drb_pct", "ast_pct", "stl_pct", "blk_pct",
    "bpm", "age", "height", "log_pick",
]
SLOT_FEATURES = ["log_pick"]
# Team strength (last season win %) and open minutes at the position, net of arrivals, only move
# minutes and games; tested, they do not change per-minute production
MINUTES_FEATURES = ["log_pick", "age", "bpm", "team_wpct", "open_min"]


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", s)
    return re.sub(r"[^a-z]", "", s)


def height_in(ht) -> float:
    m = re.match(r"(\d+)-(\d+)", str(ht))
    return int(m.group(1)) * 12 + int(m.group(2)) if m else np.nan


def load_college(year: int) -> pd.DataFrame:
    df = pd.read_csv(COLLEGE / f"barttorvik_{year}.csv", header=None, low_memory=False)
    df = df[list(BT_COLS)].rename(columns=BT_COLS)
    df["pick"] = pd.to_numeric(df["pick"], errors="coerce")
    for c in ["gp", "mpg", "pts", "reb", "ast", "stl", "blk", "ftm", "fta", "p2m", "p2a", "p3m", "p3a", "rim_att"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    games = df["gp"].replace(0, np.nan)
    per40 = 40 / df["mpg"].replace(0, np.nan)
    for c in ["pts", "reb", "ast", "stl", "blk"]:
        df[f"{c}40"] = df[c] * per40
    for c in ["p3m", "p3a", "fta", "rim_att"]:
        df[f"{c.replace('_att', '')}40"] = df[c] / games * per40
    df["fga40"] = (df["p2a"] + df["p3a"]) / games * per40
    df["p2_pct"] = df["p2m"] / df["p2a"].replace(0, np.nan)
    df["height"] = df["ht"].map(height_in)
    draft_day = pd.Timestamp(f"{year}-06-25")
    df["age"] = (draft_day - pd.to_datetime(df["dob"], errors="coerce")).dt.days / 365.25
    df["key"] = df["name"].map(norm)
    return df


def match_college(players: pd.DataFrame, college: pd.DataFrame) -> pd.DataFrame:
    """Attach each player's final college season: same name, or same pick with the same surname."""
    drafted = college[college["pick"].notna()]
    by_name = college.drop_duplicates("key").set_index("key")
    rows = []
    for _, p in players.iterrows():
        key = norm(p["name"])
        hit = None
        if key in by_name.index:
            hit = by_name.loc[key]
        else:
            same_pick = drafted[drafted["pick"] == p["pick"]]
            surname = norm(str(p["name"]).split()[-1]) if str(p["name"]).split() else ""
            same_pick = same_pick[same_pick["key"].str.contains(surname, regex=False)] if surname else same_pick.iloc[0:0]
            if len(same_pick) == 1:
                hit = same_pick.iloc[0]
        rows.append(hit.drop(labels=["name", "pick"]) if hit is not None else pd.Series(dtype=float))
    return pd.concat([players.reset_index(drop=True), pd.DataFrame(rows).reset_index(drop=True)], axis=1)


class Ridge:
    """Standardized ridge regression with an unpenalized intercept."""

    def __init__(self, alpha: float = RIDGE):
        self.alpha = alpha

    def fit(self, X: np.ndarray, y: np.ndarray, w: np.ndarray | None = None):
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-9
        Z = (X - self.mu) / self.sd
        w = np.ones(len(y)) if w is None else w
        A = np.c_[np.ones(len(Z)), Z]
        P = np.eye(A.shape[1]) * self.alpha
        P[0, 0] = 0
        W = A * w[:, None]
        self.beta = np.linalg.solve(A.T @ W + P, W.T @ y)
        resid = y - self.predict(X)
        self.resid_q = np.quantile(resid, [0.2, 0.8])
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.c_[np.ones(len(X)), (X - self.mu) / self.sd] @ self.beta


def training_set() -> pd.DataFrame:
    frames = []
    for y in TRAIN_YEARS:
        season = f"{y}_{(y + 1) % 100:02d}"
        r = pd.read_csv(ROOKIES / f"rookies_{season}.csv")
        r = r[r["DRAFT_YEAR"].astype(str) == str(y)].copy()
        r["pick"] = pd.to_numeric(r["DRAFT_NUMBER"], errors="coerce")
        r = r[r["pick"].notna()].rename(columns={"PLAYER_NAME": "name"})
        r["draft_year"] = y
        r["rookie_age"] = r["AGE"]
        frames.append(match_college(r, load_college(y)))
    df = pd.concat(frames, ignore_index=True)
    df["log_pick"] = np.log(df["pick"])
    df["total_min"] = df["MIN"] * df["GP"]
    for t in RATE_TARGETS:
        df[f"{t}_36"] = df[t] / df["MIN"].replace(0, np.nan) * 36
    return df


def season_str(y: int) -> str:
    return f"{y}-{(y + 1) % 100:02d}"


def pos_set(pos) -> set[str]:
    return set(str(pos).split("-")) & {"G", "F", "C"} if pd.notna(pos) else {"G", "F", "C"}


def team_context(df: pd.DataFrame, rosters_now: dict[int, pd.DataFrame]) -> pd.DataFrame:
    """Add team strength, open minutes at the rookie's position, and the team's habit with rookies.

    df needs PLAYER_ID, TEAM_ID, draft_year and POS. rosters_now maps a draft year to the
    roster (PLAYER_ID, TEAM_ID) of the rookie season; training uses end-of-season teams.
    """
    records = pd.read_csv(ROOKIES / "team_records.csv").set_index(["TEAM_ID", "SEASON"])["W_PCT"]
    positions = pd.read_csv(ROOKIES / "positions.csv").set_index("PERSON_ID")["POSITION"]
    last_seasons = {}
    df = df.copy()
    wpct, open_min = [], []
    for _, r in df.iterrows():
        y, team, mine = int(r["draft_year"]), r["TEAM_ID"], pos_set(r["POS"])
        prev = season_str(y - 1)
        wpct.append(records.get((team, prev), np.nan))
        if prev not in last_seasons:
            last_seasons[prev] = pd.read_csv(ROOKIES / f"all_players_{prev.replace('-', '_')}.csv")
        last = last_seasons[prev]
        now = rosters_now[y]
        now_team = set(now.loc[now["TEAM_ID"] == team, "PLAYER_ID"])
        same_pos = last["PLAYER_ID"].map(lambda pid: bool(pos_set(positions.get(pid)) & mine))
        departed = last[(last["TEAM_ID"] == team) & ~last["PLAYER_ID"].isin(now_team) & same_pos]["MIN"].sum()
        arrived = last[(last["TEAM_ID"] != team) & last["PLAYER_ID"].isin(now_team) & same_pos]["MIN"].sum()
        open_min.append((departed - arrived) / 82)
    df["team_wpct"] = wpct
    df["open_min"] = open_min
    return df


def rookie_tendency(train: pd.DataFrame, teams: pd.Series, years: pd.Series) -> np.ndarray:
    """How many more minutes than expected (for their draft slot) a team gave its rookies over the
    previous three classes, shrunk toward zero for small samples."""
    base = Ridge().fit(train[["log_pick"]].to_numpy(), train["MIN"].to_numpy())
    resid = train.assign(r=train["MIN"] - base.predict(train[["log_pick"]].to_numpy()))
    out = []
    for team, y in zip(teams, years):
        past = resid[(resid["TEAM_ID"] == team) & resid["draft_year"].between(y - 3, y - 1)]["r"]
        out.append(past.sum() / (len(past) + 3))
    return np.array(out)


def features(df: pd.DataFrame, cols: list[str], fill: pd.Series) -> np.ndarray:
    return df[cols].astype(float).fillna(fill[cols]).to_numpy()


def main() -> None:
    train = training_set()
    positions = pd.read_csv(ROOKIES / "positions.csv").set_index("PERSON_ID")["POSITION"]
    train["POS"] = train["PLAYER_ID"].map(positions)
    train = team_context(train, {y: pd.read_csv(ROOKIES / f"all_players_{season_str(y).replace('-', '_')}.csv")
                                 for y in TRAIN_YEARS})
    has_college = train["pts40"].notna()
    print(f"Training rookies: {len(train)} drafted, {has_college.sum()} matched to a college season")

    fill = train[COLLEGE_FEATURES + ["team_wpct", "open_min"]].astype(float).median()
    rated = train[train["total_min"] >= MIN_TRAIN_MINUTES]
    w = np.sqrt(rated["total_min"].to_numpy())

    college_rows = rated[rated["pts40"].notna()]
    wc = np.sqrt(college_rows["total_min"].to_numpy())
    models, slot_models = {}, {}
    for t in [f"{x}_36" for x in RATE_TARGETS] + PCT_TARGETS:
        models[t] = Ridge().fit(features(college_rows, COLLEGE_FEATURES, fill), college_rows[t].to_numpy(), wc)
        slot_models[t] = Ridge().fit(features(rated, SLOT_FEATURES, fill), rated[t].to_numpy(), w)

    # Minutes and games use every drafted rookie who played, including tiny roles
    min_model = Ridge().fit(features(train, MINUTES_FEATURES, fill), train["MIN"].to_numpy())
    gp_model = Ridge().fit(features(train, MINUTES_FEATURES, fill), train["GP"].to_numpy())

    # Leave-one-class-out check: does college data beat draft slot alone?
    errs = {"college": [], "slot": []}
    for y in TRAIN_YEARS:
        tr, te = college_rows[college_rows["draft_year"] != y], college_rows[college_rows["draft_year"] == y]
        if te.empty:
            continue
        for kind, cols in [("college", COLLEGE_FEATURES), ("slot", SLOT_FEATURES)]:
            m = Ridge().fit(features(tr, cols, fill), tr["PTS_36"].to_numpy(), np.sqrt(tr["total_min"].to_numpy()))
            errs[kind] += list(np.abs(m.predict(features(te, cols, fill)) - te["PTS_36"].to_numpy()))
    print(f"PTS per 36, mean abs error (held-out classes): college model {np.mean(errs['college']):.2f}, "
          f"draft slot only {np.mean(errs['slot']):.2f}")

    # 2026 class
    roster = pd.read_csv(DATA / "player_index_2026_27.csv")
    rk = roster[roster["DRAFT_YEAR"] == DRAFT_YEAR].copy()
    rk["name"] = rk["PLAYER_FIRST_NAME"] + " " + rk["PLAYER_LAST_NAME"]
    rk["pick"] = rk["DRAFT_NUMBER"].astype(float)
    rk = match_college(rk[["PERSON_ID", "name", "pick", "TEAM_ID", "TEAM_ABBREVIATION", "POSITION", "HEIGHT", "COLLEGE", "COUNTRY"]],
                       load_college(DRAFT_YEAR))
    rk = team_context(rk.assign(PLAYER_ID=rk["PERSON_ID"], draft_year=DRAFT_YEAR, POS=rk["POSITION"]),
                      {DRAFT_YEAR: roster.rename(columns={"PERSON_ID": "PLAYER_ID"})[["PLAYER_ID", "TEAM_ID"]]})
    rk["log_pick"] = np.log(rk["pick"])
    rk["height"] = rk["height"].fillna(rk["HEIGHT"].map(height_in))
    college_ok = rk["pts40"].notna().to_numpy()

    proj = pd.DataFrame({"PLAYER_ID": rk["PERSON_ID"], "PLAYER_NAME": rk["name"], "PICK": rk["pick"].astype(int),
                         "TEAM": rk["TEAM_ABBREVIATION"], "POSITION": rk["POSITION"],
                         "COLLEGE": rk["COLLEGE"].fillna(rk["COUNTRY"]),
                         "AGE": rk["age"].astype(float).round(1),
                         "MODEL": np.where(college_ok, "college", "draft slot")})
    Xc, Xs, Xm = (features(rk, c, fill) for c in (COLLEGE_FEATURES, SLOT_FEATURES, MINUTES_FEATURES))
    rates, lo, hi = {}, {}, {}
    for t in models:
        pc, ps = models[t].predict(Xc), slot_models[t].predict(Xs)
        rates[t] = np.where(college_ok, pc, ps)
        q = np.where(college_ok[:, None], models[t].resid_q, slot_models[t].resid_q)
        lo[t], hi[t] = rates[t] + q[:, 0], rates[t] + q[:, 1]
    proj["TEAM_WPCT_2025_26"] = rk["team_wpct"].round(3)
    proj["OPEN_MIN_AT_POS"] = rk["open_min"].round(1)
    proj["MIN"] = np.clip(min_model.predict(Xm), 8, 34)
    proj["GP"] = np.clip(gp_model.predict(Xm), 20, 78)

    # Scouting adjustments
    proj["SCOUTING_NOTE"] = ""
    if SCOUTING.exists():
        sc = pd.read_csv(SCOUTING).set_index("PLAYER_NAME")
        unknown = set(sc.index) - set(proj["PLAYER_NAME"])
        if unknown:
            print(f"Scouting rows with no matching rookie: {sorted(unknown)}")
        for i, name in proj["PLAYER_NAME"].items():
            if name not in sc.index:
                continue
            s = sc.loc[name].fillna(1)
            proj.at[i, "MIN"] = np.clip(proj.at[i, "MIN"] * s.get("MIN_MULT", 1), 8, 36)
            proj.at[i, "GP"] = np.clip(proj.at[i, "GP"] * s.get("GP_MULT", 1), 15, 80)
            for t in RATE_TARGETS:
                k = f"{t}_MULT"
                if k in s and pd.notna(s[k]):
                    rates[f"{t}_36"][i] *= s[k]
                    lo[f"{t}_36"][i] *= s[k]
                    hi[f"{t}_36"][i] *= s[k]
            proj.at[i, "SCOUTING_NOTE"] = s.get("NOTE", "")

    per_game = proj["MIN"] / 36
    for t in RATE_TARGETS:
        proj[t] = np.maximum(rates[f"{t}_36"], 0) * per_game
    proj["PTS_LOW"] = np.maximum(lo["PTS_36"], 0) * per_game
    proj["PTS_HIGH"] = hi["PTS_36"] * per_game
    proj["FG_PCT"] = np.clip(rates["FG_PCT"], 0.36, 0.64)
    proj["FT_PCT"] = np.clip(rates["FT_PCT"], 0.50, 0.92)
    proj["FGM"] = proj["FGA"] * proj["FG_PCT"]
    proj["FTM"] = proj["FTA"] * proj["FT_PCT"]

    cols = ["PICK", "PLAYER_NAME", "TEAM", "POSITION", "COLLEGE", "AGE", "MODEL",
            "TEAM_WPCT_2025_26", "OPEN_MIN_AT_POS", "GP", "MIN",
            "PTS", "PTS_LOW", "PTS_HIGH", "REB", "AST", "STL", "BLK", "FG3M", "TOV",
            "FGM", "FGA", "FG_PCT", "FTM", "FTA", "FT_PCT", "SCOUTING_NOTE", "PLAYER_ID"]
    out = proj[cols].sort_values("PICK").round(3)
    out.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"Saved {OUT.name} ({len(out)} rookies, {college_ok.sum()} with a college season)\n")
    show = ["PICK", "PLAYER_NAME", "TEAM", "MODEL", "MIN", "PTS", "REB", "AST", "STL", "BLK", "FG3M", "FG_PCT", "FT_PCT", "TOV"]
    print(out[show].head(20).round(2).to_string(index=False))


if __name__ == "__main__":
    main()
