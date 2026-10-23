"""Tests for selection.py (the rules for inspecting an event). Run:  python3 test_selection.py"""
import selection


def playing_state(**extra):
    return dict({"selected_event_id": None, "playing": True, "match_sec": 1200, "last_wall": 0.0}, **extra)


def test_selecting_an_allowed_event_pauses_the_match():
    state = playing_state()
    assert selection.select(state, 42, allowed=True) is True
    assert state["selected_event_id"] == 42 and state["playing"] is False
    print("ok  selecting an event pauses the match")


def test_a_disallowed_event_is_not_selected():
    state = playing_state(selected_event_id=7)
    assert selection.select(state, 42, allowed=False) is False
    assert state["selected_event_id"] == 7 and state["playing"] is True   # nothing changed
    print("ok  an event the view does not allow is ignored")


def test_back_to_live_resumes_and_closes_the_inspector():
    state = playing_state(selected_event_id=42, playing=False)
    selection.back_to_live(state, finished=False)
    assert state["selected_event_id"] is None and state["playing"] is True and state["last_wall"] > 0
    over = playing_state(selected_event_id=42, playing=False)
    selection.back_to_live(over, finished=True)
    assert over["selected_event_id"] is None and over["playing"] is False   # a finished match stays paused
    print("ok  Back to live resumes (unless the match is over)")


def test_restart_clears_the_selection():
    state = playing_state(selected_event_id=42, playing=False)
    selection.restart(state)
    assert state["selected_event_id"] is None and state["match_sec"] == 0 and state["playing"] is True
    print("ok  Restart clears the selection and starts over")


def test_jumping_pauses_and_drops_a_selection_from_the_future():
    state = playing_state(selected_event_id=42)
    selection.jump_to(state, 600, selected_second=1500)      # the selected event is at 1500 s
    assert state["match_sec"] == 600 and state["playing"] is False and state["selected_event_id"] is None
    keep = playing_state(selected_event_id=42)
    selection.jump_to(keep, 2000, selected_second=1500)      # still in the past: kept
    assert keep["selected_event_id"] == 42
    moved = playing_state(selected_event_id=42)
    selection.jump_to(moved, 900, event_id=99, allowed=True, selected_second=1500)
    assert moved["selected_event_id"] == 99 and moved["playing"] is False
    refused = playing_state(selected_event_id=42)
    selection.jump_to(refused, 900, event_id=99, allowed=False, selected_second=500)
    assert refused["selected_event_id"] == 42                # not allowed: the old selection stays
    print("ok  the scrubber and moment buttons pause, select, and drop selections from the future")


if __name__ == "__main__":
    test_selecting_an_allowed_event_pauses_the_match()
    test_a_disallowed_event_is_not_selected()
    test_back_to_live_resumes_and_closes_the_inspector()
    test_restart_clears_the_selection()
    test_jumping_pauses_and_drops_a_selection_from_the_future()
    print("all selection tests passed")
