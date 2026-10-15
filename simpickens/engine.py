"""
Turns raw odds into priced bets and the daily Top 10.

Input: a list of events in The Odds API's format (each with bookmakers ->
markets -> outcomes). Output: one row per bet selection, holding the best
price available, the sim win probability, the EV and the details the site
shows under "Why it ranked".
"""
import hashlib
import statistics
from datetime import datetime, timedelta, timezone

import numpy as np

from . import config
from .model import (PROP_STATS, fit_game, fit_prop_mean, grade_probs, histogram,
                    no_vig, simulate_game, simulate_prop, to_decimal)

TEAM_SPORTS = ("NBA", "NFL", "MLB", "NHL")


def seed_for(*parts):
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


def parse_time(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def fresh(market, now):
    """False if this book hasn't updated the market recently (likely a stale line)."""
    stamp = market.get("last_update")
    if not stamp:
        return True
    return now - parse_time(stamp) <= timedelta(minutes=config.STALE_MINUTES)


def fmt_line(x):
    return f"{x:+g}" if x else "PK"


def bet_stats(values, side, line, price, n_batches=10):
    """Win/push/lose shares, EV per $1, and how many of 10 batches came out +EV."""
    w, p, l = grade_probs(values, side, line)
    d = to_decimal(price)
    ev = w * (d - 1) - l
    pos = 0
    for chunk in np.array_split(values, n_batches):
        cw, cp, cl = grade_probs(chunk, side, line)
        pos += cw * (d - 1) - cl > 0
    return w, p, l, ev, int(pos)


def confidence(pos_batches, n_other_books):
    return int(round(50 * pos_batches / 10 + 50 * min(n_other_books / 6, 1)))


# ---------- team sports ----------

def collect_team_markets(ev, now):
    """Per book: moneyline, spread and total prices, oriented to the home team."""
    home, away = ev["home_team"], ev["away_team"]
    books = {}
    for bk in ev.get("bookmakers", []):
        row = {"title": bk["title"]}
        for m in bk.get("markets", []):
            if not fresh(m, now):
                continue
            by_name = {x["name"]: x for x in m["outcomes"]}
            if m["key"] == "h2h" and home in by_name and away in by_name:
                row["ml"] = (by_name[home]["price"], by_name[away]["price"])
            elif m["key"] == "spreads" and home in by_name and away in by_name:
                h, a = by_name[home], by_name[away]
                if h.get("point") is not None and abs(h["point"] + a["point"]) < 1e-9:
                    row["spread"] = (h["point"], h["price"], a["price"])
            elif m["key"] == "totals" and "Over" in by_name and "Under" in by_name:
                ov, un = by_name["Over"], by_name["Under"]
                if ov.get("point") == un.get("point"):
                    row["total"] = (ov["point"], ov["price"], un["price"])
        books[bk["key"]] = row
    return books


def price_team_event(ev, sport, now):
    books = collect_team_markets(ev, now)
    ml = [no_vig(*b["ml"]) for b in books.values() if "ml" in b]
    spreads = [(b["spread"][0], no_vig(b["spread"][1], b["spread"][2])) for b in books.values() if "spread" in b]
    totals = [(b["total"][0], no_vig(b["total"][1], b["total"][2])) for b in books.values() if "total" in b]
    if len(ml) + len(spreads) < config.MIN_BOOKS:
        return [], None
    targets = {"ml": statistics.median(ml) if ml else None, "spread": spreads, "total": totals}
    seed = seed_for(ev["id"], "fit")
    mu_h, mu_a = fit_game(sport, targets, seed, use="spread")
    # ---- Your own adjustments to the projection would go here (see model.py). ----
    sims = simulate_game(sport, mu_h, mu_a, config.N_SIMS, seed_for(ev["id"], "sim"))
    ml_sims = sims
    if ml and spreads:
        ml_h, ml_a = fit_game(sport, targets, seed, use="ml")
        ml_sims = simulate_game(sport, ml_h, ml_a, config.N_SIMS, seed_for(ev["id"], "sim"))

    home, away = ev["home_team"], ev["away_team"]
    n_ml, n_sp, n_tot = len(ml), len(spreads), len(totals)
    rows = []

    def add(book_key, b, market, cat, label, values, side, line, price, book_fair, n_books, grade):
        w, p, l, evv, pos = bet_stats(values, side, line, price)
        rows.append({
            "sel": f"{ev['id']}|{market}|{label}", "book": book_key, "book_title": b["title"],
            "market": market, "cat": cat, "label": label, "odds": price,
            "win": w, "push": p, "lose": l, "ev": evv, "batches": pos,
            "book_fair": book_fair, "n_books": n_books, "grade": grade,
        })

    for key, b in books.items():
        if "ml" in b:
            ph, pa = b["ml"]
            fair = no_vig(ph, pa)
            add(key, b, "Moneyline", "sides", f"{home} ML", ml_sims["margin"], "over", 0, ph, fair, n_ml,
                {"kind": "ml", "team": home})
            add(key, b, "Moneyline", "sides", f"{away} ML", -ml_sims["margin"], "over", 0, pa, 1 - fair, n_ml,
                {"kind": "ml", "team": away})
        if "spread" in b:
            hp, hpr, apr = b["spread"]
            fair = no_vig(hpr, apr)
            name = {"MLB": "Run line", "NHL": "Puck line"}.get(sport, "Spread")
            add(key, b, name, "sides", f"{home} {fmt_line(hp)}", sims["margin"] + hp, "over", 0, hpr, fair, n_sp,
                {"kind": "spread", "team": home, "point": hp})
            add(key, b, name, "sides", f"{away} {fmt_line(-hp)}", -sims["margin"] - hp, "over", 0, apr, 1 - fair, n_sp,
                {"kind": "spread", "team": away, "point": -hp})
        if "total" in b:
            t, op, up = b["total"]
            fair = no_vig(op, up)
            add(key, b, "Game total", "totals", f"Over {t:g}", sims["total"], "over", t, op, fair, n_tot,
                {"kind": "total", "side": "over", "point": t})
            add(key, b, "Game total", "totals", f"Under {t:g}", sims["total"], "under", t, up, 1 - fair, n_tot,
                {"kind": "total", "side": "under", "point": t})

    projection = {"mu_home": round(mu_h, 2), "mu_away": round(mu_a, 2),
                  "ml_consensus": round(targets["ml"], 4) if ml else None}
    return rows, {"sims": sims, "ml_sims": ml_sims, "projection": projection}


# ---------- player props ----------

def price_props(ev, sport, prop_event, now):
    """prop_event is the same event re-fetched with player prop markets."""
    groups = {}   # (market, player) -> {book: (line, over_price, under_price, title)}
    for bk in (prop_event or {}).get("bookmakers", []):
        for m in bk.get("markets", []):
            if m["key"] not in PROP_STATS or not fresh(m, now):
                continue
            pairs = {}
            for o in m["outcomes"]:
                player = o.get("description")
                if player and o.get("point") is not None:
                    pairs.setdefault((player, o["point"]), {})[o["name"]] = o["price"]
            for (player, line), sides in pairs.items():
                if "Over" in sides and "Under" in sides:
                    groups.setdefault((m["key"], player), {})[bk["key"]] = (line, sides["Over"], sides["Under"], bk["title"])

    rows, extras = [], {}
    for (market, player), books in groups.items():
        if len(books) < config.MIN_BOOKS:
            continue
        means = {k: fit_prop_mean(market, v[0], no_vig(v[1], v[2])) for k, v in books.items()}
        stat = PROP_STATS[market][0]
        all_mean = statistics.median(means.values())
        extras[(market, player)] = simulate_prop(market, all_mean, config.N_SIMS, seed_for(ev["id"], market, player, "all"))
        for key, (line, op, up, title) in books.items():
            others = [m for k, m in means.items() if k != key]
            mean = statistics.median(others)       # consensus without this book
            values = simulate_prop(market, mean, config.N_SIMS, seed_for(ev["id"], market, player, key))
            fair = no_vig(op, up)
            for side, price, bf in (("over", op, fair), ("under", up, 1 - fair)):
                w, p, l, evv, pos = bet_stats(values, side, line, price)
                label = f"{player} {side.title()} {line:g} {stat}"
                rows.append({
                    "sel": f"{ev['id']}|{market}|{label}", "book": key, "book_title": title,
                    "market": "Player prop", "cat": "props", "label": label, "odds": price,
                    "win": w, "push": p, "lose": l, "ev": evv, "batches": pos,
                    "book_fair": bf, "n_books": len(books), "mean": round(mean, 2),
                    "grade": {"kind": "prop", "player": player, "market": market, "side": side, "point": line},
                    "hist_key": (market, player),
                })
    return rows, extras


# ---------- fights ----------

def price_fight(ev, sport, now):
    a, b = ev["home_team"], ev["away_team"]
    books = {}
    for bk in ev.get("bookmakers", []):
        for m in bk.get("markets", []):
            if m["key"] != "h2h" or not fresh(m, now):
                continue
            by = {x["name"]: x["price"] for x in m["outcomes"]}
            if a in by and b in by:
                books[bk["key"]] = (by[a], by[b], bk["title"])
    if len(books) < config.MIN_BOOKS:
        return [], None
    fairs = {k: no_vig(v[0], v[1]) for k, v in books.items()}
    rng = np.random.default_rng(seed_for(ev["id"], "fight"))
    u = rng.random(config.N_SIMS)
    rows = []
    for key, (pa, pb, title) in books.items():
        p = statistics.median([f for k, f in fairs.items() if k != key])
        a_wins = (u < p).astype(float)          # 1 = first fighter wins this sim
        for name, price, values, bf in ((a, pa, a_wins, fairs[key]), (b, pb, 1 - a_wins, 1 - fairs[key])):
            w, pu, l, evv, pos = bet_stats(values, "over", 0.5, price)
            rows.append({
                "sel": f"{ev['id']}|ml|{name}", "book": key, "book_title": title,
                "market": "Fight ML", "cat": "sides", "label": f"{name} ML", "odds": price,
                "win": w, "push": pu, "lose": l, "ev": evv, "batches": pos,
                "book_fair": bf, "n_books": len(books), "grade": {"kind": "fight", "fighter": name},
            })
    p_all = statistics.median(fairs.values())
    return rows, {"projection": {"fighter_a_win": round(p_all, 4)}}


# ---------- whole slate ----------

def best_by_selection(rows):
    """Collapse every book's price for the same bet into one row at the best eligible price."""
    groups = {}
    for r in rows:
        groups.setdefault(r["sel"], []).append(r)
    out = []
    for sel, rs in groups.items():
        eligible = [r for r in rs if not config.MY_BOOKS or r["book"] in config.MY_BOOKS]
        if not eligible:
            continue
        best = max(eligible, key=lambda r: (r["ev"], r["odds"]))
        best = dict(best)
        best["prices"] = sorted(({"book": r["book_title"], "odds": r["odds"], "fair": round(r["book_fair"], 4)}
                                 for r in rs), key=lambda x: -to_decimal(x["odds"]))
        out.append(best)
    return out


def top_picks(selections):
    ok = [s for s in selections if config.MIN_EV <= s["ev"] <= config.MAX_EV]
    ok.sort(key=lambda s: (-s["ev"], -s["win"]))
    per_game, picks = {}, []
    for s in ok:
        g = s["event"]
        if per_game.get(g, 0) >= config.MAX_PER_GAME:
            continue
        per_game[g] = per_game.get(g, 0) + 1
        picks.append(s)
        if len(picks) == config.TOP_N:
            break
    return picks


def build_slate(provider, now, log=print):
    """Pull today's odds, simulate every game, and return the day's data for the site."""
    tz = config.TIMEZONE
    from zoneinfo import ZoneInfo
    local_now = now.astimezone(ZoneInfo(tz))
    # Today's games: from now until 4:00 AM tomorrow, local time.
    end_local = (local_now + timedelta(days=1)).replace(hour=4, minute=0, second=0, microsecond=0)
    start_iso = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = end_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    events, all_sel, extras_for = [], [], {}
    active = provider.active_sport_keys()
    for sport, spec in config.SPORTS.items():
        if spec["key"] not in active:
            log(f"{sport}: not in season, skipped")
            continue
        markets = ["h2h"] if sport in ("MMA", "BOX") else ["h2h", "spreads", "totals"]
        games = provider.game_odds(spec["key"], config.REGIONS, markets, start_iso, end_iso)
        log(f"{sport}: {len(games)} events")
        for ev in games:
            if parse_time(ev["commence_time"]) <= now:
                continue
            idx = len(events)
            if sport in TEAM_SPORTS:
                rows, extra = price_team_event(ev, sport, now)
                prop_rows, prop_extra = [], {}
                if config.INCLUDE_PROPS and spec["props"] and rows:
                    if provider.credits_used < config.MAX_CREDITS_PER_RUN:
                        pe = provider.event_odds(spec["key"], ev["id"], config.REGIONS, spec["props"])
                        prop_rows, prop_extra = price_props(ev, sport, pe, now)
                    else:
                        log("  credit limit for this run reached, skipping remaining props")
                rows += prop_rows
            else:
                rows, extra = price_fight(ev, sport, now)
                prop_extra = {}
            if not rows:
                continue
            label = f"{ev['away_team']} @ {ev['home_team']}" if sport in TEAM_SPORTS else f"{ev['home_team']} vs {ev['away_team']}"
            events.append({"id": ev["id"], "sport": sport, "sport_key": config.SPORTS[sport]["key"],
                           "label": label, "home": ev["home_team"], "away": ev["away_team"],
                           "start": ev["commence_time"], "projection": (extra or {}).get("projection")})
            extras_for[idx] = (extra or {}, prop_extra)
            for s in best_by_selection(rows):
                s["event"] = idx
                s["sport"] = sport
                all_sel.append(s)
        log(f"  credits used so far: {provider.credits_used}")

    picks = top_picks(all_sel)
    by_sport = {sp: top_picks([s for s in all_sel if s["sport"] == sp]) for sp in {s["sport"] for s in all_sel}}
    for s in picks + [x for lst in by_sport.values() for x in lst]:   # attach the histogram each pick's chart uses
        if "hist" in s:
            continue
        extra, prop_extra = extras_for[s["event"]]
        g = s["grade"]
        if g["kind"] == "prop":
            s["hist"] = histogram(prop_extra[(g["market"], g["player"])])
        elif g["kind"] in ("ml", "spread") and extra.get("sims") is not None:
            s["hist"] = histogram(extra["ml_sims" if g["kind"] == "ml" else "sims"]["margin"])
            s["hist"]["var"] = "margin"
        elif g["kind"] == "total" and extra.get("sims") is not None:
            s["hist"] = histogram(extra["sims"]["total"])
            s["hist"]["var"] = "total"
    for s in all_sel:
        s.pop("hist_key", None)
    return events, all_sel, picks, by_sport
