"""Tests for app.py with Streamlit's AppTest (no browser needed).

Run:  python3 test_app.py
The agents are switched off here, so the tests never call Azure: texts come
from insight_cache.json or the fallback line. Expected numbers are worked
out from the match data, so the tests still hold after regenerating it.
"""
import json
import os
import re
import tempfile
import time

os.environ["LAST_LINE_LIVE_AGENTS"] = "0"  # must be set before the app imports insights.py

from streamlit.testing.v1 import AppTest  # noqa: E402

import insights  # noqa: E402
from insights import filter_for, match_end_second, match_second, replay_to  # noqa: E402
from perception import match_info  # noqa: E402

MATCH = match_info()
HOME, AWAY = MATCH["home"], MATCH["away"]
END_SEC = match_end_second()
MID_SEC = END_SEC // 2 + 600  # a point in the second half
EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF️]")


def expected(upto_sec, clubs):
    """Score heading and number of cards the app should show at this moment."""
    _, _, moments, score = replay_to(MATCH, None, upto_sec)
    home_goals, away_goals = score.split("-")
    heading = f"{HOME} {home_goals} – {away_goals} {AWAY}"
    return heading, sum(1 for m in moments if m["keeper_team"] in clubs), moments


def new_app():
    at = AppTest.from_file("app.py", default_timeout=90)
    at.run()
    assert not at.exception, at.exception
    return at


def all_markdown(at):
    return "\n".join(m.value for m in at.markdown)


def card_count(at):
    """Each insight card starts with a card-head row."""
    return sum(1 for m in at.markdown if 'class="ll-card-head"' in m.value)


def chart_spec(at, index=0):
    element = at.get("plotly_chart")[index]
    return json.loads(element.proto.spec)


def test_starts_paused_at_kickoff_in_the_keepers_eyes():
    at = new_app()
    assert at.session_state.match_sec == 0
    assert at.session_state.playing is False
    assert at.radio(key="view").value == "Keeper's eyes"          # the default view
    assert f'aria-label="{HOME} 0 – 0 {AWAY}, 00:00"' in all_markdown(at)
    assert card_count(at) == 0
    assert [t.label for t in at.tabs] == ["Live", "Key moments", "Events", "Full-time report"]
    assert len(at.get("plotly_chart")) == 1                        # just the Keeper's eyes pitch
    print("ok  starts paused at kickoff, in the Keeper's eyes view")


def test_the_stylesheet_is_sent_once_and_uses_the_tokens():
    import theme
    at = new_app()
    css = [m.value for m in at.markdown if "/* ll-css */" in m.value]
    assert len(css) == 1, len(css)
    for token in (theme.LIME, theme.BG, theme.CARD, theme.CARD_BORDER, theme.BODY, theme.HEADING,
                  "Fraunces", "Outfit", "JetBrains Mono", "prefers-reduced-motion"):
        assert token in css[0], token
    print("ok  the stylesheet is sent once and carries the design tokens")


def test_mid_match_cards_and_the_pitch():
    at = new_app()
    at.session_state.match_sec = MID_SEC
    at.run()
    assert not at.exception, at.exception
    heading, cards, _ = expected(MID_SEC, [HOME])  # default club is the home side
    assert f'aria-label="{heading},' in all_markdown(at)
    assert card_count(at) == cards, (card_count(at), cards)
    spec = chart_spec(at)
    assert "MODELED SIGHTLINE · 120°" in spec["layout"]["annotations"][0]["text"]
    assert any(s.get("fillrule") == "evenodd" for s in spec["layout"]["shapes"])  # the dimming
    assert {"Keeper", "Ball"} <= {t.get("name") for t in spec["data"]}
    print(f"ok  mid-match: {heading}, {cards} cards, cone and dimming drawn")


def test_unseen_counts_are_shown():
    at = new_app()
    at.session_state.match_sec = MID_SEC
    at.run()
    text = all_markdown(at)
    assert "Missed in the last 30 s" in text and "Missed so far" in text
    print("ok  unseen counts are shown")


def test_view_toggle_and_reveal():
    at = new_app()
    at.session_state.match_sec = MID_SEC
    at.run()
    at.radio(key="view").set_value("Reveal").run()
    assert not at.exception, at.exception
    assert at.session_state.match_sec == MID_SEC                    # the match did not restart
    text = all_markdown(at)
    assert "What the keeper missed" in text and "Official numbers" in text
    assert len(at.get("plotly_chart")) == 3                         # pitch + shot map + goal mouth
    spec = chart_spec(at)
    for extra in range(1, 40):                                      # the last 8 events may all have been seen: move on a bit
        if any(t.get("name") == "Missed" for t in spec["data"]):
            break
        at.session_state.match_sec = MID_SEC + extra * 30
        at.run()
        spec = chart_spec(at)
    assert any(t.get("name") == "Missed" for t in spec["data"]), "missed events should be drawn hollow"
    at.session_state.match_sec = MID_SEC
    at.run()
    at.radio(key="view").set_value("Keeper's eyes").run()
    assert len(at.get("plotly_chart")) == 1
    assert at.session_state.match_sec == MID_SEC
    print("ok  the view toggle works and never restarts the match")


def test_full_pitch_toggle_and_players_on_the_pitch():
    at = new_app()
    at.session_state.match_sec = MID_SEC
    at.run()
    dims = lambda spec: [sh for sh in spec["layout"].get("shapes", []) if sh.get("fillrule") == "evenodd"]
    spec = chart_spec(at)
    assert len(dims(spec)) == 1, "the pitch is dimmed outside the cone by default"
    named = {tr.get("name") for tr in spec["data"]}
    assert {"Your team", "Opponents"} & named, "the players in view are drawn"
    hollow = [tr for tr in spec["data"] if tr.get("marker", {}).get("symbol") == "circle-open" and tr.get("name") in ("Your team", "Opponents")]
    assert not hollow, "Keeper's eyes never draws a player the keeper cannot see"
    at.checkbox(key="full_pitch").set_value(True).run()
    assert not at.exception, at.exception
    assert not dims(chart_spec(at)), "no dimming with the full-pitch toggle on"
    assert at.session_state.match_sec == MID_SEC                    # the toggle does not move the match
    at.radio(key="view").set_value("Reveal").run()
    spec = chart_spec(at)
    assert any(tr.get("marker", {}).get("symbol") == "circle-open" and tr.get("name") in ("Your team", "Opponents")
               for tr in spec["data"]), "Reveal also draws the players out of sight, hollow"
    print("ok  the full-pitch toggle removes the dimming; players in view are drawn, hidden ones only in Reveal")


def test_switching_everything_keeps_position():
    at = new_app()
    at.session_state.match_sec = MID_SEC
    at.run()
    at.radio(key="language").set_value("Español").run()
    assert not at.exception, at.exception
    assert at.session_state.match_sec == MID_SEC
    _, cards, _ = expected(MID_SEC, [HOME])
    assert card_count(at) == cards
    assert "Momentos clave" in all_markdown(at)
    spanish_sights = ("Tu acción", "Visto con claridad", "Visto tarde")
    assert any(s in all_markdown(at) for s in spanish_sights)

    at.radio(key="mode").set_value("Analyst").run()
    at.slider(key="fov").set_value(150).run()
    assert not at.exception, at.exception
    assert at.session_state.match_sec == MID_SEC
    assert "150°" in chart_spec(at)["layout"]["annotations"][0]["text"]   # the cone widened

    at.selectbox(key="club").set_value("Both").run()
    assert not at.exception, at.exception
    assert at.session_state.match_sec == MID_SEC
    assert at.radio(key="eyes_keeper").value == HOME               # Both follows the home keeper first
    at.radio(key="eyes_keeper").set_value(AWAY).run()
    _, away_cards, _ = expected(MID_SEC, [AWAY])
    assert card_count(at) == away_cards, (card_count(at), away_cards)
    assert at.session_state.match_sec == MID_SEC
    print("ok  language, mode, field of view, club and keeper switches keep the match position")


def test_distribution_card():
    """The best-rated distribution that led to a shot, or the best-rated one if
    none did. Its expected card is built from the data, so this works for any seed."""
    _, _, moments, _ = replay_to(MATCH, None, END_SEC)
    dists = [m for m in moments if m["distribution"]]
    to_shot = [m for m in dists if m["distribution"]["led_to_shot"]]
    m = max(to_shot or dists, key=lambda m: m["distribution"]["quality"])
    d = m["distribution"]
    at = new_app()
    at.session_state.match_sec = END_SEC
    at.selectbox(key="club").set_value(m["keeper_team"]).run()
    assert not at.exception, at.exception
    text = all_markdown(at)
    assert f'<span class="ll-clock">{m["clock"]}</span>' in text
    assert f"Distribution · {d['verdict']}" in text                  # the headline carries the verdict
    assert f"Quality {d['quality']}" in text
    numbers = "\n".join(e.value for e in at.markdown if f"**Quality**: {d['quality']}/100" in e.value)
    assert f"{d['target_role']} {d['target_player']}" in numbers
    print(f"ok  distribution card at {m['clock']} ({m['player']} to {d['target_player']})")


def test_shot_card_has_headline_pills_and_numbers():
    _, _, moments, _ = replay_to(MATCH, None, END_SEC)
    m = next(m for m in moments if m["saveability"] is not None and m["keeper_team"] == HOME)
    at = new_app()
    at.session_state.match_sec = END_SEC
    at.run()
    text = all_markdown(at)
    assert f'<span class="ll-clock">{m["clock"]}</span>' in text
    assert f"Saveability {m['saveability']}" in text
    assert any(s in text for s in ("Seen clearly", "Late sight"))
    assert "Show the numbers" in [e.label for e in at.expander]
    print(f"ok  shot card at {m['clock']} has a verdict, a score pill, a sight pill and numbers")


def test_no_emojis_in_the_keepers_eyes_view():
    at = new_app()
    at.session_state.match_sec = END_SEC
    at.run()
    shown = [all_markdown(at)] + [c.value for c in at.caption] + [b.label for b in at.button]
    shown += [e.label for e in at.expander] + [t.label for t in at.tabs]
    found = EMOJI.findall("\n".join(shown))
    assert not found, found
    print("ok  no emojis in the Keeper's eyes view")


def test_play_pause_restart():
    at = new_app()
    at.session_state.match_sec = 600
    at.run()
    at.button(key="play").click().run()
    assert not at.exception, at.exception
    assert at.session_state.playing is True
    at.session_state.last_wall = time.time() - 1.5    # a second and a half of real time goes by
    at.run()
    assert 600 + 1.5 * 120 - 20 < at.session_state.match_sec < 600 + 1.5 * 120 + 60, \
        at.session_state.match_sec                    # about 180 match seconds, at 120x
    at.button(key="pause").click().run()
    paused_at = at.session_state.match_sec
    at.session_state.last_wall = time.time() - 3
    at.run()
    assert at.session_state.playing is False
    assert at.session_state.match_sec == paused_at     # paused: the clock does not move
    at.button(key="restart").click().run()
    assert at.session_state.match_sec < 60 and at.session_state.playing is True
    print("ok  play, pause and restart; replay speed follows the wall clock")


def test_a_long_gap_does_not_make_the_match_jump():
    at = new_app()
    at.button(key="play").click().run()
    at.session_state.last_wall = time.time() - 600     # a browser tab that slept for ten minutes
    at.run()
    assert at.session_state.match_sec <= 2.0 * 120 + 5, at.session_state.match_sec
    print("ok  a long gap moves the match by at most two seconds' worth")


def test_full_time_report():
    at = new_app()
    at.session_state.match_sec = END_SEC
    at.selectbox(key="club").set_value("Both").run()
    assert not at.exception, at.exception
    heading, _, _ = expected(END_SEC, [HOME, AWAY])
    assert f'aria-label="{heading}, FT"' in all_markdown(at)
    labels = [m.label for m in at.metric]
    assert labels.count("Goals prevented") == 2, labels
    assert labels.count("Distribution completed") == 2, labels
    print(f"ok  full-time report: {heading}")


# ---------- Click to inspect ----------

def pick_events():
    """A perceived pass and a missed pass for the home keeper, both before MID_SEC."""
    f = filter_for(HOME, 120)
    seen = next(pe for pe in reversed(f.perceived) if pe.second < MID_SEC and pe.event["type"] == "pass")
    missed = next(m for m in reversed(f.missed) if m.reason != "unseen_option"
                  and match_second(m.event) < MID_SEC and m.event["type"] == "pass")
    return seen.event["id"], missed.event["id"]


def select_and_run(event_id, view="Keeper's eyes", seconds=MID_SEC):
    at = new_app()
    at.session_state.match_sec = seconds
    at.session_state.selected_event_id = event_id
    at.radio(key="view").set_value(view).run()
    assert not at.exception, at.exception
    return at


def has_inspector(at):
    return any('class="ll-inspector-head"' in m.value for m in at.markdown)


def test_selecting_an_event_shows_the_inspector():
    seen_id, _ = pick_events()
    at = select_and_run(seen_id)
    text = all_markdown(at)
    assert has_inspector(at)
    assert "Quick insight" in text                           # agents are off here: the template is used
    assert "In the 30 seconds before: you saw" in text       # what you saw / what you missed (a count)
    assert any(e.label == "Show the numbers" for e in at.expander)
    assert "You&#x27;re" in text and "off your line" in text  # second person, from the template
    assert len(at.get("plotly_chart")) == 1                  # the one big pitch shows the selected moment
    assert any("The pitch shows the selected moment" in c.value for c in at.caption)
    row = filter_for(HOME, 120).lookup(seen_id)
    assert f'<span class="ll-clock">{row["event"]["clock"]}</span>' in text
    print("ok  selecting an event shows the inspector (text, count, numbers) and puts the moment on the pitch")


def test_a_key_moment_card_shows_its_moment_on_the_pitch():
    """Clicking a key moment's button selects the event, pauses, and the left pitch shows that moment."""
    moments = [m for m in replay_to(MATCH, None, END_SEC)[2] if m["keeper_team"] == HOME]
    target = moments[len(moments) // 2]
    at = new_app()
    at.session_state.match_sec = END_SEC
    at.session_state.playing = False
    at.run()
    at.button(key=f"show_{target['event_id']}").click().run()
    assert not at.exception, at.exception
    assert at.session_state.selected_event_id == target["event_id"] and at.session_state.playing is False
    assert at.session_state.match_sec == END_SEC                         # the clock stays where it was
    assert has_inspector(at)
    assert any("The pitch shows the selected moment" in c.value for c in at.caption)
    spec = chart_spec(at)
    rings = [tr for tr in spec["data"] if tr.get("marker", {}).get("symbol") == "circle-open" and tr.get("showlegend") is False
             and tr.get("hoverinfo") == "skip"]
    assert rings, "the selected moment has a ring on the pitch"
    assert at.button(key=f"show_{target['event_id']}").disabled         # the chosen card says so
    at.button(key="inspector_back_to_live").click().run()
    assert at.session_state.selected_event_id is None
    assert not any("The pitch shows the selected moment" in c.value for c in at.caption)
    print("ok  clicking a key moment shows it on the pitch, marks the card, and Back to live returns")


def test_events_filters_cover_every_event_type():
    """Every event lands in All and in exactly one of the other filters (Other takes the rest)."""
    at = new_app()
    at.session_state.match_sec = END_SEC
    at.run()
    at.radio(key="view").set_value("Reveal").run()
    counts = {}
    for name in ("all", "shots", "passes", "keeper", "other"):
        at.radio(key="ev_filter").set_value(name).run()
        assert not at.exception, at.exception
        counts[name] = list(at.session_state.evlist_ids)
    parts = counts["shots"] + counts["passes"] + counts["keeper"] + counts["other"]
    assert sorted(parts) == sorted(counts["all"]), "a filter misses or repeats some events"
    other_types = {filter_for(HOME, 120).lookup(i, True)["event"]["type"] for i in counts["other"]}
    assert {"foul", "stoppage", "throw_in"} <= other_types, other_types
    print(f"ok  the Events filters split all {len(counts['all'])} events with nothing lost (Other has set pieces, fouls...)")


def test_play_closes_the_inspector_and_restarts_at_full_time():
    moments = [m for m in replay_to(MATCH, None, END_SEC)[2] if m["keeper_team"] == HOME]
    at = new_app()
    at.session_state.match_sec = END_SEC
    at.run()
    at.button(key=f"show_{moments[0]['event_id']}").click().run()
    assert at.session_state.selected_event_id is not None
    at.button(key="play").click().run()
    assert at.session_state.selected_event_id is None and at.session_state.playing is True
    assert at.session_state.match_sec < 5, "Play at full time starts the match again"
    print("ok  Play closes the inspector (the pitch never freezes on an old moment) and restarts at full time")


def test_goal_markers_use_the_fan_clock():
    at = new_app()
    at.session_state.match_sec = END_SEC
    at.run()
    timeline = next(m.value for m in at.markdown if 'class="ll-timeline"' in m.value)
    goals = [e for e in insights.keeper_eyes(HOME)._events if e["type"] == "goal"]
    for g in goals:
        assert f"{g['clock'].split(':')[0]}&#39; {g['team']}" in timeline, (g["clock"], timeline[-400:])
    print(f"ok  goal diamonds and the timeline speak the fan clock ({', '.join(g['clock'] for g in goals)})")


def test_a_failed_agent_call_is_not_repeated_on_every_rerun():
    calls = []
    saved = insights.LIVE_AGENTS, insights.generate_event_text
    insights.LIVE_AGENTS = True
    insights.generate_event_text = lambda *a, **k: calls.append(1)        # the agents "fail" (None)
    try:
        f = filter_for(HOME, 120)
        pe = next(pe for pe in f.perceived if insights.ai_info(HOME, pe.event["id"])["eligible"]
                  and insights.moment_key(insights.ai_info(HOME, pe.event["id"])["text_event_id"],
                                          "analyst", "Nobody", "es", "eyes") not in insights.load_cache())
        facts = f.facts(pe.event["id"], reveal=False)
        for _ in range(3):
            text, source = insights.get_event_text(HOME, facts, "analyst", "es", "Nobody", "eyes")
            assert text and source == "quick"
        assert len(calls) == 1, f"the agents were asked {len(calls)} times"
    finally:
        insights.LIVE_AGENTS, insights.generate_event_text = saved
        insights._failed.clear()
    print("ok  after a failed agent call the same text is not requested again on every rerun")


def test_a_moment_beyond_the_shown_pitch_says_so():
    """Reveal can select an event in the other half; the pitch only shows the keeper's half, so the note says where it was."""
    f = filter_for(HOME, 120)
    far = next(m for m in f.missed if m.reason == "beyond_radius" and m.event["type"] == "pass")
    at = new_app()
    at.session_state.match_sec = END_SEC
    at.run()
    at.radio(key="view").set_value("Reveal").run()
    at.session_state.selected_event_id = far.event["id"]
    at.run()
    assert not at.exception, at.exception
    assert any("beyond the part of the pitch shown" in c.value for c in at.caption)
    print("ok  a selected moment in the other half is explained, not silently missing from the pitch")


def test_sight_range_what_if_draws_the_whole_pitch():
    """A longer sight range stretches the cone, and above 55 m the whole pitch is drawn."""
    at = new_app()
    at.session_state.match_sec = MID_SEC
    at.run()
    top = lambda spec: spec["layout"]["yaxis"]["range"][1]
    assert top(chart_spec(at)) < 70, "the default view stops just past halfway"
    at.slider(key="sight").set_value(90).run()
    assert not at.exception, at.exception
    assert top(chart_spec(at)) > 100, "a 90 m sight range draws the whole pitch"
    at.radio(key="view").set_value("Reveal").run()
    assert not at.exception, at.exception
    assert top(chart_spec(at)) > 100
    assert at.session_state.match_sec == MID_SEC
    short, long_ = filter_for(HOME, 120, 55), filter_for(HOME, 120, 90)
    assert len(long_.perceived) > len(short.perceived), "a longer range perceives more of the match"
    print(f"ok  sight range 90 m: whole pitch drawn, {len(long_.perceived)} events perceived against {len(short.perceived)} at 55 m")


def test_no_selection_shows_only_a_hint():
    at = select_and_run(None)
    assert not has_inspector(at)
    assert any("Click a marker on the pitch" in c.value for c in at.caption)
    print("ok  with nothing selected the inspector shows a hint")


def test_unperceived_events_are_not_selectable_in_keepers_eyes():
    seen_id, missed_id = pick_events()
    f = filter_for(HOME, 120)
    assert f.can_select(seen_id, MID_SEC, reveal=False)
    assert not f.can_select(missed_id, MID_SEC, reveal=False)
    assert f.can_select(missed_id, MID_SEC, reveal=True)
    at = select_and_run(missed_id)                           # a stale or forced selection is refused
    assert not has_inspector(at)
    assert "is not something this keeper perceived" in all_markdown(at)
    at = select_and_run(missed_id, view="Reveal")            # in Reveal the same event can be inspected
    assert has_inspector(at)
    header = next(m.value for m in at.markdown if 'class="ll-inspector-head"' in m.value)
    assert ">Missed<" in header                              # and the inspector header flags it as missed
    assert "You can&#x27;t see this one" in header           # with the reason it was missed
    print("ok  an unperceived event cannot be inspected in Keeper's eyes, and is flagged in Reveal")


def test_the_events_list_follows_the_perception_rule():
    seen_id, missed_id = pick_events()
    at = select_and_run(None)
    eyes_ids = set(at.session_state.evlist_ids)
    assert seen_id in eyes_ids and missed_id not in eyes_ids
    assert all(filter_for(HOME, 120).can_select(i, MID_SEC) for i in eyes_ids)
    at = select_and_run(None, view="Reveal")
    reveal_ids = set(at.session_state.evlist_ids)
    assert eyes_ids < reveal_ids and missed_id in reveal_ids          # Reveal lists everything
    at.radio(key="ev_filter").set_value("shots").run()
    shots = at.session_state.evlist_ids
    kinds = {filter_for(HOME, 120).lookup(i, True)["event"]["type"] for i in shots}
    assert shots and kinds <= {"shot", "goal"}, kinds
    print(f"ok  the Events list: {len(eyes_ids)} events in Keeper's eyes, {len(reveal_ids)} in Reveal, filters work")


def test_selection_survives_language_mode_and_view_changes():
    seen_id, _ = pick_events()
    at = select_and_run(seen_id)
    at.radio(key="language").set_value("Español").run()
    assert at.session_state.selected_event_id == seen_id and has_inspector(at)
    assert "Estás a" in all_markdown(at) and "Análisis rápido" in all_markdown(at)
    at.radio(key="mode").set_value("Analyst").run()
    assert at.session_state.selected_event_id == seen_id and has_inspector(at)
    at.radio(key="view").set_value("Reveal").run()
    assert at.session_state.selected_event_id == seen_id and has_inspector(at)
    at.slider(key="fov").set_value(150).run()
    assert at.session_state.selected_event_id == seen_id and not at.exception
    print("ok  the selection survives language, mode, view and field-of-view changes")


def test_restart_clears_the_selection():
    seen_id, _ = pick_events()
    at = select_and_run(seen_id)
    at.button(key="restart").click().run()
    assert at.session_state.selected_event_id is None and not has_inspector(at)
    print("ok  Restart clears the selection")


def test_back_to_live_resumes_and_closes_the_inspector():
    seen_id, _ = pick_events()
    at = select_and_run(seen_id)
    assert at.session_state.playing is False
    at.button(key="inspector_back_to_live").click().run()
    assert at.session_state.selected_event_id is None and at.session_state.playing is True
    assert not has_inspector(at)
    print("ok  Back to live closes the inspector and resumes the match")


def test_scrubber_pauses_and_drops_a_selection_from_the_future():
    seen_id, _ = pick_events()
    at = select_and_run(seen_id)
    at.button(key="play").click().run()
    assert at.session_state.playing is True
    at.select_slider(key="scrub").set_value(5).run()               # five minutes: before the selected event
    assert at.session_state.playing is False
    assert at.session_state.match_sec == 300
    assert at.session_state.selected_event_id is None        # that event has not happened yet
    at = select_and_run(seen_id)
    at.select_slider(key="scrub").set_value(85).run()              # later: the selection is kept
    assert at.session_state.match_sec == 5100 and at.session_state.selected_event_id == seen_id
    print("ok  the scrubber pauses, and drops a selection that is now in the future")


def test_next_and_previous_moment_buttons():
    at = new_app()
    moments = [m for m in replay_to(MATCH, None, END_SEC)[2] if m["keeper_team"] == HOME]
    at.button(key="next_moment").click().run()
    assert not at.exception, at.exception
    assert at.session_state.selected_event_id == moments[0]["event_id"]
    assert at.session_state.match_sec == moments[0]["second"] + 2 and at.session_state.playing is False
    assert has_inspector(at)
    at.button(key="next_moment").click().run()
    assert at.session_state.selected_event_id == moments[1]["event_id"]
    at.button(key="prev_moment").click().run()
    assert at.session_state.selected_event_id == moments[0]["event_id"]
    print("ok  Next and Previous moment jump to the keeper's key moments, select them and pause")


def test_ai_insight_comes_from_the_cache_and_quick_insight_is_the_fallback():
    event = next(e for e in insights.notable_events() if e["team"] == HOME)
    facts = filter_for(HOME, 120).facts(event["event_id"], reveal=False)
    second = facts["second"] + 30
    quick = select_and_run(event["event_id"], seconds=second)
    assert "Quick insight" in all_markdown(quick) and "AI insight" not in all_markdown(quick)   # cache miss, agents off
    with tempfile.TemporaryDirectory() as folder:
        real_path = insights.CACHE_PATH
        insights.CACHE_PATH = os.path.join(folder, "cache.json")
        try:
            key = insights.moment_key(event["event_id"], "casual", HOME, "en", "eyes")
            with open(insights.CACHE_PATH, "w") as f:
                json.dump({"_match": insights.cache_fingerprint(),
                           key: {"text": "A cached AI explanation.", "generated_at": "now"}}, f)
            insights._cache, insights._cache_mtime = {}, None
            cached = select_and_run(event["event_id"], seconds=second)
            text = all_markdown(cached)
            assert "AI insight" in text and "A cached AI explanation." in text
            assert "Quick insight" not in text
        finally:
            insights.CACHE_PATH = real_path
            insights._cache, insights._cache_mtime = {}, None
    ordinary = pick_events()[0]
    plain = select_and_run(ordinary)                       # an ordinary pass is never "AI insight"
    assert "AI insight" not in all_markdown(plain)
    print("ok  AI insight comes from the cache (or the agents); everything else is a Quick insight")


if __name__ == "__main__":
    test_starts_paused_at_kickoff_in_the_keepers_eyes()
    test_the_stylesheet_is_sent_once_and_uses_the_tokens()
    test_mid_match_cards_and_the_pitch()
    test_unseen_counts_are_shown()
    test_view_toggle_and_reveal()
    test_full_pitch_toggle_and_players_on_the_pitch()
    test_switching_everything_keeps_position()
    test_distribution_card()
    test_shot_card_has_headline_pills_and_numbers()
    test_no_emojis_in_the_keepers_eyes_view()
    test_play_pause_restart()
    test_a_long_gap_does_not_make_the_match_jump()
    test_full_time_report()
    test_selecting_an_event_shows_the_inspector()
    test_a_key_moment_card_shows_its_moment_on_the_pitch()
    test_events_filters_cover_every_event_type()
    test_play_closes_the_inspector_and_restarts_at_full_time()
    test_goal_markers_use_the_fan_clock()
    test_a_failed_agent_call_is_not_repeated_on_every_rerun()
    test_a_moment_beyond_the_shown_pitch_says_so()
    test_sight_range_what_if_draws_the_whole_pitch()
    test_no_selection_shows_only_a_hint()
    test_unperceived_events_are_not_selectable_in_keepers_eyes()
    test_the_events_list_follows_the_perception_rule()
    test_selection_survives_language_mode_and_view_changes()
    test_restart_clears_the_selection()
    test_back_to_live_resumes_and_closes_the_inspector()
    test_scrubber_pauses_and_drops_a_selection_from_the_future()
    test_next_and_previous_moment_buttons()
    test_ai_insight_comes_from_the_cache_and_quick_insight_is_the_fallback()
    print("all tests passed")
