# Sim Pickens

Daily sports picks from 10,000 simulations per game, priced against every major US sportsbook.

Every morning a GitHub Action pulls real odds from The Odds API, runs the sims, saves
the Top 10 and grades the previous days' picks. GitHub Pages serves the website from
the `docs` folder. Until an `ODDS_API_KEY` secret is added, it runs on demo data.

The step-by-step setup guide is the "Sim Pickens: Going Live" document that came with this project.

## What's where

| Path | What it does |
| --- | --- |
| `simpickens/config.py` | **Settings.** Sports, props, which books, EV limits, run size. The one file meant to be edited. |
| `simpickens/odds_api.py` | Fetches odds and final scores from The Odds API. |
| `simpickens/model.py` | The math: no-vig odds, game simulators, player-stat distributions. Your own projections plug in here. |
| `simpickens/engine.py` | Prices every bet at every book and picks the Top 10. |
| `simpickens/grader.py` | Grades picks won/lost/push and keeps the record. |
| `simpickens/espn.py` | Player box scores for grading props (free ESPN feeds). |
| `simpickens/demo.py` | Made-up games in The Odds API's format, used with no key. |
| `results_manual.json` | Grade fights or stuck picks by hand: `"2026-10-18 #4": "won"`. |
| `docs/` | The website. `docs/data/` is written by the daily run. |
| `.github/workflows/daily.yml` | The daily schedule (GitHub Actions). |

## Running it on your own computer (optional)

You don't need this to run the site. It's handy for testing changes or learning the code.

```bash
pip install -r requirements.txt
python -m simpickens daily            # demo data
ODDS_API_KEY=your_key python -m simpickens daily --force   # real odds (Mac/Linux)
python -m http.server --directory docs 8000    # then open http://localhost:8000
```

## How a pick is made

1. Each book's two-way prices are turned into fair (no-vig) probabilities.
2. The game simulator is tuned until its results match the consensus of all books
   (spreads and totals for one sim, moneylines for another). Player props use the
   consensus of the other books with the pick's own book left out.
3. 10,000 simulations price every line at every book. EV per $1 = win% × (decimal odds − 1) − loss%.
4. Bets between +1% and +12% EV qualify; the best ten (max two per game) make the board.

For entertainment and educational purposes only. 21+. 1-800-GAMBLER.
