"""
Demo data, used until you add an ODDS_API_KEY.

It produces made-up games in exactly the same shape The Odds API returns,
with several sportsbooks whose prices disagree a little (like real books do),
plus final scores and box scores so grading can be tested. Nothing here is
real: the site shows a "Demo data" banner whenever this is in use.
"""
import hashlib
from datetime import datetime, timedelta, timezone

import numpy as np

from .model import PROP_STATS, prop_over_share, simulate_game, to_american

BOOKS = [("draftkings", "DraftKings"), ("fanduel", "FanDuel"), ("betmgm", "BetMGM"),
         ("williamhill_us", "Caesars"), ("betrivers", "BetRivers"), ("bovada", "Bovada"),
         ("betonlineag", "BetOnline.ag"), ("lowvig", "LowVig.ag")]

TEAMS = {
    "NBA": ["Boston Celtics", "New York Knicks", "Milwaukee Bucks", "Cleveland Cavaliers", "Denver Nuggets",
            "Oklahoma City Thunder", "Los Angeles Lakers", "Golden State Warriors", "Phoenix Suns", "Dallas Mavericks",
            "Miami Heat", "Minnesota Timberwolves", "Sacramento Kings", "Indiana Pacers", "Orlando Magic", "Houston Rockets"],
    "NFL": ["Kansas City Chiefs", "Buffalo Bills", "Philadelphia Eagles", "San Francisco 49ers", "Detroit Lions",
            "Baltimore Ravens", "Dallas Cowboys", "Green Bay Packers", "Cincinnati Bengals", "Los Angeles Rams",
            "Houston Texans", "Miami Dolphins", "Pittsburgh Steelers", "Minnesota Vikings", "Seattle Seahawks", "Denver Broncos"],
    "NHL": ["Vegas Golden Knights", "Edmonton Oilers", "Colorado Avalanche", "Dallas Stars", "Florida Panthers",
            "Toronto Maple Leafs", "New York Rangers", "Boston Bruins", "Carolina Hurricanes", "Winnipeg Jets",
            "Los Angeles Kings", "Tampa Bay Lightning", "Vancouver Canucks", "Minnesota Wild"],
    "MLB": ["Los Angeles Dodgers", "New York Yankees", "Philadelphia Phillies", "Seattle Mariners"],
}
FIRST = ["Marcus", "Jalen", "Tyrese", "Dominic", "Andre", "Cole", "Mateo", "Darius", "Isaiah", "Theo", "Malik", "Grant",
         "Desmond", "Elias", "Trent", "Omar", "Luca", "Xavier", "Jonah", "Silas", "Nico", "Felix", "Wade", "Rhett"]
LAST = ["Ortiz", "Hollister", "Vance", "Okonkwo", "Brandt", "Calloway", "Reyes", "Whitfield", "Mercer", "Adeyemi",
        "Castellano", "Pryor", "Novak", "Sutton", "Kincaid", "Delgado", "Fairbanks", "Moreau", "Ridley", "Banner",
        "Ashby", "Mensah", "Larue", "Petrov", "Holt", "Ibarra", "Strand", "Vasquez"]
PROPS = {"NBA": [("player_points", 26), ("player_points", 18), ("player_rebounds", 9.5), ("player_assists", 6.5)],
         "NFL": [("player_pass_yds", 245), ("player_rush_yds", 68), ("player_reception_yds", 62)],
         "MLB": [("pitcher_strikeouts", 6.2), ("batter_hits", 1.0)],
         "NHL": [("player_shots_on_goal", 3.1), ("player_total_saves", 27)]}
SPORT_KEYS = {"NBA": "basketball_nba", "NFL": "americanfootball_nfl", "MLB": "baseball_mlb",
              "NHL": "icehockey_nhl", "MMA": "mma_mixed_martial_arts", "BOX": "boxing_boxing"}


def h(*parts):
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


def name(*parts):
    k = h("name", *parts)
    return f"{FIRST[k % len(FIRST)]} {LAST[(k >> 8) % len(LAST)]}"


def two_way(p, rng, vig=0.045, noise=0.018):
    """A book's prices for a two-way market whose true chance is p."""
    q = float(np.clip(p + rng.normal(0, noise), 0.04, 0.96))
    a, b = q * (1 + vig), (1 - q) * (1 + vig)
    return to_american(1 / a), to_american(1 / b)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class DemoProvider:
    credits_used = 0
    credits_remaining = None

    def __init__(self):
        self._games = {}     # event id -> true details, for scores/box scores

    def active_sport_keys(self):
        return set(SPORT_KEYS.values())

    def _sport_of(self, key):
        return next(s for s, k in SPORT_KEYS.items() if k == key)

    def _slate(self, sport, start):
        """Deterministic made-up games for the local day containing `start`."""
        day = start.strftime("%Y-%m-%d")
        rng = np.random.default_rng(h(day, sport))
        dow = start.weekday()   # Monday = 0
        if sport == "NFL" and dow not in (6, 0, 3):
            return []
        if sport in ("MMA", "BOX") and dow not in (5,):
            return []
        n = {"NBA": 6, "NFL": 8 if dow == 6 else 1, "NHL": 6, "MLB": 1, "MMA": 4, "BOX": 2}[sport]
        base = datetime(start.year, start.month, start.day, 23, 0, tzinfo=timezone.utc)
        out = []
        if sport in TEAMS:
            teams = list(rng.permutation(TEAMS[sport]))
            for i in range(min(n, len(teams) // 2)):
                out.append((f"demo-{sport}-{day}-{i}", teams[2 * i], teams[2 * i + 1],
                            base + timedelta(minutes=30 * int(rng.integers(0, 7)) - (360 if sport == "NFL" and i < 6 else 0))))
        else:
            for i in range(n):
                out.append((f"demo-{sport}-{day}-{i}", name(sport, day, i, "a"), name(sport, day, i, "b"),
                            base + timedelta(hours=2, minutes=-30 * i)))
        return out

    def game_odds(self, sport_key, regions, markets, start_iso, end_iso):
        sport = self._sport_of(sport_key)
        start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
        events = []
        for d in {start.date(), end.date()}:
            for gid, home, away, t in self._slate(sport, datetime(d.year, d.month, d.day, tzinfo=timezone.utc)):
                if start < t <= end:
                    events.append(self._event(sport, sport_key, gid, home, away, t))
        return events

    def _event(self, sport, sport_key, gid, home, away, t):
        rng = np.random.default_rng(h(gid))
        upd = _iso(getattr(self, "now", datetime.now(timezone.utc)))
        books = []
        if sport in ("MMA", "BOX"):
            p = float(np.clip(rng.normal(0.55, 0.18), 0.12, 0.88))
            self._games[gid] = {"sport": sport, "p": p}
            for key, title in BOOKS:
                pa, pb = two_way(p, rng, vig=0.05)
                books.append({"key": key, "title": title, "markets": [{"key": "h2h", "last_update": upd, "outcomes": [
                    {"name": home, "price": pa}, {"name": away, "price": pb}]}]})
        else:
            typical = {"NBA": 114, "NFL": 22, "MLB": 4.4, "NHL": 3.05}[sport]
            spread = {"NBA": 5.5, "NFL": 4, "MLB": 0.5, "NHL": 0.35}[sport]
            mu_h = typical * rng.normal(1, 0.04) + spread * 0.25
            mu_a = typical * rng.normal(1, 0.04) - spread * 0.25
            mu_h += rng.normal(0, spread)
            g = simulate_game(sport, mu_h, mu_a, 6000, h(gid, "true"))
            self._games[gid] = {"sport": sport, "mu": (mu_h, mu_a)}
            p_home = float(np.mean(g["margin"] > 0) / max(1e-9, np.mean(g["margin"] != 0)))
            mline = float(np.median(g["margin"]))
            tline = float(np.median(g["total"]))
            for key, title in BOOKS:
                markets = []
                ph, pa = two_way(p_home, rng)
                markets.append({"key": "h2h", "last_update": upd, "outcomes": [{"name": home, "price": ph}, {"name": away, "price": pa}]})
                if sport in ("NBA", "NFL"):
                    hp = -(round(mline * 2) / 2 + rng.choice([0, 0, 0, 0.5, -0.5]))
                    hp = hp if hp % 1 else hp + 0.5
                elif sport == "MLB":
                    hp = -1.5 if p_home > 0.5 else 1.5
                else:
                    hp = -1.5 if p_home > 0.5 else 1.5
                cover = float(np.mean(g["margin"] + hp > 0) / max(1e-9, np.mean(g["margin"] + hp != 0)))
                sh, sa = two_way(cover, rng)
                markets.append({"key": "spreads", "last_update": upd, "outcomes": [
                    {"name": home, "price": sh, "point": hp}, {"name": away, "price": sa, "point": -hp}]})
                tl = round(tline * 2) / 2 + rng.choice([0, 0, 0, 0.5, -0.5])
                tl = tl if tl % 1 else tl + 0.5
                over = float(np.mean(g["total"] > tl))
                po, pu = two_way(over, rng)
                markets.append({"key": "totals", "last_update": upd, "outcomes": [
                    {"name": "Over", "price": po, "point": tl}, {"name": "Under", "price": pu, "point": tl}]})
                books.append({"key": key, "title": title, "markets": markets})
        return {"id": gid, "sport_key": sport_key, "commence_time": _iso(t), "home_team": home,
                "away_team": away, "bookmakers": books}

    def _players(self, sport, gid, home, away):
        out = []
        for side, team in (("home", home), ("away", away)):
            for i, (market, mean) in enumerate(PROPS[sport]):
                rng = np.random.default_rng(h(team, market, i))
                out.append((name(team, market, i), market, max(0.4, mean * rng.normal(1, 0.15))))
        return out

    def event_odds(self, sport_key, event_id, regions, markets):
        sport = self._sport_of(sport_key)
        parts = event_id.split("-")
        day = "-".join(parts[2:5])
        ev = next((e for e in self._slate(sport, datetime.fromisoformat(day + "T12:00:00+00:00")) if e[0] == event_id), None)
        if not ev:
            return None
        gid, home, away, t = ev
        rng = np.random.default_rng(h(gid, "props"))
        upd = _iso(getattr(self, "now", datetime.now(timezone.utc)))
        books = {k: {"key": k, "title": t_, "markets": {}} for k, t_ in BOOKS}
        for player, market, mean in self._players(sport, gid, home, away):
            if market not in markets:
                continue
            base_line = round(mean * 2) / 2
            base_line = base_line if base_line % 1 else base_line + 0.5
            if market == "batter_hits":
                base_line = 0.5
            for key, title in BOOKS:
                if rng.random() < 0.15:
                    continue                                   # not every book posts every prop
                line = base_line + (rng.choice([0, 0, 0, 1, -1]) if base_line > 3 else 0)
                po, pu = two_way(prop_over_share(market, mean, line), rng, vig=0.06, noise=0.022)
                books[key]["markets"].setdefault(market, []).extend([
                    {"name": "Over", "description": player, "price": po, "point": line},
                    {"name": "Under", "description": player, "price": pu, "point": line}])
        return {"id": gid, "home_team": home, "away_team": away, "commence_time": _iso(t),
                "bookmakers": [{"key": b["key"], "title": b["title"], "markets": [
                    {"key": m, "last_update": upd, "outcomes": o} for m, o in b["markets"].items()]} for b in books.values()]}

    # ---- results ----
    def _final(self, gid):
        sport = gid.split("-")[1]
        day = "-".join(gid.split("-")[2:5])
        ev = next(e for e in self._slate(sport, datetime.fromisoformat(day + "T12:00:00+00:00")) if e[0] == gid)
        self._event(sport, SPORT_KEYS[sport], *ev)
        mu_h, mu_a = self._games[gid]["mu"]
        g = simulate_game(sport, mu_h, mu_a, 1, h(gid, "final"))
        return ev, (float(g["home"][0]), float(g["away"][0]))

    def scores(self, sport_key, days_from=3):
        sport = self._sport_of(sport_key)
        if sport in ("MMA", "BOX"):
            return []
        now = datetime.now(timezone.utc) if not hasattr(self, "now") else self.now
        out = []
        for back in range(days_from + 1):
            d = now - timedelta(days=back)
            for gid, home, away, t in self._slate(sport, datetime(d.year, d.month, d.day, tzinfo=timezone.utc)):
                if t + timedelta(hours=3) < now:
                    _, (hs, as_) = self._final(gid)
                    out.append({"id": gid, "completed": True, "home_team": home, "away_team": away,
                                "scores": [{"name": home, "score": str(int(hs))}, {"name": away, "score": str(int(as_))}]})
        return out

    def box_score(self, sport, home, away, start_iso):
        from .espn import norm_name
        t = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        days = [t - timedelta(days=1), t]
        ev = next((e for d in days for e in self._slate(sport, datetime(d.year, d.month, d.day, tzinfo=timezone.utc))
                   if e[1] == home and e[2] == away and e[3] == t), None)
        if not ev:
            return None
        rng = np.random.default_rng(h(ev[0], "box"))
        out = {}
        for player, market, mean in self._players(sport, ev[0], home, away):
            _, fam, a, b = PROP_STATS[market]
            v = max(0, round(mean + (a * mean + b) * rng.normal())) if fam == "norm" else int(rng.poisson(mean))
            out.setdefault(norm_name(player), {})[market] = float(v)
        return out
