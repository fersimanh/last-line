"""Tests for inspector.py and the per-event facts in perception.py. Run:  python3 test_inspector.py"""
import json
import re

import inspector
from insights import filter_for, notable_events
from perception import match_info

MATCH = match_info()
HOME, AWAY = MATCH["home"], MATCH["away"]
EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF️]")
FILTERS = {team: filter_for(team, 120) for team in (HOME, AWAY)}


def test_every_event_type_has_a_template_in_both_languages():
    seen_types, count = set(), 0
    for team, f in FILTERS.items():
        for pe in f.perceived:
            facts = f.facts(pe.event["id"], reveal=False)
            for language in ("en", "es"):
                text = inspector.template_text(facts, language)
                assert text and "None" not in text and "{" not in text and "nan" not in text.lower(), (pe.event["type"], text)
                assert not EMOJI.search(text)
                if facts["sight"] != "felt":   # a shot you only felt says so instead of the distance
                    assert f"{round(facts['keeper_off_line_m'])} m" in text, text
            seen_types.add(pe.event["type"])
            count += 1
    assert seen_types >= {"pass", "through_ball", "cross", "box_entry", "shot", "goal", "keeper_save",
                          "keeper_claim", "keeper_sweep", "keeper_distribution", "tackle", "possession_change"}, seen_types
    print(f"ok  {count} perceived events x 2 languages all get a template ({len(seen_types)} event types)")


def test_spanish_is_really_spanish():
    f = FILTERS[HOME]
    for pe in f.perceived:
        if pe.event["type"] == "pass" and pe.sight == "seen":
            facts = f.facts(pe.event["id"])
            en, es = inspector.template_text(facts, "en"), inspector.template_text(facts, "es")
            assert "Estás a" in es and "You're" in en and en != es
            assert " off your line" not in es and "passes" not in es
            break
    print("ok  the Spanish templates are Spanish")


def test_the_keeper_view_never_includes_what_the_keeper_missed():
    f = FILTERS[HOME]
    missed_ids = [m.event["id"] for m in f.missed if m.reason != "unseen_option"]
    assert missed_ids
    assert all(f.facts(i, reveal=False) is None for i in missed_ids)           # not selectable in Keeper's eyes
    assert all(f.facts(i, reveal=True) is not None for i in missed_ids)        # but selectable in Reveal
    assert all(not f.can_select(i, 99999, reveal=False) for i in missed_ids)
    assert all(f.can_select(i, 99999, reveal=True) for i in missed_ids)
    future = max(i for i in range(10**4) if f.lookup(i, True) is not None)
    assert f.facts(future + 1, reveal=True) is None                            # an id that does not exist
    first = f.perceived[10]
    assert not f.can_select(f.perceived[-1].event["id"], first.second, reveal=False)   # not happened yet
    print("ok  missed and future events are not selectable in Keeper's eyes; Reveal allows missed ones")


def test_pass_facts_hide_a_destination_the_keeper_did_not_perceive():
    f = FILTERS[HOME]
    hidden = shown = 0
    for pe in f.perceived:
        if pe.event["type"] != "pass":
            continue
        nxt = pe.event["id"] + 1
        eyes, full = f.facts(pe.event["id"], reveal=False)["ball_move"], f.facts(pe.event["id"], reveal=True)["ball_move"]
        assert full["distance_m"] is not None or nxt >= 10**6
        next_perceived = f.lookup(nxt, False) is not None
        if next_perceived:
            assert eyes["distance_m"] == full["distance_m"]
            shown += 1
        else:
            assert eyes["distance_m"] is None and eyes["outcome"] is None, "leaked an unperceived destination"
            hidden += 1
    assert hidden and shown
    print(f"ok  pass destinations: {shown} shown, {hidden} hidden because the keeper did not perceive them")


def test_pass_facts_do_not_peek_into_the_future():
    f = FILTERS[HOME]
    pe = next(p for p in f.perceived if p.event["type"] == "pass" and f.lookup(p.event["id"] + 1, False))
    now = pe.second                       # the clock is exactly at the pass: the next event has not happened
    nxt_second = f.lookup(pe.event["id"] + 1, False)["event"]["minute"] * 60 + f.lookup(pe.event["id"] + 1, False)["event"]["second"]
    if nxt_second > now:
        assert f.facts(pe.event["id"], upto_sec=now)["ball_move"]["distance_m"] is None
    assert f.facts(pe.event["id"], upto_sec=now + 600)["ball_move"]["distance_m"] is not None
    print("ok  a pass's destination is not shown before it has happened")


def test_notable_rules():
    base = {"key_moment": False, "type": "pass"}
    move = {"distance_m": 10, "forward_m": 5, "direction": "forward", "outcome": "completed",
            "leads_to_shot": False, "own_third": False, "pressure": None}
    check = lambda **kw: inspector.notable_reason(dict(base, ball_move=dict(move, **kw)))
    assert check() is None                                              # an ordinary pass
    assert check(forward_m=inspector.LONG_FORWARD_M) == "long_forward"
    assert check(forward_m=inspector.LONG_FORWARD_M - 1) is None
    assert check(forward_m=30, direction="lateral") is None             # sideways ground is not "forward"
    assert check(distance_m=inspector.LONG_BALL_M) == "long_ball"
    assert check(leads_to_shot=True) == "leads_to_shot"
    assert check(outcome="lost", own_third=True) == "lost_own_third"
    assert check(outcome="lost", own_third=False) is None               # lost, but not in the own third
    assert inspector.notable_reason(dict(base, type="keeper_distribution", ball_move=None)) == "keeper_pass"
    assert inspector.notable_reason(dict(base, key_moment=True, ball_move=None)) == "key_moment"
    assert inspector.notable_reason(dict(base, type="tackle", ball_move=None)) is None
    print("ok  notable pass rules: long forward, long ball, leads to a shot, lost in own third, keeper pass")


def test_notable_events_for_this_match():
    events = notable_events()
    assert events
    assert {e["why"] for e in events} <= {"keeper_pass", "long_ball", "long_forward", "leads_to_shot", "lost_own_third"}
    ids = [e["event_id"] for e in events]
    assert len(ids) == len(set(ids)), "an event is listed twice"
    for e in events:
        f = FILTERS[e["team"]]
        facts = f.facts(e["event_id"], reveal=False)
        assert facts is not None and facts["relevant_keeper"] == e["team"] and not facts["key_moment"]
    print(f"ok  {len(events)} notable events, each for one keeper who perceived it, none a key moment")


def test_agent_facts_are_compact_and_perceived_only():
    f = FILTERS[HOME]
    for pe in f.perceived[:300]:
        compact = inspector.agent_facts(f.facts(pe.event["id"], reveal=False))
        assert not {"event", "traffic", "position", "insight", "reason"} & set(compact)
        assert len(json.dumps(compact)) < 600
    print("ok  the agents get compact facts: no raw event, no traffic, no missed reason")


def test_numbers_rows():
    f = FILTERS[HOME]
    kinds = {}
    for pe in f.perceived:
        facts = f.facts(pe.event["id"])
        rows = inspector.numbers_rows(facts, "en")
        assert rows and all(isinstance(a, str) and isinstance(b, str) for a, b in rows)
        t = pe.event["type"]
        if t == "shot" and pe.insight.get("saveability") is not None:
            kinds["shot"] = rows
        if t == "keeper_distribution":
            kinds["distribution"] = rows
        if t == "pass":
            kinds["pass"] = rows
    labels = lambda kind: [a for a, _ in kinds[kind]]
    assert any(label.startswith("Saveability") for label in labels("shot"))
    assert sum(1 for l in labels("shot") if "(" in l) == 14                    # the 14 saveability factors
    assert "Quality" in labels("distribution") and "Decision score" in labels("distribution")
    assert {"Distance", "Direction", "Pressure", "Outcome"} <= set(labels("pass"))
    spanish = [a for a, _ in inspector.numbers_rows(f.facts(f.perceived[40].event["id"]), "es")]
    assert "Estabas fuera de tu línea" in spanish
    print("ok  numbers: 14 factors for shots, quality and decision for passes out, distance/direction/pressure/outcome for passes")


if __name__ == "__main__":
    test_every_event_type_has_a_template_in_both_languages()
    test_spanish_is_really_spanish()
    test_the_keeper_view_never_includes_what_the_keeper_missed()
    test_pass_facts_hide_a_destination_the_keeper_did_not_perceive()
    test_pass_facts_do_not_peek_into_the_future()
    test_notable_rules()
    test_notable_events_for_this_match()
    test_agent_facts_are_compact_and_perceived_only()
    test_numbers_rows()
    print("all inspector tests passed")
