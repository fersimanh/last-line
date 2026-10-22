"""Tests for app.py with Streamlit's AppTest (no browser needed).

Run:  python3 test_app.py
The agents are switched off here, so the tests never call Azure: texts come
from insight_cache.json or the fallback line.
"""
import os

os.environ["LAST_LINE_LIVE_AGENTS"] = "0"  # must be set before the app imports insights.py

from streamlit.testing.v1 import AppTest  # noqa: E402

from insights import match_second  # noqa: E402
from replay import load_match  # noqa: E402

_, EVENTS = load_match()
END_SEC = match_second(EVENTS[-1])


def new_app():
    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    return at


def all_markdown(at):
    return "\n".join(m.value for m in at.markdown)


def card_count(at):
    """Each insight card starts with a bold clock, like **67:03** ·"""
    return sum(1 for m in at.markdown if m.value.startswith("**") and "** · **" in m.value)


def test_starts_paused_at_kickoff():
    at = new_app()
    assert at.session_state.match_sec == 0
    assert at.session_state.playing is False
    assert "Harbor United 0 – 0 Northgate FC" in all_markdown(at)
    assert card_count(at) == 0
    assert len(at.tabs) == 2
    print("ok  starts paused at kickoff")


def test_mid_match_cards_and_charts():
    at = new_app()
    at.session_state.match_sec = 4100  # 68:20, just after the 67:03 goal
    at.run()
    assert not at.exception, at.exception
    text = all_markdown(at)
    assert "Harbor United 1 – 2 Northgate FC" in text
    assert "**67:03** · **Goal conceded** · Marco Tesch" in text
    # Default club is Harbor United, so only moments at Harbor's goal show:
    # goals at 11:16 and 67:03, saves at 31:58 and 56:16
    assert card_count(at) == 4, card_count(at)
    assert len(at.get("plotly_chart")) == 2  # shot map + goal mouth
    print("ok  mid-match cards and charts")


def test_switching_options_keeps_position():
    at = new_app()
    at.session_state.match_sec = 4100
    at.run()
    at.radio(key="language").set_value("Español").run()
    assert not at.exception, at.exception
    assert at.session_state.match_sec == 4100  # the match did not restart
    assert "**67:03** · **Gol encajado** · Marco Tesch" in all_markdown(at)

    at.radio(key="mode").set_value("Analyst").run()
    at.selectbox(key="club").set_value("Both").run()
    assert not at.exception, at.exception
    assert at.session_state.match_sec == 4100
    assert card_count(at) == 15, card_count(at)            # both goals now
    assert len(at.get("plotly_chart")) == 4               # two maps, two goal mouths
    print("ok  switching options keeps the match position")


def test_play_pause_restart():
    at = new_app()
    at.session_state.match_sec = 600
    at.button(key="play").click().run()
    assert not at.exception, at.exception
    assert at.session_state.match_sec > 600, at.session_state.match_sec  # the clock moved
    at.button(key="pause").click().run()
    paused_at = at.session_state.match_sec
    at.run()
    assert at.session_state.playing is False
    assert at.session_state.match_sec == paused_at
    at.button(key="restart").click()
    at.session_state.playing = False  # stop the loop right after the restart
    print("ok  play, pause and restart")


def test_full_time_report():
    at = new_app()
    at.session_state.match_sec = END_SEC
    at.selectbox(key="club").set_value("Both").run()
    assert not at.exception, at.exception
    text = all_markdown(at)
    assert "Harbor United 1 – 3 Northgate FC" in text
    labels = [m.label for m in at.metric]
    assert labels.count("Goals prevented") == 2, labels
    print("ok  full-time report")


if __name__ == "__main__":
    test_starts_paused_at_kickoff()
    test_mid_match_cards_and_charts()
    test_switching_options_keeps_position()
    test_play_pause_restart()
    test_full_time_report()
    print("all tests passed")
