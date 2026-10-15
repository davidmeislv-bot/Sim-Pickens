"""
Sim Pickens settings.

This is the one file you're meant to change. Edit it right on GitHub
(open the file, click the pencil icon, change a value, click "Commit changes").
The next daily run uses the new settings.
"""

# Your local time zone. "Today's slate" means games that start between the time
# the program runs and 4:00 AM tomorrow morning in this time zone.
TIMEZONE = "America/Los_Angeles"

# Which sports to run, The Odds API's name for each, and which player props to
# pull. Remove a line to stop running that sport. Each prop market costs
# 1 credit per game, so fewer props = fewer credits used.
SPORTS = {
    "NFL": {"key": "americanfootball_nfl",
            "props": ["player_pass_yds", "player_rush_yds", "player_reception_yds"]},
    "NBA": {"key": "basketball_nba",
            "props": ["player_points", "player_rebounds", "player_assists"]},
    "MLB": {"key": "baseball_mlb",
            "props": ["pitcher_strikeouts", "batter_hits"]},
    "NHL": {"key": "icehockey_nhl",
            "props": ["player_shots_on_goal", "player_total_saves"]},
    "MMA": {"key": "mma_mixed_martial_arts", "props": []},
    "BOX": {"key": "boxing_boxing", "props": []},
}

# Set to False to skip player props entirely (uses far fewer credits).
INCLUDE_PROPS = True

# Which group of sportsbooks to compare. "us" covers DraftKings, FanDuel,
# BetMGM, Caesars/William Hill, BetRivers, Bovada and others.
# "us,us2" adds more books but doubles the credits used.
REGIONS = "us"

# Only recommend bets at these books. Leave the list empty to allow any book.
# Every book is still used to work out the consensus line.
# Example: MY_BOOKS = ["williamhill_us", "draftkings", "fanduel", "betmgm"]
MY_BOOKS = []

# A bet needs at least this many books pricing the same market before the
# consensus is trusted.
MIN_BOOKS = 4

# Picks must have at least this much expected value (0.01 = +1%).
MIN_EV = 0.01

# Anything above this EV is almost always a stale or wrong line, so it's skipped.
MAX_EV = 0.12

# Ignore any book's price that hasn't updated in this many minutes.
STALE_MINUTES = 90

# How many picks make the daily board, and the most from any single game.
TOP_N = 10
MAX_PER_GAME = 2

# Simulations per game.
N_SIMS = 10_000

# Safety limit: stop pulling props if one run has used this many credits.
MAX_CREDITS_PER_RUN = 400

# Display names for the site.
SPORT_NAMES = {"NFL": "NFL", "NBA": "NBA", "MLB": "MLB", "NHL": "NHL", "MMA": "UFC/MMA", "BOX": "Boxing"}
