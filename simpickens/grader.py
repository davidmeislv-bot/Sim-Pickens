"""
Grades past picks as won, lost or push and keeps the running record.

Game lines (moneyline, spread, total) use final scores from The Odds API.
Player props use ESPN box scores. Fights, and anything that can't be found
automatically, can be graded by hand in results_manual.json.
"""
import json
import os
from datetime import datetime, timedelta, timezone

from .espn import norm_name
from .model import to_decimal

MANUAL_FILE = "results_manual.json"
GIVE_UP_DAYS = 3   # after this many days, unfound results are flagged for a manual grade


def load_manual(path=MANUAL_FILE):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        data = json.load(f)
    return {k.strip(): str(v).strip().lower() for k, v in data.get("results", {}).items()}


def settle(value, side, line):
    if value == line:
        return "push"
    if side == "over":
        return "won" if value > line else "lost"
    return "won" if value < line else "lost"


def units_for(result, odds):
    if result == "won":
        return round(to_decimal(odds) - 1, 4)
    if result == "lost":
        return -1.0
    return 0.0


def grade_one(pick, final, box):
    """final = (home_score, away_score) or None; box = {player: {market: value}} or None."""
    g = pick["grade"]
    if g["kind"] in ("ml", "spread", "total"):
        if final is None:
            return None
        hs, as_ = final
        if g["kind"] == "total":
            return settle(hs + as_, g["side"], g["point"])
        margin = hs - as_ if g["team"] == pick["home"] else as_ - hs
        if g["kind"] == "ml":
            return settle(margin, "over", 0)
        return settle(margin + g["point"], "over", 0)
    if g["kind"] == "prop":
        if not box:
            return None
        stats = box.get(norm_name(g["player"]))
        if not stats or g["market"] not in stats:
            return None
        return settle(stats[g["market"]], g["side"], g["point"])
    return None   # fights: manual only


def grade_record(record, provider, now, log=print):
    pending = [p for p in record["picks"] if p.get("result") in (None, "pending", "manual")]
    if not pending:
        return 0
    manual = load_manual()
    finals, boxes = {}, {}
    sports_needed = {p["sport_key"] for p in pending if p["grade"]["kind"] in ("ml", "spread", "total")}
    for sk in sports_needed:
        for ev in provider.scores(sk):
            if ev.get("completed") and ev.get("scores"):
                s = {x["name"]: float(x["score"]) for x in ev["scores"]}
                if ev["home_team"] in s and ev["away_team"] in s:
                    finals[ev["id"]] = (s[ev["home_team"]], s[ev["away_team"]])

    graded = 0
    for p in pending:
        key = f"{p['date']} #{p['rank']}"
        result = manual.get(key)
        if result not in ("won", "lost", "push"):
            result = None
            start = datetime.fromisoformat(p["start"].replace("Z", "+00:00"))
            if now - start < timedelta(hours=3):
                continue                                   # game may still be going
            box = None
            if p["grade"]["kind"] == "prop":
                if p["event_id"] not in boxes:
                    try:
                        boxes[p["event_id"]] = provider.box_score(p["sport"], p["home"], p["away"], p["start"])
                    except Exception as e:                 # ESPN down or changed
                        log(f"  box score lookup failed for {p['matchup']}: {e}")
                        boxes[p["event_id"]] = None
                box = boxes[p["event_id"]]
            result = grade_one(p, finals.get(p["event_id"]), box)
            if result is None:
                if now - start > timedelta(days=GIVE_UP_DAYS):
                    p["result"] = "manual"
                continue
        p["result"] = result
        p["units"] = units_for(result, p["odds"])
        graded += 1
    log(f"Graded {graded} picks")
    return graded


def summarize(record):
    done = [p for p in record["picks"] if p.get("result") in ("won", "lost", "push")]
    w = sum(p["result"] == "won" for p in done)
    l = sum(p["result"] == "lost" for p in done)
    pu = sum(p["result"] == "push" for p in done)
    units = round(sum(p.get("units", 0) for p in done), 2)
    risked = w + l
    by_sport = {}
    for p in done:
        s = by_sport.setdefault(p["sport"], {"won": 0, "lost": 0, "push": 0, "units": 0.0})
        s[p["result"]] += 1
        s["units"] = round(s["units"] + p.get("units", 0), 2)
    record["summary"] = {
        "won": w, "lost": l, "push": pu, "units": units,
        "roi": round(units / risked, 4) if risked else None,
        "pending": sum(p.get("result") in (None, "pending") for p in record["picks"]),
        "manual": sum(p.get("result") == "manual" for p in record["picks"]),
        "by_sport": by_sport,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return record
