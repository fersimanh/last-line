"""Tests for app.py with Streamlit's AppTest (no browser needed).

Run:  python3 test_app.py
The agents are switched off here, so the tests never call Azure: texts come
from insight_cache.json or the fallback line. Expected numbers are worked
out from the match file, so the tests still hold after regenerating it.
"""
import os

os.environ["LAST_LINE_LIVE_AGENTS"] = "0"  # must be set before the app imports insights.py

from streamlit.testing.v1 import AppTest  # noqa: E402

from insights import match_second, replay_to  # noqa: E402
from replay import load_match  # noqa: E402

MATCH, EVENTS = load_match()
HOME, AWAY = MATCH["home"], MATCH["away"]
END_SEC = match_second(EVENTS[-1])
MID_SEC = END_SEC // 2 + 600  # a point in the second half


def expected(upto_sec, clubs):
    """Score heading and number of cards the app should show at this moment."""
    _, _, moments, score = replay_to(MATCH, EVENTS, upto_sec)
    home_goals, away_goals = score.split("-")
    heading = f"{HOME} {home_goals} – {away_goals} {AWAY}"
    return heading, sum(1 for m in moments if m["keeper_team"] in clubs), moments


def new_app():
    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    return at


def all_markdown(at):
    return "\n".join(m.value for m in at.markdown)


def card_count(at):
    """Each insight card starts with a bold clock, like **67:03** · **Save**"""
    return sum(1 for m in at.markdown if m.value.startswith("**") and "** · **" in m.value)


def test_starts_paused_at_kickoff():
    at = new_app()
    assert at.session_state.match_sec == 0
    assert at.session_state.playing is False
    assert f"{HOME} 0 – 0 {AWAY}" in all_markdown(at)
    assert card_count(at) == 0
    assert len(at.tabs) == 2
    print("ok  starts paused at kickoff")


def test_mid_match_cards_and_charts():
    at = new_app()
    at.session_state.match_sec = MID_SEC
    at.run()
    assert not at.exception, at.exception
    heading, cards, _ = expected(MID_SEC, [HOME])  # default club is the home side
    assert heading in all_markdown(at)
    assert card_count(at) == cards, (card_count(at), cards)
    assert len(at.get("plotly_chart")) == 2  # shot map + goal mouth
    print(f"ok  mid-match: {heading}, {cards} cards, 2 charts")


def test_switching_options_keeps_position():
    at = new_app()
    at.session_state.match_sec = MID_SEC
    at.run()
    at.radio(key="language").set_value("Español").run()
    assert not at.exception, at.exception
    assert at.session_state.match_sec == MID_SEC  # the match did not restart
    _, cards, moments = expected(MID_SEC, [HOME])
    assert card_count(at) == cards
    spanish_titles = ("Parada", "Gol encajado", "Centro atrapado", "Salida", "Distribución")
    assert any(f"** · **{title}**" in all_markdown(at) for title in spanish_titles)

    at.radio(key="mode").set_value("Analyst").run()
    at.selectbox(key="club").set_value("Both").run()
    assert not at.exception, at.exception
    assert at.session_state.match_sec == MID_SEC
    _, cards, _ = expected(MID_SEC, [HOME, AWAY])
    assert card_count(at) == cards, (card_count(at), cards)  # both keepers now
    assert len(at.get("plotly_chart")) == 4                   # two maps, two goal mouths
    print(f"ok  switching options keeps the match position ({cards} cards for both)")


def test_distribution_card():
    """The showcase: 89:25, Mateo Rios volleys to striker Luca Ferro under high
    pressure, the long ball is won and leads to a shot."""
    at = new_app()
    at.session_state.match_sec = END_SEC
    at.radio(key="mode").set_value("Analyst").run()
    assert not at.exception, at.exception
    text = all_markdown(at)
    assert "**89:25** · **Distribution** · Mateo Rios → Luca Ferro" in text
    assert ":blue-badge[Quality 90 · excellent]" in text
    captions = "\n".join(c.value for c in at.caption)
    assert "kick (volley) · ST · 73.4 m · high pressure · decision 100 · led to a shot" in captions
    print("ok  distribution card at 89:25")


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
    print("ok  play and pause")


def test_full_time_report():
    at = new_app()
    at.session_state.match_sec = END_SEC
    at.selectbox(key="club").set_value("Both").run()
    assert not at.exception, at.exception
    heading, _, _ = expected(END_SEC, [HOME, AWAY])
    assert heading in all_markdown(at)
    labels = [m.label for m in at.metric]
    assert labels.count("Goals prevented") == 2, labels
    assert labels.count("Distribution completed") == 2, labels
    print(f"ok  full-time report: {heading}")


if __name__ == "__main__":
    test_starts_paused_at_kickoff()
    test_mid_match_cards_and_charts()
    test_switching_options_keeps_position()
    test_distribution_card()
    test_play_pause_restart()
    test_full_time_report()
    print("all tests passed")
