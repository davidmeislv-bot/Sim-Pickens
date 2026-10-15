"""
Player box scores for grading props, from ESPN's public scoreboard feeds.

The Odds API only has final scores, not player stats, so prop picks are
checked here. These ESPN feeds are free and need no key, but they are not an
official, documented API: if ESPN changes them, prop picks simply stay
"pending" and you can grade them by hand (see results_manual.json).
"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

SITE = "https://site.api.espn.com/apis/site/v2/sports"
LEAGUE = {"NBA": "basketball/nba", "NFL": "football/nfl", "MLB": "baseball/mlb", "NHL": "hockey/nhl"}

# market -> (which stat group, ESPN stat keys, ESPN column labels)
STAT_LOOKUP = {
    "player_points":        (None, ["points"], ["PTS"]),
    "player_rebounds":      (None, ["rebounds", "totalRebounds"], ["REB"]),
    "player_assists":       (None, ["assists"], ["AST"]),
    "player_pass_yds":      ("passing", ["passingYards"], ["YDS"]),
    "player_rush_yds":      ("rushing", ["rushingYards"], ["YDS"]),
    "player_reception_yds": ("receiving", ["receivingYards"], ["YDS"]),
    "pitcher_strikeouts":   ("pitching", ["strikeouts"], ["K"]),
    "batter_hits":          ("batting", ["hits"], ["H"]),
    "player_shots_on_goal": ("skaters", ["shotsTotal", "shots"], ["S", "SOG"]),
    "player_total_saves":   ("goalies", ["saves"], ["SV"]),
}


def norm_name(name):
    n = re.sub(r"[^a-z ]", "", name.lower().replace("-", " "))
    n = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", n)
    return " ".join(n.split())


def _group_kind(group):
    """Work out what a stat table is (passing, pitching, goalies...)."""
    name = (group.get("name") or group.get("type") or group.get("text") or "").lower()
    labels = group.get("labels") or []
    if "IP" in labels or "pitch" in name:
        return "pitching"
    if "AB" in labels or "batt" in name:
        return "batting"
    if "SV" in labels or "goalie" in name:
        return "goalies"
    for k in ("passing", "rushing", "receiving"):
        if k in name:
            return k
    return "skaters" if ("S" in labels or "SOG" in labels) else name


def parse_box(summary):
    """ESPN game summary JSON -> {normalized player name: {market: value}}."""
    out = {}
    for team in (summary.get("boxscore") or {}).get("players", []):
        for group in team.get("statistics", []):
            kind = _group_kind(group)
            keys = group.get("keys") or []
            labels = group.get("labels") or []
            for row in group.get("athletes", []):
                name = norm_name(((row.get("athlete") or {}).get("displayName")) or "")
                stats = row.get("stats") or []
                if not name or not stats:
                    continue
                for market, (want_kind, want_keys, want_labels) in STAT_LOOKUP.items():
                    if want_kind and want_kind != kind:
                        continue
                    col = next((keys.index(k) for k in want_keys if k in keys), None)
                    if col is None:
                        col = next((labels.index(l) for l in want_labels if l in labels), None)
                    if col is None or col >= len(stats):
                        continue
                    try:
                        out.setdefault(name, {})[market] = float(str(stats[col]).split("-")[0])
                    except ValueError:
                        pass
    return out


class ESPN:
    def __init__(self):
        self.session = requests.Session()

    def _get(self, url, **params):
        r = self.session.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def box_score(self, sport, home, away, start_iso):
        """Stats for a finished game, or None if it isn't found or isn't final."""
        if sport not in LEAGUE:
            return None
        start = datetime.fromisoformat(start_iso.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))
        board = self._get(f"{SITE}/{LEAGUE[sport]}/scoreboard", dates=start.strftime("%Y%m%d"))
        want = {norm_name(home), norm_name(away)}
        for event in board.get("events", []):
            comp = (event.get("competitions") or [{}])[0]
            names = {norm_name(c["team"]["displayName"]) for c in comp.get("competitors", [])}
            if names != want:
                continue
            if not ((event.get("status") or {}).get("type") or {}).get("completed"):
                return None
            return parse_box(self._get(f"{SITE}/{LEAGUE[sport]}/summary", event=event["id"]))
        return None
