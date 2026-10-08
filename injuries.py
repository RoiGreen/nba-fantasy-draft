"""
Pull ESPN's NBA injury list into ./nba_2026_27/injuries.csv (and stamp the time in injuries_updated.txt).

    python injuries.py

Used by the daily run on this computer (daily_update.py) and by the GitHub Actions workflow that
refreshes injuries during the day. Needs only pandas, so it also runs where stats.nba.com is blocked.
A failed pull keeps the previous list.
"""

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
OUT = HERE / "nba_2026_27"
URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"


def pull_injuries() -> str:
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
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
    OUT.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT / "injuries.csv", index=False, encoding="utf-8-sig")
    (OUT / "injuries_updated.txt").write_text(datetime.now(timezone.utc).isoformat(timespec="minutes"), encoding="utf-8")
    return f"Injuries: {len(rows)} players listed"


if __name__ == "__main__":
    print(pull_injuries())
