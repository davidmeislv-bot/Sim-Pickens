"""Checks the ESPN box score parser on a small sample in ESPN's layout."""
from simpickens.espn import parse_box

SAMPLE = {"boxscore": {"players": [
    {"team": {"displayName": "Los Angeles Lakers"}, "statistics": [
        {"names": ["MIN", "PTS", "REB", "AST"], "keys": ["minutes", "points", "rebounds", "assists"],
         "labels": ["MIN", "PTS", "REB", "AST"],
         "athletes": [{"athlete": {"displayName": "LeBron James"}, "stats": ["36", "28", "9", "11"]},
                      {"athlete": {"displayName": "Bench Guy"}, "stats": []}]}]},
    {"team": {"displayName": "Kansas City Chiefs"}, "statistics": [
        {"name": "passing", "keys": ["completions/passingAttempts", "passingYards"], "labels": ["C/ATT", "YDS"],
         "athletes": [{"athlete": {"displayName": "Patrick Mahomes II"}, "stats": ["24/35", "291"]}]},
        {"name": "rushing", "keys": ["rushingAttempts", "rushingYards"], "labels": ["CAR", "YDS"],
         "athletes": [{"athlete": {"displayName": "Isiah Pacheco"}, "stats": ["18", "77"]}]}]},
    {"team": {"displayName": "Dodgers"}, "statistics": [
        {"type": "batting", "labels": ["H-AB", "AB", "R", "H", "K"], "keys": ["hits-atBats", "atBats", "runs", "hits", "strikeouts"],
         "athletes": [{"athlete": {"displayName": "Mookie Betts"}, "stats": ["2-4", "4", "1", "2", "1"]}]},
        {"type": "pitching", "labels": ["IP", "H", "K"], "keys": ["fullInnings.partInnings", "hits", "strikeouts"],
         "athletes": [{"athlete": {"displayName": "Yoshinobu Yamamoto"}, "stats": ["6.0", "4", "8"]}]}]},
]}}


def test_parse():
    box = parse_box(SAMPLE)
    assert box["lebron james"] == {"player_points": 28, "player_rebounds": 9, "player_assists": 11}
    assert box["patrick mahomes"]["player_pass_yds"] == 291
    assert box["isiah pacheco"]["player_rush_yds"] == 77
    assert box["mookie betts"]["batter_hits"] == 2
    assert box["yoshinobu yamamoto"]["pitcher_strikeouts"] == 8
    assert "batter_hits" not in box["yoshinobu yamamoto"]
    assert "bench guy" not in box


if __name__ == "__main__":
    test_parse()
    print("ok")
