"""
The math: odds conversion, removing the vig, the game simulators and the
player-stat distributions.

How a game is simulated
-----------------------
1. Every book's moneyline, spread and total is turned into a fair (no-vig)
   probability.
2. The simulator's two settings for the game (how many points each team
   scores on average) are tuned until the simulated games agree with that
   market consensus.
3. 10,000 games are played with those settings. For every line every book
   offers, the share of games where the bet wins is its sim win probability.

To add your own opinion to a game (an injury the market hasn't priced in,
weather, a model of your own), change mu_home / mu_away after fit_game()
and before simulate_game(). That's where a stats-based model plugs in.
"""
import math

import numpy as np


# ---------- odds ----------

def to_decimal(american):
    return 1 + american / 100 if american > 0 else 1 + 100 / -american


def to_american(decimal):
    if decimal >= 2:
        return int(round((decimal - 1) * 100))
    return int(round(-100 / (decimal - 1)))


def no_vig(price_a, price_b):
    """Fair probability of side A from a two-way market (both prices American)."""
    ia, ib = 1 / to_decimal(price_a), 1 / to_decimal(price_b)
    return ia / (ia + ib)


def grade_probs(values, side, line):
    """Win / push / lose shares for an over-under style bet on an array of outcomes.
    side 'over' wins when value > line; 'under' wins when value < line."""
    if side == "over":
        win = np.mean(values > line)
        lose = np.mean(values < line)
    else:
        win = np.mean(values < line)
        lose = np.mean(values > line)
    return float(win), float(1 - win - lose), float(lose)


# ---------- game simulators ----------
# Each returns (home_score, away_score) arrays of length n.
# rng is a numpy Generator; passing the same seed gives the same games, which
# keeps the tuning step stable.

def _sim_nba(mu_h, mu_a, n, rng):
    # Shared pace moves both scores together; each team then varies on its own.
    # Gives a margin spread of about 13 points, close to real NBA games.
    pace = 1 + 0.04 * rng.standard_normal(n)
    h = np.rint(mu_h * pace + 9.5 * rng.standard_normal(n))
    a = np.rint(mu_a * pace + 9.5 * rng.standard_normal(n))
    tie = h == a
    while tie.any():                                   # overtime periods
        k = int(tie.sum())
        h[tie] += np.maximum(0, np.rint(6 + 3 * rng.standard_normal(k)))
        a[tie] += np.maximum(0, np.rint(6 + 3 * rng.standard_normal(k)))
        tie = h == a
    return h, a


def _nfl_team(mu, n, rng):
    # Each team gets about 11 drives; each drive ends in a touchdown, a field
    # goal or nothing. Building scores this way puts margins on football's key
    # numbers (3, 7, 10) the way real games land.
    drives = 11
    p_td = min(0.6, 0.72 * mu / 6.94 / drives)
    p_fg = min(0.35, 0.28 * mu / 3 / drives)
    out = rng.multinomial(drives, [p_td, p_fg, 1 - p_td - p_fg], size=n)
    tds, fgs = out[:, 0], out[:, 1]
    missed_xp = rng.binomial(tds, 0.06)
    safety = (rng.random(n) < 0.02) * 2
    return 7 * tds - missed_xp + 3 * fgs + safety


def _sim_nfl(mu_h, mu_a, n, rng):
    h = _nfl_team(mu_h, n, rng).astype(float)
    a = _nfl_team(mu_a, n, rng).astype(float)
    tie = h == a
    k = int(tie.sum())
    if k:
        decided = rng.random(k) < 0.93                  # about 7% of OT games end tied
        home_wins = rng.random(k) < np.clip(0.5 + (mu_h - mu_a) * 0.02, 0.2, 0.8)
        pts = np.where(rng.random(k) < 0.7, 3, 6)
        idx = np.flatnonzero(tie)
        h[idx] += np.where(decided & home_wins, pts, 0)
        a[idx] += np.where(decided & ~home_wins, pts, 0)
    return h, a


def _sim_mlb(mu_h, mu_a, n, rng):
    h = rng.poisson(mu_h * rng.gamma(6, 1 / 6, n)).astype(float)
    a = rng.poisson(mu_a * rng.gamma(6, 1 / 6, n)).astype(float)
    tie = h == a
    k = int(tie.sum())
    if k:                                               # extra innings
        home_wins = rng.random(k) < mu_h / (mu_h + mu_a)
        idx = np.flatnonzero(tie)
        h[idx] += home_wins
        a[idx] += ~home_wins
    return h, a


def _sim_nhl(mu_h, mu_a, n, rng):
    h = rng.poisson(mu_h, n).astype(float)
    a = rng.poisson(mu_a, n).astype(float)
    tie = h == a
    k = int(tie.sum())
    if k:                                               # overtime / shootout
        home_wins = rng.random(k) < np.clip(0.5 + (mu_h - mu_a) * 0.15, 0.3, 0.7)
        idx = np.flatnonzero(tie)
        h[idx] += home_wins
        a[idx] += ~home_wins
    return h, a


SIMULATORS = {"NBA": _sim_nba, "NFL": _sim_nfl, "MLB": _sim_mlb, "NHL": _sim_nhl}
# Typical points per team, used as the starting guess when tuning.
TYPICAL = {"NBA": 114.0, "NFL": 22.0, "MLB": 4.4, "NHL": 3.0}


def simulate_game(sport, mu_h, mu_a, n, seed):
    rng = np.random.default_rng(seed)
    h, a = SIMULATORS[sport](mu_h, mu_a, n, rng)
    return {"home": h, "away": a, "margin": h - a, "total": h + a}


def _bisect(f, lo, hi, iters=28):
    """Find x in [lo, hi] where the increasing function f(x) crosses 0."""
    flo, fhi = f(lo), f(hi)
    if flo > 0:
        return lo
    if fhi < 0:
        return hi
    for _ in range(iters):
        mid = (lo + hi) / 2
        if f(mid) < 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def fit_game(sport, targets, seed, n=6000, use="spread"):
    """
    Tune average points (home, away) so simulated games match the market.

    targets = {
      "ml":     fair home win probability (or None),
      "spread": list of (home_line, fair_home_cover_prob),
      "total":  list of (line, fair_over_prob),
    }
    use = "spread" tunes the winning margin to the spreads, "ml" to the moneyline.
    Spread bets are priced with a spread-tuned sim and moneylines with an
    ml-tuned one, so a mismatch between the two markets can't pose as an edge.
    """
    base = TYPICAL[sport]
    level, diff = 2 * base, 0.0
    floor = 0.25 if sport in ("MLB", "NHL") else 1.0

    def sims(lv, df):
        mh = max(floor, (lv + df) / 2)
        ma = max(floor, (lv - df) / 2)
        return simulate_game(sport, mh, ma, n, seed)

    def total_gap(lv):
        g = sims(lv, diff)
        out = []
        for line, q in targets["total"]:
            w, p, l = grade_probs(g["total"], "over", line)
            out.append(w / max(1e-9, w + l) - q)
        return float(np.mean(out))

    def margin_gap(df):
        g = sims(level, df)
        use_spread = (use == "spread" and targets["spread"]) or targets["ml"] is None
        if use_spread:
            out = []
            for home_line, q in targets["spread"]:
                w, p, l = grade_probs(g["margin"] + home_line, "over", 0)
                out.append(w / max(1e-9, w + l) - q)
            return float(np.mean(out)) if out else 0.0
        w = float(np.mean(g["margin"] > 0))
        l = float(np.mean(g["margin"] < 0))
        return w / max(1e-9, w + l) - targets["ml"]

    span = {"NBA": 40, "NFL": 30, "MLB": 6, "NHL": 4}[sport]
    for _ in range(3):
        if targets["total"]:
            level = _bisect(total_gap, 2 * base * 0.6, 2 * base * 1.4, iters=22)
        if targets["spread"] or targets["ml"] is not None:
            diff = _bisect(margin_gap, -span, span, iters=22)
    return max(floor, (level + diff) / 2), max(floor, (level - diff) / 2)


# ---------- player props ----------
# Each stat has a distribution family. "norm" is a rounded normal whose spread
# grows with the average (a + b * mean). "pois" is a count (Poisson).

PROP_STATS = {
    # market key:            (label, family, sd_slope, sd_floor)
    "player_points":         ("Points", "norm", 0.25, 2.5),
    "player_rebounds":       ("Rebounds", "pois", 0, 0),
    "player_assists":        ("Assists", "pois", 0, 0),
    "player_pass_yds":       ("Passing Yds", "norm", 0.22, 15),
    "player_rush_yds":       ("Rushing Yds", "norm", 0.45, 6),
    "player_reception_yds":  ("Receiving Yds", "norm", 0.5, 6),
    "pitcher_strikeouts":    ("Strikeouts", "pois", 0, 0),
    "batter_hits":           ("Hits", "pois", 0, 0),
    "player_shots_on_goal":  ("Shots on Goal", "pois", 0, 0),
    "player_total_saves":    ("Saves", "pois", 0, 0),
}


def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _pois_cdf(k, lam):
    """P(X <= k) for a Poisson count."""
    if k < 0:
        return 0.0
    term = total = math.exp(-lam)
    for i in range(1, int(k) + 1):
        term *= lam / i
        total += term
    return min(1.0, total)


def prop_over_share(market, mean, line):
    """Fair over probability (pushes removed) for a player whose average is `mean`."""
    _, fam, a, b = PROP_STATS[market]
    hi = math.floor(line) + 1                 # smallest value that beats the line
    lo = math.ceil(line) - 1                  # largest value that loses to it
    if fam == "norm":
        sd = a * mean + b
        over = 1 - _norm_cdf((hi - 0.5 - mean) / sd)
        under = _norm_cdf((lo + 0.5 - mean) / sd)
    else:
        over = 1 - _pois_cdf(hi - 1, mean)
        under = _pois_cdf(lo, mean)
    return over / max(1e-12, over + under)


def fit_prop_mean(market, line, fair_over):
    """The player average that makes P(over) equal the book's no-vig price."""
    return _bisect(lambda m: prop_over_share(market, m, line) - fair_over, 0.01, max(5.0, line * 4 + 10), iters=40)


def simulate_prop(market, mean, n, seed):
    _, fam, a, b = PROP_STATS[market]
    rng = np.random.default_rng(seed)
    if fam == "norm":
        return np.maximum(0, np.rint(mean + (a * mean + b) * rng.standard_normal(n)))
    return rng.poisson(mean, n).astype(float)


# ---------- summaries for the site ----------

def histogram(values, max_bins=34):
    """Compact histogram of simulated outcomes for the 'Why it ranked' chart."""
    v = np.asarray(values)
    lo, hi = np.percentile(v, [0.5, 99.5])
    lo, hi = math.floor(lo), math.ceil(hi)
    span = hi - lo + 1
    width = max(1, math.ceil(span / max_bins))
    start = lo - (lo % width) if width > 1 else lo
    bins = math.ceil((hi + 1 - start) / width)
    idx = np.clip(((v - start) // width).astype(int), 0, bins - 1)
    counts = np.bincount(idx, minlength=bins)
    return {"start": int(start), "width": int(width), "counts": counts.tolist(), "mean": round(float(v.mean()), 2)}
