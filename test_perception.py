"""Tests for perception.py. Run:  python3 test_perception.py"""
from perception import PerceptionFilter, match_info, second_of
from replay import is_key_moment, load_match

MATCH = match_info()
TEAMS = (MATCH["home"], MATCH["away"])
_, RAW = load_match()  # tests may read the raw match to check the filter against it


def full(team):
    f = PerceptionFilter(team)
    f.advance_all()
    return f


def test_every_event_is_perceived_or_missed_once():
    for team in TEAMS:
        f = full(team)
        perceived = [pe.event["id"] for pe in f.perceived]
        missed = [m.event["id"] for m in f.missed if m.reason != "unseen_option"]
        assert not set(perceived) & set(missed), "an event is both perceived and missed"
        assert sorted(perceived + missed) == [e["id"] for e in RAW], "events lost or duplicated"
        assert len(f.reveal()) == len(RAW)
    print("ok  every event is perceived or missed, exactly once")


def test_own_actions_and_goals_are_always_perceived():
    for team in TEAMS:
        f = full(team)
        sight = {pe.event["id"]: pe.sight for pe in f.perceived}
        for e in RAW:
            own = e["team"] == team and e["type"] in (
                "keeper_save", "keeper_claim", "keeper_sweep", "keeper_distribution")
            if own:
                assert sight.get(e["id"]) == "own", e["id"]
            if e["type"] == "goal":
                assert e["id"] in sight, f"goal {e['id']} not perceived"
            if e["type"] == "shot" and e["team"] != team and e["outcome"] in ("goal", "saved"):
                assert e["id"] in sight, f"shot {e['id']} reached the goal but was not perceived"
        assert f.score == "-".join(str(MATCH["final_score"][t]) for t in TEAMS)
    print("ok  own actions, goals and shots on target are always perceived; score is right")


def test_every_key_moment_reaches_its_keeper():
    def keeper_of(e):
        if e["type"] in ("keeper_claim", "keeper_sweep", "keeper_distribution"):
            return e["team"]
        return TEAMS[1] if e["team"] == TEAMS[0] else TEAMS[0]
    for team in TEAMS:
        f = full(team)
        expected = {e["id"] for e in RAW if is_key_moment(e) and keeper_of(e) == team}
        got = {pe.event["id"] for pe in f.perceived if pe.key_moment}
        assert got == expected, (team, expected - got, got - expected)
    print("ok  every key moment reaches its own keeper")


def test_distribution_options_are_filtered():
    for team in TEAMS:
        f = full(team)
        for pe in f.perceived:
            e = pe.event
            if e["type"] != "keeper_distribution":
                continue
            raw = RAW[e["id"]]
            assert all(o["visible"] for o in e["options"]), "an unseen option was passed on"
            assert e["unseen_options"] == sum(not o["visible"] for o in raw["options"])
            assert e["target_player"] in [o["player"] for o in e["options"]]
            assert pe.insight["best_option"] in [o["player"] for o in e["options"]]
        logged = [m for m in f.missed if m.reason == "unseen_option"]
        assert len(logged) == sum(pe.event.get("unseen_options", 0) for pe in f.perceived)
    print("ok  distribution options outside the sightline are filtered and logged")


def test_unseen_count_and_incremental_replay():
    team = TEAMS[0]
    whole = full(team)
    step = PerceptionFilter(team)
    for upto in range(0, 5600, 600):  # replay in 10-minute steps
        step.advance_all(upto)
        assert all(pe.second <= upto for pe in step.perceived)
    step.advance_all()
    assert [pe.event["id"] for pe in step.perceived] == [pe.event["id"] for pe in whole.perceived]
    assert step.unseen_count() == whole.unseen_count()
    assert whole.unseen_count() == sum(1 for m in whole.missed if m.reason != "unseen_option")
    assert whole.unseen_count(0, 600) == sum(1 for m in whole.missed if m.reason != "unseen_option"
                                             and second_of(m.event) <= 600)
    assert sum(pe.unseen_before for pe in whole.perceived) <= whole.unseen_count()
    print("ok  incremental replay matches a full replay; unseen counts add up")


def test_bodies_block_the_view():
    """Some events are missed only because a body stood in the way, and every
    one of those really is in range and inside the cone."""
    for team in TEAMS:
        f = full(team)
        blocked = [m for m in f.missed if m.reason == "blocked"]
        assert blocked, f"{team}: nothing was ever blocked"
        for m in blocked:
            assert m.distance_m <= f.radius_m
    print("ok  some events are missed only because a body blocked the view")


def test_perception_reads_the_tracking():
    """With tracking, the keeper's position and every body come from it, anywhere on the pitch."""
    import numpy as np
    import vision
    for team in TEAMS:
        f = full(team)
        assert f.tracking is not None
        players, _ = f.tracking.frame_arrays(team)
        gk = f.tracking.keeper_slot(team)
        for pe in f.perceived[:300]:                                  # the keeper stands where the tracking says
            k = max(f.tracking.sample_index(pe.event["t"]) - 1, 0)
            assert np.allclose(pe.keeper_pos, players[k, gk], atol=1e-6), pe.event["id"]
        # a missed event marked "blocked" really has a tracked body in the sightline
        blocked = [m for m in f.missed if m.reason == "blocked"]
        assert blocked
        for m in blocked[:50]:
            k = max(f.tracking.sample_index(m.event["t"]) - 1, 0)
            pos = vision.to_keeper_frame(m.event, team)
            bodies = [tuple(p) for i, p in enumerate(players[k]) if i != gk and f.tracking.on_pitch_mask()[k, i]]
            assert vision.blockers_of(m.keeper_pos, pos, bodies), m.event["id"]
        # blocking works away from the goals too: the old traffic lists covered only the attacking third
        assert any(m.distance_m > 30 for m in blocked)
    print("ok  the keeper's position and the bodies in the way come from the tracking, anywhere on the pitch")


def test_the_crowd_the_keeper_sees():
    import vision
    f = full(TEAMS[0])
    for second in (300, 1500, 3200, 5000):
        eyes, reveal = f.state_at(second), f.state_at(second, reveal=True)
        assert len(reveal["players"]) >= 18 and all(p["visible"] for p in eyes["players"])
        assert len(eyes["players"]) == sum(1 for p in reveal["players"] if p["visible"])
        assert len(eyes["players"]) < len(reveal["players"]), "the keeper never sees everyone"
        others = [(p["x"], p["y"]) for p in reveal["players"]]
        for p in reveal["players"]:                                   # Reveal's flag is the same visibility rule
            rest = [o for o in others if o != (p["x"], p["y"])]
            assert p["visible"] == vision.is_visible(reveal["keeper"], reveal["facing"], (p["x"], p["y"]),
                                                     f.fov_deg, f.radius_m, rest)
    print("ok  Keeper's eyes shows only the players in view; Reveal shows everyone, flagged by the same rule")


def test_wider_view_sees_more():
    narrow = PerceptionFilter(TEAMS[0], fov_deg=90)
    wide = PerceptionFilter(TEAMS[0], fov_deg=180)
    narrow.advance_all()
    wide.advance_all()
    assert len(wide.perceived) > len(narrow.perceived)
    print(f"ok  a wider field of view perceives more ({len(narrow.perceived)} at 90, "
          f"{len(wide.perceived)} at 180 degrees)")


if __name__ == "__main__":
    test_every_event_is_perceived_or_missed_once()
    test_own_actions_and_goals_are_always_perceived()
    test_every_key_moment_reaches_its_keeper()
    test_distribution_options_are_filtered()
    test_unseen_count_and_incremental_replay()
    test_bodies_block_the_view()
    test_perception_reads_the_tracking()
    test_the_crowd_the_keeper_sees()
    test_wider_view_sees_more()
    print("all perception tests passed")
