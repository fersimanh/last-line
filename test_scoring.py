"""Tests for the shot-situation parts of scoring.py. Run:  python3 test_scoring.py"""
from scoring import MatchState, saveability

# A plain shot from 14 m, on target, keeper on the line (attacking frame: goal at x = 105)
BASE = {
    "type": "shot", "outcome": "saved", "x": 91.0, "y": 34.0, "distance_m": 14.0,
    "speed_kmh": 95, "end_y": 35.5, "end_z": 0.8, "keeper_x": 104.0, "keeper_y": 34.0,
    "body_part": "foot", "deflected": False, "swerve": 0.2, "defenders_in_lane": 0,
    "keeper_set": True, "situation": "open_play", "assist_seconds": 3, "ball_shift_m": 0.0,
    "seconds_since_keeper_action": None,
}


def score(**changes):
    return saveability(dict(BASE, **changes))[0]


def test_keeper_who_just_acted_scores_lower():
    rested = score()
    just_saved = score(seconds_since_keeper_action=1)
    assert just_saved < rested, (just_saved, rested)
    assert score(seconds_since_keeper_action=10) == rested  # fully recovered after 4.5 s
    print(f"ok  a keeper who acted 1 s ago scores {just_saved}, a rested one {rested}")


def test_ball_moved_across_makes_it_harder():
    straight = score()
    square = score(ball_shift_m=12.0, assist_seconds=1)   # 12 m across in 1 second
    slow = score(ball_shift_m=12.0, assist_seconds=6)     # same distance, plenty of time
    assert square < slow < straight, (square, slow, straight)
    print(f"ok  a fast square pass scores {square}, a slow switch {slow}, no switch {straight}")


def test_coming_out_is_right_one_on_one():
    out_1v1 = score(situation="one_on_one", keeper_x=98.0)      # 7 m off the line
    line_1v1 = score(situation="one_on_one", keeper_x=104.0)    # stayed on the line
    out_open = score(situation="open_play", keeper_x=98.0)
    assert out_1v1 > line_1v1, (out_1v1, line_1v1)
    assert out_1v1 > out_open, (out_1v1, out_open)
    print(f"ok  one on one, coming out scores {out_1v1} vs {line_1v1} staying home")


def test_old_match_files_still_score():
    old = {k: v for k, v in BASE.items()
           if k not in ("situation", "assist_seconds", "ball_shift_m", "seconds_since_keeper_action")}
    assert saveability(old)[0] is not None
    print("ok  shots without the new fields still score")


def test_close_downs_count_as_workload():
    state = MatchState("A", "B")
    state.update({"minute": 1, "second": 0, "type": "keeper_close_down", "team": "A",
                  "player": "Keeper", "x": 99.0, "y": 34.0, "target_player": "X"})
    assert state.keeper_report()["A"]["close_downs"] == 1
    assert state.workload("A") == 1
    print("ok  close-downs count toward workload")


def test_insight_carries_the_situation():
    state = MatchState("A", "B")
    shot = dict(BASE, minute=1, second=0, team="B", player="P", keeper="K", situation="rebound")
    assert state.update(shot)["situation"] == "rebound"
    print("ok  the shot insight carries the situation")


if __name__ == "__main__":
    test_keeper_who_just_acted_scores_lower()
    test_ball_moved_across_makes_it_harder()
    test_coming_out_is_right_one_on_one()
    test_old_match_files_still_score()
    test_close_downs_count_as_workload()
    test_insight_carries_the_situation()
    print("all scoring tests passed")
