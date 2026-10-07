"""
Build the draft-night dashboard from the downloaded stats.

Run nba_stats_2025_26.py first, then:
    python build_dashboard.py

Reads dashboard_template.html, embeds the player data and writes draft_dashboard.html.
Rankings are computed inside the page so every filter re-ranks live.
"""

import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
DATA = HERE / "nba_2025_26"
TEMPLATE = HERE / "dashboard_template.html"
OUT = HERE / "draft_dashboard.html"
# Standalone website for GitHub Pages, with Supabase accounts (built when site_config.json is filled in)
SITE_CONFIG = HERE / "site_config.json"
SITE_OUT = HERE / "docs" / "index.html"
SUPABASE_JS = "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/dist/umd/supabase.min.js"
SITE_RESET = ("html{color-scheme:light dark}body{margin:0;font:14px/1.45 system-ui,-apple-system,'Segoe UI',sans-serif}"
              "img{max-width:100%}[hidden]{display:none!important}")

MIN_GP = 10  # keep the file small; the page filters further
STATS = ["MIN", "PTS", "REB", "AST", "STL", "BLK", "FG3M", "TOV", "FGM", "FGA", "FTM", "FTA"]
ADV = ["USG_PCT", "PACE", "OFF_RATING"]
TEAM_ADV = ["PACE", "OFF_RATING", "DEF_RATING", "NET_RATING"]

# Players who missed most of 2025-26 are shown with their last full season instead
PREVIOUS_SEASONS = ["2024-25", "2023-24"]
INJURED_MAX_GP = 25   # fewer games than this in 2025-26
FULL_SEASON_GP = 40   # what counts as a full season before that
FULL_ROLE_MIN = 25    # and a real role in it
INJURED_CSV = HERE / "injured_last_full_season.csv"
ROOKIE_CSV = HERE / "rookie_projections_2026_27.csv"
DIST_CSV = HERE / "team_distribution.csv"  # from team_distribution.py
ROLES_CSV = HERE / "team_roles_2026_27.csv"  # from team_distribution.py


def entry(r, roster, adv, post=None) -> dict:
    pid = int(r["PLAYER_ID"])
    on_roster = pid in roster.index
    p = {
        "id": pid,
        "name": r["PLAYER_NAME"],
        "age": int(r["AGE"]),
        "team25": r["TEAM_ABBREVIATION"],
        "team26": roster.at[pid, "TEAM_ABBREVIATION"] if on_roster else None,
        "pos": roster.at[pid, "POSITION"] if on_roster else None,
        "gp": int(r["GP"]),
        "s": [round(float(r[c]), 2) for c in STATS],
    }
    if post is not None and pid in post.index:
        q = post.loc[pid]
        p["post_gp"] = int(q["GP"])
        p["post"] = [round(float(q[c]), 2) for c in STATS]
    if pid in adv.index:
        p["adv"] = [round(float(adv.at[pid, c]), 3) for c in ADV]
    return {k: v if isinstance(v, list) else (None if pd.isna(v) else v) for k, v in p.items()}


def injured_players(current: pd.DataFrame, roster: pd.DataFrame) -> list[dict]:
    """Rostered players with < INJURED_MAX_GP games in 2025-26, using their latest full season."""
    gp_now = current.set_index("PLAYER_ID")["GP"]
    seen, out = set(), []
    for season in PREVIOUS_SEASONS:
        tag = season.replace("-", "_")
        base = pd.read_csv(DATA / f"players_base_pergame_regular_{tag}.csv")
        adv = pd.read_csv(DATA / f"players_advanced_pergame_regular_{tag}.csv").set_index("PLAYER_ID")
        full = base[(base["GP"] >= FULL_SEASON_GP) & (base["MIN"] >= FULL_ROLE_MIN)]
        for _, r in full.iterrows():
            pid = int(r["PLAYER_ID"])
            if pid in seen:
                continue
            seen.add(pid)
            if gp_now.get(pid, 0) >= INJURED_MAX_GP or pid not in roster.index:
                continue
            p = entry(r, roster, adv)
            # team25 is the 2025-26 team, not the team in the older season
            cur = current[current["PLAYER_ID"] == pid]
            p["team25"] = cur["TEAM_ABBREVIATION"].iloc[0] if len(cur) else p["team26"]
            p["src"] = season
            p["team_src"] = r["TEAM_ABBREVIATION"]  # team the shown stats were recorded with
            p["gp_now"] = int(gp_now.get(pid, 0))
            out.append(p)
    return out


def rookies(existing: set[int]) -> list[dict]:
    """2026 draft class with model projections from rookie_projections.py."""
    if not ROOKIE_CSV.exists():
        print(f"{ROOKIE_CSV.name} not found, skipping rookies (run rookie_projections.py)")
        return []
    out = []
    for _, r in pd.read_csv(ROOKIE_CSV).iterrows():
        pid = int(r["PLAYER_ID"])
        if pid in existing:
            continue
        out.append({
            "id": pid,
            "name": r["PLAYER_NAME"],
            "age": None if pd.isna(r["AGE"]) else int(r["AGE"]),
            "team25": None,
            "team26": r["TEAM"],
            "pos": None if pd.isna(r["POSITION"]) else r["POSITION"],
            "gp": int(round(r["GP"])),
            "s": [round(float(r[c]), 2) for c in STATS],
            "rookie": True,
            "pick": int(r["PICK"]),
            "college": None if pd.isna(r["COLLEGE"]) else r["COLLEGE"],
            "note": None if pd.isna(r["SCOUTING_NOTE"]) else r["SCOUTING_NOTE"],
            "pts_range": [round(float(r["PTS_LOW"]), 1), round(float(r["PTS_HIGH"]), 1)],
        })
    return out


def main() -> None:
    current = pd.read_csv(DATA / "players_base_pergame_regular.csv")
    post = pd.read_csv(DATA / "players_base_pergame_post_allstar.csv").set_index("PLAYER_ID")
    roster = pd.read_csv(DATA / "player_index_2026_27.csv").set_index("PERSON_ID")
    adv = pd.read_csv(DATA / "players_advanced_pergame_regular.csv").set_index("PLAYER_ID")

    injured = injured_players(current, roster)
    injured_ids = {p["id"] for p in injured}
    players = [entry(r, roster, adv, post) for _, r in current[current["GP"] >= MIN_GP].iterrows()
               if int(r["PLAYER_ID"]) not in injured_ids]
    players += injured
    players += rookies({p["id"] for p in players})

    pd.DataFrame([{
        "PLAYER_NAME": p["name"], "TEAM_2026_27": p["team26"], "AGE": p["age"],
        "GP_2025_26": p["gp_now"], "LAST_FULL_SEASON": p["src"], "GP": p["gp"],
        **dict(zip(STATS, p["s"])),
        **({"USG_PCT": p["adv"][0], "PACE": p["adv"][1], "OFF_RATING": p["adv"][2]} if p.get("adv") else {}),
    } for p in sorted(injured, key=lambda p: -p["s"][STATS.index("PTS")])]).to_csv(
        INJURED_CSV, index=False, encoding="utf-8-sig")
    print(f"Saved {INJURED_CSV.name} ({len(injured)} players)")

    abbr = roster.drop_duplicates("TEAM_ID").set_index("TEAM_ID")["TEAM_ABBREVIATION"]
    team_adv = pd.read_csv(DATA / "teams_advanced_pergame_regular.csv")
    teams = [{"t": abbr.get(r["TEAM_ID"]), "name": r["TEAM_NAME"],
              **{c: round(float(r[c]), 2) for c in TEAM_ADV}}
             for _, r in team_adv.iterrows()]

    html = TEMPLATE.read_text(encoding="utf-8")
    if ROLES_CSV.exists():
        roles = pd.read_csv(ROLES_CSV).set_index("PLAYER_ID")["ROLE"].to_dict()
        for p in players:
            p["role"] = roles.get(p["id"])

    dist = []
    if DIST_CSV.exists():
        for _, r in pd.read_csv(DIST_CSV).iterrows():
            dist.append({"t": r["TEAM_ABBREVIATION"], "key": round(float(r["KEY_SHARE_2026_27"]), 3),
                         "rot": round(float(r["ROTATION_SHARE_2026_27"]), 3),
                         "bench": round(float(r["BENCH_SHARE_2026_27"]), 3),
                         "n": round(float(r["EFFECTIVE_N_2026_27"]), 1), "players": r["KEY_PLAYERS_2026_27"]})
    else:
        print(f"{DIST_CSV.name} not found, skipping the importance panel (run team_distribution.py)")

    payload = json.dumps({"stats": STATS, "players": players, "teams": teams, "dist": dist}, ensure_ascii=False, separators=(",", ":"))
    html = html.replace("/*__DATA__*/null", payload)
    OUT.write_text(html, encoding="utf-8")
    build_site(html)
    print(f"Saved {OUT.name} ({len(players)} players)")


def build_site(html: str) -> None:
    """Wrap the page in a full HTML document and switch it to Supabase sign-in."""
    if not SITE_CONFIG.exists():
        print(f"{SITE_CONFIG.name} not found, skipping the website")
        return
    cfg = json.loads(SITE_CONFIG.read_text(encoding="utf-8"))
    if not cfg.get("supabaseUrl") or not cfg.get("supabaseKey"):
        print(f"{SITE_CONFIG.name} is missing supabaseUrl / supabaseKey, skipping the website")
        return
    site_cfg = json.dumps({"supabaseUrl": cfg["supabaseUrl"], "supabaseKey": cfg["supabaseKey"]})
    html = html.replace("/*__SITE__*/null", site_cfg)
    html = html.replace("\n<script>\n", f'\n<script src="{SUPABASE_JS}"></script>\n<script>\n', 1)
    # The template starts with <title>, font links and <style>; those belong in <head>
    cut = html.index("</style>") + len("</style>")
    head, body = html[:cut], html[cut:]
    page = ('<!doctype html><html lang="he"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            f"<style>{SITE_RESET}</style>{head}</head><body>{body}</body></html>")
    SITE_OUT.parent.mkdir(exist_ok=True)
    SITE_OUT.write_text(page, encoding="utf-8")
    (SITE_OUT.parent / ".nojekyll").write_text("", encoding="utf-8")  # serve files as-is
    print(f"Saved website {SITE_OUT.relative_to(HERE)}")


if __name__ == "__main__":
    main()
