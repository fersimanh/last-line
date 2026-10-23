"""Unit tests for vision.py. Run:  python3 test_vision.py

Part 1 checks the geometry with made-up points. Part 2 checks the frame
conversion on real events from match_events.json, working out the expected
values from the generator's rules (see the vision.py header).
"""
import math

import vision as v
from replay import load_match

MATCH, EVENTS = load_match()
HOME, AWAY = MATCH["home"], MATCH["away"]


def other(team):
    return AWAY if team == HOME else HOME


def first(predicate):
    return next(e for e in EVENTS if predicate(e))


# ---------- Part 1: the sightline ----------

KEEPER = (4.0, 34.0)
FACING_UP = 0.0  # facing straight up the pitch


def test_straight_ahead_is_visible():
    assert v.is_visible(KEEPER, FACING_UP, (30.0, 34.0))
    print("ok  straight ahead is visible")


def test_behind_is_not_visible():
    # a point behind the goal line (negative x) is directly behind a keeper facing up
    assert not v.is_visible(KEEPER, FACING_UP, (-0.5, 34.0))
    # facing down the pitch toward y = 0 (-90 degrees... i.e. facing -y), a point up the pitch is behind
    assert not v.is_visible(KEEPER, 180.0, (30.0, 34.0))
    print("ok  behind the keeper is not visible")


def test_fov_edge():
    # 120 degree FOV: the edge is 60 degrees off the facing direction
    def point_at(deg, dist=20.0):
        return (KEEPER[0] + dist * math.cos(math.radians(deg)),
                KEEPER[1] + dist * math.sin(math.radians(deg)))
    assert v.is_visible(KEEPER, FACING_UP, point_at(59))       # just inside
    assert v.is_visible(KEEPER, FACING_UP, point_at(-59))
    assert not v.is_visible(KEEPER, FACING_UP, point_at(61))   # just outside
    assert not v.is_visible(KEEPER, FACING_UP, point_at(-61))
    # a wider field of view lets the 61 degree point in
    assert v.is_visible(KEEPER, FACING_UP, point_at(61), fov_deg=150)
    print("ok  just inside and just outside the FOV edge")


def test_beyond_radius():
    edge = v.DEFAULT_RADIUS_M
    assert v.is_visible(KEEPER, FACING_UP, (4 + edge - 1, 34.0))       # just inside the default range
    assert not v.is_visible(KEEPER, FACING_UP, (4 + edge + 1, 34.0))   # just beyond it
    assert v.is_visible(KEEPER, FACING_UP, (4 + 70, 34.0), radius_m=80)  # a longer range sees further
    print("ok  beyond the radius is not visible")


def test_body_in_the_way_blocks():
    ball = (30.0, 34.0)
    assert not v.is_visible(KEEPER, FACING_UP, ball, blockers=[(15.0, 34.0)])     # dead in line
    assert not v.is_visible(KEEPER, FACING_UP, ball, blockers=[(15.0, 34.15)])    # shoulder in line
    assert v.is_visible(KEEPER, FACING_UP, ball, blockers=[(15.0, 36.0)])         # 2 m to the side
    assert v.is_visible(KEEPER, FACING_UP, ball, blockers=[(40.0, 34.0)])         # behind the ball
    assert v.is_visible(KEEPER, FACING_UP, ball, blockers=[(29.8, 34.0)])         # level with it
    assert v.blockers_of(KEEPER, ball, [(15.0, 34.0), (15.0, 40.0)]) == [(15.0, 34.0)]
    print("ok  a body in the sightline blocks; beside, behind or level with the ball does not")


def test_near_bodies_hide_more_than_far_ones():
    ball = (44.0, 34.0)
    # a point 0.9 m off the line, 40 m away, is 1.29 degrees off axis
    off_line = (44.0, 34.9)
    near = (6.0, 34.0)    # 2 m from the keeper: covers 8.5 degrees
    far = (30.0, 34.0)    # 26 m away: covers 0.66 degrees
    assert v.hides(KEEPER, off_line, near)
    assert not v.hides(KEEPER, off_line, far)
    assert v.hides(KEEPER, ball, far)
    print("ok  a body close to the keeper hides a wider angle than a far one")


def test_facing_angle():
    assert v.facing_angle(KEEPER, (30.0, 34.0)) == 0.0          # ball straight up the pitch
    assert abs(v.facing_angle(KEEPER, (4.0, 60.0)) - v.MAX_TURN_DEG) < 1e-9  # ball level: he turns, but not past the limit
    assert v.facing_angle(KEEPER, KEEPER) == 0.0                # ball at the keeper's feet
    assert v.facing_angle((6.0, 34.0), (5.5, 34.0)) == 0.0      # a goal kick just behind him: he faces up the pitch
    for ball in [(0.5, 34.0), (0.5, 10.0), (-1.0, 60.0), (2.0, 20.0), (2.0, 48.0)]:   # behind him, near the goal line
        assert abs(v.facing_angle((8.0, 34.0), ball)) <= v.MAX_TURN_DEG, ball        # never into his own net
    assert v.facing_angle((8.0, 34.0), (2.0, 20.0)) < 0 < v.facing_angle((8.0, 34.0), (2.0, 48.0))   # but toward its side
    print("ok  facing angle")


# ---------- Part 2: frames, on real events ----------

def test_shot_against_followed_keeper():
    """A shot by the other team at the followed goal. Recorded in the shooter's
    frame (goal at x = 105), so it is flipped, and keeper_x ~ 101-104 becomes ~1-4."""
    shot = first(lambda e: e["type"] == "shot" and e["team"] == AWAY)
    x, y = v.to_keeper_frame(shot, HOME)
    assert (x, y) == (round(105 - shot["x"], 10), round(68 - shot["y"], 10)) or \
        (abs(x - (105 - shot["x"])) < 1e-9 and abs(y - (68 - shot["y"])) < 1e-9)
    kx, ky = v.keeper_position(shot, v.DEFAULT_KEEPER, HOME)
    assert 0.5 <= kx <= 5.0, kx
    assert abs(kx - (105 - shot["keeper_x"])) < 1e-9 and abs(ky - (68 - shot["keeper_y"])) < 1e-9
    assert x > 5  # the shooter is out in the pitch, not at the goal
    print(f"ok  shot against the followed keeper: shooter ({x:.1f}, {y:.1f}), keeper ({kx:.1f}, {ky:.1f})")


def test_shot_by_followed_team():
    """The followed team's own shot is in its own attacking frame, so it is
    unchanged: it lands far from the followed goal. The keeper is the OTHER one,
    so the followed keeper's position is not updated."""
    shot = first(lambda e: e["type"] == "shot" and e["team"] == HOME)
    assert v.to_keeper_frame(shot, HOME) == (shot["x"], shot["y"])
    assert v.to_keeper_frame(shot, HOME)[0] > 70
    assert v.keeper_position(shot, (9.0, 30.0), HOME) == (9.0, 30.0)
    print("ok  shot by the followed team stays far from the followed goal")


def test_save_by_followed_keeper():
    """A save by the followed keeper is recorded in the shooter's frame (keeper
    near x = 101-104). In the keeper frame the keeper is on the goal line."""
    save = first(lambda e: e["type"] == "keeper_save" and e["team"] == HOME)
    x, y = v.to_keeper_frame(save, HOME)
    assert 0.5 <= x <= 5.0, x
    shot = next(e for e in EVENTS if e["id"] == save["related_to"])
    assert v.keeper_position(save, v.DEFAULT_KEEPER, HOME) == (x, y)
    assert abs(x - (105 - shot["keeper_x"])) < 3.0  # about the spot the shot recorded (he may have moved a step)
    # the same save seen from the OTHER keeper's point of view is up the pitch
    assert v.to_keeper_frame(save, AWAY)[0] > 100
    print(f"ok  save by the followed keeper: ({x:.1f}, {y:.1f})")


def test_claim_by_followed_keeper():
    claim = first(lambda e: e["type"] == "keeper_claim" and e["team"] == HOME)
    x, y = v.to_keeper_frame(claim, HOME)
    assert 1.0 <= x <= 5.5, x          # claim x was 100-103.5 in the attacker's frame
    assert 28 <= y <= 40, y
    assert v.keeper_position(claim, v.DEFAULT_KEEPER, HOME) == (x, y)
    print(f"ok  claim by the followed keeper: ({x:.1f}, {y:.1f})")


def test_distribution_in_own_frame():
    """Distribution is in the distributor's OWN frame. For the followed keeper
    that is already the keeper frame; for the other keeper it must be flipped."""
    mine = first(lambda e: e["type"] == "keeper_distribution" and e["team"] == HOME)
    assert v.to_keeper_frame(mine, HOME) == (mine["x"], mine["y"])
    assert 0.5 <= mine["x"] <= 25.0
    assert v.keeper_position(mine, (30.0, 10.0), HOME) == (mine["x"], mine["y"])
    assert v.ball_position(mine, HOME) == (mine["target_x"], mine["target_y"])

    theirs = first(lambda e: e["type"] == "keeper_distribution" and e["team"] == AWAY)
    x, y = v.to_keeper_frame(theirs, HOME)
    assert abs(x - (105 - theirs["x"])) < 1e-9 and x > 98, x  # their keeper is at the far end
    assert v.keeper_position(theirs, (7.0, 33.0), HOME) == (7.0, 33.0)  # not our keeper
    bx, by = v.ball_position(theirs, HOME)
    assert abs(bx - (105 - theirs["target_x"])) < 1e-9
    print(f"ok  distribution: followed keeper ({mine['x']}, {mine['y']}), "
          f"other keeper appears at ({x:.1f}, {y:.1f})")


def test_defending_events_use_the_other_frame():
    """A tackle by the followed team is recorded in the OPPONENT's attacking
    frame, so it must be flipped; by the opponent it is in the followed team's."""
    tackle = first(lambda e: e["type"] == "tackle" and e["team"] == HOME)
    assert v.to_keeper_frame(tackle, HOME) == (105 - tackle["x"], 68 - tackle["y"])
    tackle2 = first(lambda e: e["type"] == "tackle" and e["team"] == AWAY)
    assert v.to_keeper_frame(tackle2, HOME) == (tackle2["x"], tackle2["y"])
    print("ok  defending events use the other team's frame")


def test_the_tracked_timeline():
    """With tracking the bodies in the way come from the tracked players, on any part of the pitch."""
    from perception import load_tracking
    tracking = load_tracking(MATCH, "match_events.json")
    assert tracking is not None
    timeline = v.build_timeline(EVENTS, HOME, tracking)
    assert len(timeline) == len(EVENTS)
    players, _ = tracking.frame_arrays(HOME)
    gk = tracking.keeper_slot(HOME)
    shots = [i for i, e in enumerate(EVENTS) if e["type"] == "shot"]
    for i in sorted(set(list(range(0, len(EVENTS), 7)) + shots)):
        entry, k = timeline[i], max(tracking.sample_index(EVENTS[i]["t"]) - 1, 0)
        assert abs(entry["keeper"][0] - players[k, gk, 0]) < 1e-6
        assert len(entry["blockers"]) == int(tracking.on_pitch_mask()[k].sum()) - 1     # everyone but the keeper
        assert entry["blocked_by"] == len(v.blockers_of(entry["keeper"], entry["pos"], entry["blockers"]))
        assert all(0 <= b[0] <= 105 and 0 <= b[1] <= 68 for b in entry["blockers"])
    some_blocked = [e for e in timeline if e["blocked_by"] > 0]
    assert some_blocked and any(e["pos"][0] < 60 for e in some_blocked), "bodies block the view in midfield too"
    clear = [e for e in timeline if e["blocked_by"] == 0 and e["distance_m"] <= v.DEFAULT_RADIUS_M
             and e["off_axis"] <= v.DEFAULT_FOV_DEG / 2]
    assert all(v.was_seen(e) for e in clear), "nothing in the way, in range and in the cone: seen"
    print(f"ok  tracked timeline: {len(some_blocked)} of {len(timeline)} events have a body in the sightline, "
          f"including in midfield")


def test_the_older_traffic_path_still_works():
    """Match files without tracking keep using the events' own `traffic` lists."""
    shot = {"type": "shot", "team": HOME, "t": 1.0, "x": 90.0, "y": 34.0, "keeper_x": 4.0, "keeper_y": 34.0,
            "traffic": [{"team": AWAY, "role": "defender", "x": 4.0 + 1.0, "y": 34.0}]}
    entry = v.build_timeline([shot], AWAY)[0]          # followed by the other team: the point is flipped into that keeper frame
    assert entry["blockers"], "traffic is read when there is no tracking"
    print("ok  older match files without tracking keep working from `traffic`")


def test_timeline_is_consistent():
    timeline = v.build_timeline(EVENTS, HOME)
    assert len(timeline) == len(EVENTS)
    for entry in timeline:
        assert -1 <= entry["pos"][0] <= 106 and -1 <= entry["pos"][1] <= 69, entry["pos"]
        assert 0 <= entry["keeper"][0] <= 25
    # the followed keeper never leaves a sensible area near the goal
    seen = sum(v.was_seen(e) for e in timeline)
    print(f"ok  timeline: {len(timeline)} events, {seen} inside the default sightline")


if __name__ == "__main__":
    test_straight_ahead_is_visible()
    test_behind_is_not_visible()
    test_fov_edge()
    test_beyond_radius()
    test_body_in_the_way_blocks()
    test_near_bodies_hide_more_than_far_ones()
    test_facing_angle()
    test_shot_against_followed_keeper()
    test_shot_by_followed_team()
    test_save_by_followed_keeper()
    test_claim_by_followed_keeper()
    test_distribution_in_own_frame()
    test_defending_events_use_the_other_frame()
    test_the_tracked_timeline()
    test_the_older_traffic_path_still_works()
    test_timeline_is_consistent()
    print("all vision tests passed")
