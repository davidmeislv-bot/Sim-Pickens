"""
Talks to The Odds API (https://the-odds-api.com).

Every call here returns the API's JSON as Python lists and dicts. Nothing in
this file does any math; it only fetches data.
"""
import time

import requests

BASE = "https://api.the-odds-api.com/v4"


class OddsAPIError(Exception):
    pass


class OddsAPI:
    def __init__(self, key):
        self.key = key
        self.session = requests.Session()
        self.credits_used = 0          # credits this run has spent
        self.credits_remaining = None  # credits left on your plan this month

    def _get(self, path, **params):
        params["apiKey"] = self.key
        for attempt in range(3):
            resp = self.session.get(BASE + path, params=params, timeout=30)
            if resp.status_code == 429:          # too many requests: wait and retry
                time.sleep(2 + 2 * attempt)
                continue
            break
        if resp.status_code == 401:
            raise OddsAPIError("The Odds API rejected the key. Check the ODDS_API_KEY secret in GitHub.")
        if resp.status_code in (404, 422):       # no data for this sport/event right now
            return None
        if resp.status_code >= 400:
            raise OddsAPIError(f"The Odds API returned {resp.status_code}: {resp.text[:200]}")
        used = resp.headers.get("x-requests-last")
        if used:
            self.credits_used += int(float(used))
        remaining = resp.headers.get("x-requests-remaining")
        if remaining:
            self.credits_remaining = int(float(remaining))
        return resp.json()

    def active_sport_keys(self):
        """Sports that are in season right now. This call is free."""
        data = self._get("/sports") or []
        return {s["key"] for s in data if s.get("active")}

    def game_odds(self, sport_key, regions, markets, start_iso, end_iso):
        """Moneyline, spread and total for every game in the window. Costs markets x regions."""
        return self._get(f"/sports/{sport_key}/odds", regions=regions, markets=",".join(markets),
                         oddsFormat="american", dateFormat="iso",
                         commenceTimeFrom=start_iso, commenceTimeTo=end_iso) or []

    def event_odds(self, sport_key, event_id, regions, markets):
        """Player props for one game. Costs (markets returned) x regions."""
        return self._get(f"/sports/{sport_key}/events/{event_id}/odds", regions=regions,
                         markets=",".join(markets), oddsFormat="american", dateFormat="iso")

    def scores(self, sport_key, days_from=3):
        """Final scores from the last few days. Costs 2 credits per sport."""
        return self._get(f"/sports/{sport_key}/scores", daysFrom=days_from, dateFormat="iso") or []
