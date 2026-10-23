"""Tests for the match engine (sim_engine.py, formations.py, tracking.py).

Run:  python3 test_sim.py
They play two short seeds and check the contract the rest of the app depends on:
event schema and frames, tracking physics, the loader, and determinism.
"""
import json
import os
import tempfile
import time

import numpy as np

import calibration
import formations
import sim_engine
from perception import PerceptionFilter
from tracking import Tracking

SEED = 3
STARTED = time.time()
RESULT = sim_engine.simulate(SEED)
SECONDS = time.time() - STARTED
EVENTS, MATCH, TRACK = RESULT["events"], RESULT["match"], RESULT["tracking"]
HOME, AWAY = MATCH["home"], MATCH["away"]
TMP = tempfile.mkdtemp()
EVENTS_PATH, TRACKING_PATH = os.path.join(TMP, "e.json"), os.path.join(TMP, "t.npz")
sim_engine.save(RESULT, EVENTS_PATH, TRACKING_PATH)
TRACKING = Tracking(TRACKING_PATH)
BALL_MOVES = ("pass", "cross", "through_ball")
COMMON = ("id", "minute", "second", "half", "team", "player", "type", "x", "y")
OLD_TYPES = {"pass", "cross", "through_ball", "box_entry", "tackle", "possession_change", "shot", "goal", "keeper_save",
             "keeper_claim", "keeper_sweep", "keeper_close_down", "keeper_distribution"}
NEW_TYPES = {"dribble", "stoppage", "throw_in", "corner", "free_kick", "penalty", "foul", "card", "offside",
             "substitution", "keeper_punch", "off_ball_run"}


def test_deterministic_and_fast():
    again = sim_engine.simulate(SEED)
    assert json.dumps(again["events"]) == json.dumps(EVENTS)
    for key in ("players", "ball", "times", "half"):
        assert np.array_equal(again["tracking"][key], TRACK[key]), key
    other = sim_engine.simulate(SEED + 1)
    assert json.dumps(other["events"]) != json.dumps(EVENTS)
    assert SECONDS < 60, SECONDS
    print(f"ok  the same seed gives the same match and tracking; a match takes {SECONDS:.1f} s (limit 60 s)")


def test_event_schema_and_order():
    assert {e["type"] for e in EVENTS} <= OLD_TYPES | NEW_TYPES, {e["type"] for e in EVENTS} - OLD_TYPES - NEW_TYPES
    assert [e["id"] for e in EVENTS] == list(range(len(EVENTS)))                 # sequential ids
    assert [e["t"] for e in EVENTS] == sorted(e["t"] for e in EVENTS)            # sorted by time
    for e in EVENTS:
        assert all(k in e for k in COMMON), e
        assert e["minute"] == int(e["t"] // 60) and e["second"] == int(e["t"] % 60)
        assert e["half"] in (1, 2) and (e["half"] == 1) == (e["t"] < TRACKING.times[np.argmax(TRACKING.half == 2)])
        assert -0.1 <= e["x"] <= 105.1 and -0.1 <= e["y"] <= 68.1, e
        assert e["team"] in (HOME, AWAY)
    for e in EVENTS:
        if e["type"] in BALL_MOVES:
            assert isinstance(e["success"], bool) and e["receiver"] and e["pass_type"] in (
                "short", "back", "switch", "long", "through", "cross"), e
            assert e["length_m"] > 0 and 0 <= e["end_x"] <= 105 and 0 <= e["end_y"] <= 68
        if "traffic" in e:
            assert all({"team", "role", "x", "y"} <= set(b) for b in e["traffic"]) and len(e["traffic"]) <= 21
    assert all(k in MATCH for k in ("home", "away", "final_score", "pitch", "seed", "coordinate_note"))
    print(f"ok  {len(EVENTS)} events: schema, ids, order, frames-in-range, pass fields, traffic")


def test_tracking_shape_and_physics():
    t = TRACKING
    assert t.players.shape == (len(t.times), 22, 2) and t.ball.shape == (len(t.times), 2)
    assert len(t.times) > 10800 and abs(np.diff(t.times) - 0.5).max() < 1e-6 and t.hz == 2.0
    assert TRACK["players"].dtype == np.int16 and TRACK["ball"].dtype == np.int16       # compact centimeters
    assert t.players[..., 0].min() >= -0.5 and t.players[..., 1].min() >= -3.0 and t.players[..., 0].max() <= 105.5 and t.players[..., 1].max() <= 68.5
    step = np.linalg.norm(np.diff(t.players, axis=0), axis=2) / 0.5                      # speed of each player
    same_half = (t.half[1:] == t.half[:-1])[:, None]
    assert (step * same_half).max() < 11.0, (step * same_half).max()                      # nobody teleports or flies
    ball_step = np.linalg.norm(np.diff(t.ball, axis=0), axis=1) / 0.5
    assert (ball_step * same_half[:, 0]).max() < 45.0                                     # fast, but a football
    print(f"ok  tracking: {len(t.times)} samples at 2 Hz, int16 cm, in bounds, top speed "
          f"{(step * same_half).max():.1f} m/s, ball {(ball_step * same_half[:, 0]).max():.1f} m/s")


def test_roster_and_formations():
    assert sorted(set(TRACKING.teams)) == sorted([HOME, AWAY]) and len(TRACKING.indices(HOME)) == 11
    assert sorted(set(TRACK["slots"][:11])) == sorted(s[0] for s in formations.FORMATIONS[MATCH["formations"][HOME]])
    for team in (HOME, AWAY):
        assert [TRACKING.roles[i] for i in TRACKING.indices(team)].count("GK") == 1
    start = TRACKING.players_in_frame(0.0, HOME)[:11]
    anchors = np.array([p["anchor"] for p in formations.build_teams(__import__("random").Random(SEED))[0]["players"]])
    assert np.linalg.norm(start - anchors, axis=1).max() < 25                            # kickoff spots follow the formation
    # the keepers stay in their own area for the whole match, in either half (the sides switch at half time)
    for team in (HOME, AWAY):
        gk = [i for i in TRACKING.indices(team) if TRACKING.roles[i] == "GK"][0]
        for seconds in np.linspace(0, TRACKING.times[-1], 40):
            now = TRACKING.positions_at(seconds)
            x, y = TRACKING.to_team_frame(now["players"][gk], team, now["half"])
            assert x < 40 and 18 < y < 50, (team, seconds, x, y)
    print("ok  rosters and formations; each keeper stays by their own goal in both halves")


def test_loader_interpolates_and_converts_frames():
    t = TRACKING
    k = 1000
    at_sample = t.positions_at(t.times[k])
    assert np.allclose(at_sample["players"], t.players[k], atol=1e-6)
    mid = t.positions_at((t.times[k] + t.times[k + 1]) / 2)
    assert np.allclose(mid["players"], (t.players[k] + t.players[k + 1]) / 2, atol=1e-6)
    assert np.allclose(t.positions_at(-5)["players"], t.players[0]) and np.allclose(t.positions_at(1e6)["players"], t.players[-1])
    boundary = int(np.argmax(t.half == 2))                                              # first sample of the second half
    gap = t.positions_at(t.times[boundary] - 0.25)
    assert np.allclose(gap["players"], t.players[boundary - 1]) and gap["half"] == 1      # no blending across half time
    pts = np.array([[10.0, 20.0], [90.5, 60.0]])
    for team in (HOME, AWAY):
        for seconds in (100.0, 3000.0):
            once = t.to_team_frame(pts, team, t.half_at(seconds))
            assert np.allclose(t.to_team_frame(once, team, t.half_at(seconds)), pts)      # flipping twice is a no-op
            assert np.allclose(t.to_keeper_frame(pts, team, seconds), t.to_event_frame(pts, team, seconds))
    assert t.attack_dir(HOME, 1) == 1 and t.attack_dir(HOME, 2) == -1 and t.attack_dir(AWAY, 1) == -1
    print("ok  the loader interpolates, does not blend across half time, and converts frames (and back)")


def test_events_agree_with_tracking():
    """Each pass is recorded where the passer stood; each defending event in the attacker's frame."""
    errors, tackle_errors = [], []
    for n, e in enumerate(EVENTS):
        k = int(round(e["t"] / 0.5))
        before = TRACKING.players[max(k - 1, 0)]                    # the engine acts on the positions of the previous sample
        restart = n > 0 and EVENTS[n - 1]["type"] in ("corner", "free_kick")   # a short routine: the taker is placed on the spot
        if e["type"] in BALL_MOVES + ("dribble",) and e.get("pass_type") != "throw_in" and not restart:
            i = TRACKING.index_of(e["player"])
            absolute = TRACKING.to_event_frame(np.array([e["x"], e["y"]]), e["team"], e["t"])
            errors.append(np.linalg.norm(before[i] - absolute))
            assert TRACKING.teams[i] == e["team"]
        if e["type"] in ("tackle", "possession_change"):
            # recorded in the OTHER team's frame: convert with the loser's frame. The winner is standing
            # where he won the ball (a sample later), so his tracked position is the reference.
            loser = AWAY if e["team"] == HOME else HOME
            absolute = TRACKING.to_event_frame(np.array([e["x"], e["y"]]), loser, e["t"])
            winner = TRACKING.index_of(e["player"])
            assert TRACKING.teams[winner] == e["team"]
            tackle_errors.append(np.linalg.norm(TRACKING.players[min(k, len(TRACKING.times) - 1)][winner] - absolute))
    assert errors and max(errors) < 0.1, max(errors)                 # exact, up to rounding to 0.1 m
    assert tackle_errors and np.median(tackle_errors) < 2.0 and max(tackle_errors) < 6.0, (np.median(tackle_errors), max(tackle_errors))
    print(f"ok  events match the tracking: {len(errors)} passes/carries exact, {len(tackle_errors)} defending events in the attacker's frame")


def test_failed_passes_lose_the_ball_and_successful_ones_do_not():
    lost = kept = 0
    for i, e in enumerate(EVENTS):
        if e["type"] not in BALL_MOVES:
            continue
        later = [x for x in EVENTS[i + 1:i + 12] if x["t"] - e["t"] < 20 and x["type"] in ("tackle", "possession_change", "stoppage", "keeper_claim", "keeper_punch", "keeper_sweep")
                 and x["team"] != e["team"]]
        if e["success"]:
            nxt = next((x for x in EVENTS[i + 1:] if x["t"] > e["t"] + 0.1), None)
            kept += 1
            assert not (nxt and nxt["type"] in ("tackle", "possession_change") and nxt["team"] != e["team"]
                        and nxt["t"] - e["t"] < 0.9 * e["length_m"] / 10 and nxt.get("reason") == "interception"), e
        else:
            assert later, ("a failed pass must hand the ball over", e)
            lost += 1
    assert lost and kept
    print(f"ok  {lost} failed passes each hand the ball to the other team; {kept} successful passes keep it")


def test_football_shaped_match():
    m = calibration.metrics_for(RESULT)
    assert 450 < m["completed_passes"] < 1000 and 60 < m["pass_completion"] < 95
    types = {e["type"] for e in EVENTS}
    assert {"pass", "cross", "through_ball", "tackle", "possession_change", "box_entry", "stoppage"} <= types
    assert 35 < MATCH["possession_pct"][HOME] < 65 and 45 < MATCH["live_minutes"] < 80
    print(f"ok  a football-shaped match: {m['completed_passes']} completed passes, {m['pass_completion']:.0f}% completion, "
          f"{MATCH['possession_pct'][HOME]}% possession for {HOME}, {MATCH['live_minutes']} live minutes")


def test_the_original_event_contract_is_kept():
    """contract.json lists every field the original generator wrote, per event type. Keep them all."""
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract.json")) as f:
        contract = json.load(f)["types"]
    results = [RESULT] + [sim_engine.simulate(s) for s in (11, 12)]
    seen = set()
    for r in results:
        for e in r["events"]:
            missing = set(contract.get(e["type"], [])) - set(e)
            assert not missing, (e["type"], missing)
            seen.add(e["type"])
    assert set(contract) - {"keeper_sweep"} <= seen, set(contract) - seen          # every old type still appears
    print(f"ok  every original field of {len(seen & set(contract))} old event types is still there, across {len(results)} matches")


def test_stoppages_and_set_pieces():
    kinds = {}
    for e in EVENTS:
        kinds.setdefault(e["type"], []).append(e)
    stops = {e["reason"] for e in kinds["stoppage"]}
    assert {"throw_in", "goal_kick", "corner", "free_kick", "half_time"} <= stops, stops
    for e in kinds["stoppage"]:
        assert e["duration_s"] > 0
    for e in kinds["corner"]:
        assert e["delivery"] in ("inswinger", "outswinger", "short") and e["keeper_decision"] in ("claim", "punch", "miss", "stay")
        assert 0 <= e["attackers_in_box"] <= 10 and 0 <= e["defenders_in_box"] <= 10 and e["x"] > 100
    walls = [e for e in kinds["free_kick"] if e["kind"] == "direct"]
    assert walls, "no direct free kick in this match"
    for e in walls:
        assert 1 <= e["wall_size"] <= 5 and 8.0 <= e["wall_distance_m"] <= 10.5 and e["wall_offset_m"] >= 0, e
        assert "keeper_post_offset_m" in e
    for e in kinds.get("penalty", []):
        assert abs(e["x"] - 94.0) < 0.5 and e["keeper_dive"] in ("left", "right", "stays")
    for e in kinds["throw_in"]:
        assert e["y"] < 0.5 or e["y"] > 67.5 or e["x"] < 0.5 or e["x"] > 104.5, e
    for e in kinds["foul"]:
        assert "fouled" in e and isinstance(e["in_box"], bool)
    print(f"ok  stoppages {sorted(stops)}; {len(kinds['corner'])} corners, {len(walls)} direct free kicks with a wall, "
          f"{len(kinds['throw_in'])} throw-ins, {len(kinds.get('penalty', []))} penalties")


def test_goals_shots_and_the_score():
    shots = {e["id"]: e for e in EVENTS if e["type"] == "shot"}
    goals = [e for e in EVENTS if e["type"] == "goal"]
    assert sum(1 for s in shots.values() if s["outcome"] == "goal") == len(goals) == sum(MATCH["final_score"].values())
    score = {HOME: 0, AWAY: 0}
    for g in goals:
        assert g["related_to"] in shots and shots[g["related_to"]]["outcome"] == "goal" and shots[g["related_to"]]["t"] <= g["t"]
        score[g["team"]] += 1
        assert g["score"] == f"{score[HOME]}-{score[AWAY]}"
    assert score == {HOME: MATCH["final_score"][HOME], AWAY: MATCH["final_score"][AWAY]}
    for s in shots.values():
        assert s["situation"] in ("open_play", "rebound", "second_ball", "one_on_one", "two_on_one", "header_from_cross", "cutback",
                                  "corner", "free_kick", "penalty"), s["situation"]
        assert s["body_part"] in ("foot", "head") and s["outcome"] in ("goal", "saved", "blocked", "off_target")
        assert s["distance_m"] >= 1 and 0 <= s["defenders_in_lane"] <= 3
    # defenders in the lane are counted from the tracked positions
    checked = same = 0
    for s in shots.values():
        if s["situation"] in ("free_kick", "penalty") or s["body_part"] == "head":
            continue
        k = int(round(s["t"] / 0.5))
        players = TRACKING.players[max(k - 1, 0)]
        mine = s["team"]
        direction = TRACKING.attack_dir(mine, s["half"])
        pts = players if direction == 1 else np.stack([105 - players[:, 0], 68 - players[:, 1]], axis=1)
        me = np.array([s["x"], s["y"]])
        a, b, c = me, np.array([105.0, 30.34]), np.array([105.0, 37.66])
        count = 0
        for i in TRACKING.indices(HOME if mine == AWAY else AWAY):
            if TRACKING.roles[i] == "GK" or pts[i][0] <= me[0] + 0.5 or pts[i][1] < 0:
                continue
            side = lambda u, v, w: (v[0] - u[0]) * (w[1] - u[1]) - (v[1] - u[1]) * (w[0] - u[0])
            s1, s2, s3 = side(a, b, pts[i]), side(b, c, pts[i]), side(c, a, pts[i])
            count += (s1 >= 0 and s2 >= 0 and s3 >= 0) or (s1 <= 0 and s2 <= 0 and s3 <= 0)
        checked += 1
        same += min(count, 3) == s["defenders_in_lane"]
    assert checked and same >= 0.85 * checked, (same, checked)
    print(f"ok  {len(shots)} shots, {len(goals)} goals tie to the score; defenders in the lane match the tracking in {same}/{checked}")


def test_cards_substitutions_and_added_time():
    subs = [e for e in EVENTS if e["type"] == "substitution"]
    for team in (HOME, AWAY):
        assert len([e for e in subs if e["team"] == team]) <= 5
    assert subs and all(e["player_on"] and e["player_off"] and e["half"] == 2 for e in subs)
    for e in subs:                                                  # the tracking swaps the name at that moment
        before, after = TRACKING.names_at(e["t"] - 1.0), TRACKING.names_at(e["t"] + 1.0)
        assert e["player_off"] in before and e["player_on"] in after and e["player_on"] not in before, e
    for e in [e for e in EVENTS if e["type"] == "card"]:
        assert e["card"] in ("yellow", "red") and e["reason"]
    reds = [e for e in EVENTS if e["type"] == "card" and e["card"] == "red"]
    for e in reds:                                                  # a sent-off player is off the pitch for good
        assert not TRACKING.on_pitch(TRACKING.times[-1])[TRACKING.index_of(e["player"])]
    # the second half runs 45 minutes plus its added time
    second = TRACKING.times[TRACKING.half == 2]
    assert abs((TRACKING.times[-1] - second[0]) - (2700 + MATCH["added_time_s"]["second_half"])) < 30
    assert 60 <= MATCH["added_time_s"]["first_half"] + MATCH["added_time_s"]["second_half"] <= 1500
    print(f"ok  {len(subs)} substitutions swap names in the tracking, {len(reds)} red cards leave the pitch, "
          f"added time {MATCH['added_time_s']['first_half']} s and {MATCH['added_time_s']['second_half']} s")


def test_off_ball_runs_come_from_the_tracking():
    runs = [e for e in EVENTS if e["type"] == "off_ball_run"]
    assert runs, "no runs"
    by_id = {e["id"]: e for e in EVENTS}
    for r in runs:
        shot = by_id[r["run_for"]]
        assert shot["type"] == "shot" and shot["team"] == r["team"] and 0 < shot["t"] - r["t"] <= 9.0, (r, shot["t"])
        assert r["end_x"] >= 70 and r["length_m"] >= 9 and r["speed_ms"] >= 5.4
        i = TRACKING.index_of(r["player"])                          # he really moved that far, that fast
        a, b = TRACKING.positions_at(r["t"])["players"][i], TRACKING.positions_at(r["t"] + r["length_m"] / r["speed_ms"])["players"][i]
        assert np.linalg.norm(b - a) > 0.6 * r["length_m"], (r, np.linalg.norm(b - a))
    print(f"ok  {len(runs)} off-ball runs, each a real sprint in the tracking in the seconds before a shot")


def test_the_keeper_is_part_of_the_game():
    dist = [e for e in EVENTS if e["type"] == "keeper_distribution"]
    assert {"goal_kick"} <= {e["trigger"] for e in dist} and len(dist) >= 20
    for e in dist:
        assert e["method"] in ("throw", "kick", "roll", "ground_pass") and e["outcome"] in (
            "completed", "intercepted", "contested_won", "contested_lost"), e
        assert 2 <= len(e["options"]) <= 7 and e["target_player"] in [o["player"] for o in e["options"]]
    in_game = sum(1 for e in EVENTS if e["type"] in ("keeper_claim", "keeper_save", "keeper_punch", "keeper_sweep", "keeper_close_down"))
    assert in_game >= 5
    back_passes = sum(1 for e in EVENTS if e["type"] == "keeper_distribution" and e["trigger"] == "back_pass")
    print(f"ok  keepers: {len(dist)} distributions ({back_passes} after a back pass), {in_game} saves/claims/punches/sweeps/close-downs")


def test_inspector_and_scoring_read_every_engine_event():
    """The app's inspector (templates in two languages, the numbers) must cope with the new event types."""
    import inspector
    types = {e["id"]: e["type"] for e in EVENTS}
    shown, kinds = 0, set()
    for team in (HOME, AWAY):
        f = PerceptionFilter(team, path=EVENTS_PATH)
        f.advance_all()
        ids = [pe.event["id"] for pe in f.perceived] + [m.event["id"] for m in f.missed if "id" in m.event]
        for reveal in (False, True):
            for i in ids:
                facts = f.facts(i, reveal=reveal)
                if facts is None:
                    continue
                for language in ("en", "es"):
                    text = inspector.template_text(facts, language)
                    assert text and "None" not in text and "{" not in text, (types[i], text)
                    inspector.numbers_rows(facts, language)
                kinds.add(types[i])
                shown += 1
    assert {"dribble", "throw_in", "free_kick", "corner", "foul", "stoppage"} <= kinds, kinds
    print(f"ok  the inspector and scoring handle {shown} event views of {len(kinds)} event types, in both languages")


def test_the_perception_layer_still_reads_the_events():
    """The existing PerceptionFilter must accept engine events unchanged (the contract)."""
    for team in (HOME, AWAY):
        f = PerceptionFilter(team, path=EVENTS_PATH)
        f.advance_all()
        missed = [m for m in f.missed if m.reason != "unseen_option"]
        assert len(f.perceived) + len(missed) == len(EVENTS)
        assert f.perceived and missed
        for pe in f.perceived[:200]:
            assert f.facts(pe.event["id"], reveal=False) is not None
    print("ok  PerceptionFilter reads the engine's events: every event is perceived or missed exactly once")


if __name__ == "__main__":
    test_deterministic_and_fast()
    test_event_schema_and_order()
    test_tracking_shape_and_physics()
    test_roster_and_formations()
    test_loader_interpolates_and_converts_frames()
    test_events_agree_with_tracking()
    test_failed_passes_lose_the_ball_and_successful_ones_do_not()
    test_football_shaped_match()
    test_the_original_event_contract_is_kept()
    test_stoppages_and_set_pieces()
    test_goals_shots_and_the_score()
    test_cards_substitutions_and_added_time()
    test_off_ball_runs_come_from_the_tracking()
    test_the_keeper_is_part_of_the_game()
    test_inspector_and_scoring_read_every_engine_event()
    test_the_perception_layer_still_reads_the_events()
    print("all sim tests passed")
