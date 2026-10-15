"""
Run Sim Pickens.

    python -m simpickens daily           pull today's odds, run the sims, grade past picks
    python -m simpickens daily --force   redo today even if today's picks already exist
    python -m simpickens grade           only grade past picks (no new odds pulled)

With no ODDS_API_KEY set it runs on demo data.
Everything it writes goes in docs/data/, which is what the website reads.
"""
import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import config
from .engine import build_slate
from .grader import grade_record, summarize

DATA = os.path.join("docs", "data")
DAYS = os.path.join(DATA, "days")


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, path)


def r4(x):
    return round(float(x), 4)


def clean(pick, i):
    """A pick ready for the site: probabilities rounded, rank added."""
    out = {k: (r4(v) if k in ("win", "push", "lose", "ev", "book_fair") else v)
           for k, v in pick.items() if k != "sel"}
    out["rank"] = i + 1
    return out


def make_provider(force_demo):
    key = os.environ.get("ODDS_API_KEY", "").strip()
    if key and not force_demo:
        from .espn import ESPN
        from .odds_api import OddsAPI

        api, espn = OddsAPI(key), ESPN()
        api.box_score = espn.box_score     # props are graded from ESPN box scores
        return api, False
    from .demo import DemoProvider
    return DemoProvider(), True


def main():
    ap = argparse.ArgumentParser(prog="simpickens")
    ap.add_argument("command", choices=["daily", "grade"])
    ap.add_argument("--force", action="store_true", help="redo today's picks")
    ap.add_argument("--demo", action="store_true", help="use demo data even if a key is set")
    ap.add_argument("--now", help=argparse.SUPPRESS)   # for testing: pretend it's this UTC time
    args = ap.parse_args()

    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    provider, demo = make_provider(args.demo)
    provider.now = now
    print(f"Sim Pickens · {'DEMO DATA' if demo else 'live odds'} · {now.isoformat(timespec='minutes')}")

    index = load(os.path.join(DATA, "index.json"), {"days": []})
    if index.get("days") and index.get("demo") != demo:
        # Switching between demo and real data: start the record fresh.
        print("Data source changed (demo <-> live): clearing old picks and record.")
        shutil.rmtree(DAYS, ignore_errors=True)
        index = {"days": []}
        save(os.path.join(DATA, "record.json"), {"picks": []})

    record = load(os.path.join(DATA, "record.json"), {"picks": []})
    grade_record(record, provider, now)

    today = now.astimezone(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d")
    day_path = os.path.join(DAYS, f"{today}.json")
    if args.command == "daily" and (args.force or not os.path.exists(day_path)):
        events, selections, picks, by_sport = build_slate(provider, now)
    else:
        events = None
    if events == []:
        print(f"{today}: no games with enough odds yet. Nothing saved, so the next run will try again.")
    elif events:
        day = {
            "date": today, "generated": now.isoformat(timespec="seconds"), "demo": demo,
            "n_sims": config.N_SIMS * len(events), "events": events,
            "picks": [clean(p, i) for i, p in enumerate(picks)],
            # The best picks within each sport, for the sport filter on the site.
            "by_sport": {sp: [clean(p, i) for i, p in enumerate(lst)] for sp, lst in by_sport.items()},
            # Every priced bet at its best price, for the Quick Pick parlay builder.
            "bets": [{"e": s["event"], "s": s["sport"], "c": s["cat"], "m": s["market"], "l": s["label"],
                      "o": s["odds"], "b": s["book_title"], "w": r4(s["win"]), "p": r4(s["push"]), "v": r4(s["ev"])}
                     for s in selections],
        }
        save(day_path, day)
        # Add today's picks to the record (replacing any earlier run of today).
        record["picks"] = [p for p in record["picks"] if p["date"] != today]
        for p in day["picks"]:
            ev = events[p["event"]]
            record["picks"].append({
                "date": today, "rank": p["rank"], "sport": p["sport"], "sport_key": ev["sport_key"],
                "label": p["label"], "matchup": ev["label"], "home": ev["home"], "away": ev["away"],
                "start": ev["start"], "event_id": ev["id"], "odds": p["odds"], "book": p["book_title"],
                "win": p["win"], "ev": p["ev"], "grade": p["grade"], "result": "pending",
            })
        print(f"{today}: {len(events)} events, {len(selections)} bets priced, {len(picks)} picks")
        if today not in index["days"]:
            index["days"].append(today)
    elif args.command == "daily":
        print(f"{today}: picks already made (use --force to redo)")

    summarize(record)
    save(os.path.join(DATA, "record.json"), record)
    index["days"] = sorted(set(index["days"]), reverse=True)
    index.update({"demo": demo, "last_run": now.isoformat(timespec="seconds"), "timezone": config.TIMEZONE,
                  "credits_remaining": provider.credits_remaining, "credits_used_last_run": provider.credits_used,
                  "sport_names": config.SPORT_NAMES})
    save(os.path.join(DATA, "index.json"), index)
    if provider.credits_remaining is not None:
        print(f"Odds API credits used this run: {provider.credits_used}, left this month: {provider.credits_remaining}")


if __name__ == "__main__":
    main()
