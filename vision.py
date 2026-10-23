"""Keeper's eyes: where things are, and what the keeper can see.

Pure Python (no Streamlit), so it is easy to test.

THE KEEPER FRAME. Everything here is in the followed keeper's frame: their own
goal is at x = 0, y = 34, on a 105 x 68 pitch, and x grows up the pitch toward
the other goal.

THE DATA FRAMES (see README.md and generate_match.py). Each event is recorded
in the frame of ONE team, the team that "attacks toward x = 105" in it:
  - keeper_distribution: the distributing team's own frame (its keeper is at
    x = 2-6). Its target_x/target_y and options use the same frame.
  - keeper_save, keeper_claim, keeper_sweep, keeper_close_down, tackle,
    possession_change: these
    are done by the DEFENDING team, but recorded in the ATTACKING team's frame
    (the other team's frame than their `team` field implies).
  - everything else (pass, cross, through_ball, box_entry, shot, goal): the
    attacking team's frame, which is the event's own `team`.
So an event is already in the followed keeper's frame when the frame's owner is
the followed team; otherwise flip it: x -> 105 - x, y -> 68 - y.

BODIES IN THE WAY. Events near a goal carry `traffic`: the other players
standing around (same frame as the event). A body hides a point when it stands
between the keeper and the point and the keeper's sightline passes through it.
A body close to the keeper hides a wide angle; a far one only a sliver.
"""
import math

PITCH_LENGTH = 105.0
PITCH_WIDTH = 68.0
DEFAULT_KEEPER = (4.0, 34.0)   # where the keeper stands before we know better
DEFAULT_FOV_DEG = 120          # field of view of the modeled sightline
DEFAULT_RADIUS_M = 55          # how far the keeper can make things out
TRAIL_LENGTH = 8               # events kept for the fading trail
BODY_HALF_WIDTH_M = 0.3        # half a player's shoulder width: what blocks a sightline
BLOCK_MARGIN_M = 0.5           # a body must be at least this much nearer than the point

# Done by the defending team, but recorded in the attacking team's frame
DEFENDING_TYPES = ("keeper_save", "keeper_claim", "keeper_sweep", "keeper_close_down",
                   "tackle", "possession_change")
# Events that show where the followed keeper stands
KEEPER_OWN_TYPES = ("keeper_save", "keeper_claim", "keeper_sweep", "keeper_close_down",
                    "keeper_distribution")


# ---------- Frames ----------

def in_followed_frame(event, followed_team):
    """True when the event is already recorded in the followed keeper's frame
    (its frame owner is the followed team)."""
    if event["type"] in DEFENDING_TYPES:
        return event["team"] != followed_team   # the owner is the OTHER (attacking) team
    return event["team"] == followed_team       # attacking events and distributions


def point_to_keeper_frame(event, followed_team, x, y):
    """Move any point recorded in this event's frame into the keeper frame."""
    if in_followed_frame(event, followed_team):
        return x, y
    return PITCH_LENGTH - x, PITCH_WIDTH - y


def to_keeper_frame(event, followed_team):
    """(x, y) of the event in the followed keeper's frame."""
    return point_to_keeper_frame(event, followed_team, event["x"], event["y"])


# ---------- Keeper, ball, sightline ----------

def keeper_position(event, last_known, followed_team):
    """Where the followed keeper stands during this event.

    Known from: keeper_x/keeper_y on shots against the followed keeper; and the
    event position on the followed keeper's own saves, claims, sweeps and
    distributions. Anything else leaves the keeper where they were last seen.
    (The spec names two arguments; followed_team is needed to know whose keeper.)"""
    if event["type"] == "shot" and event["team"] != followed_team:
        return point_to_keeper_frame(event, followed_team, event["keeper_x"], event["keeper_y"])
    if event["type"] in KEEPER_OWN_TYPES and event["team"] == followed_team:
        return to_keeper_frame(event, followed_team)
    return last_known


def ball_position(event, followed_team):
    """Where the ball is after this event. For a distribution the keeper has
    just released it, so the ball is on its way to the target."""
    if event["type"] == "keeper_distribution":
        return point_to_keeper_frame(event, followed_team, event["target_x"], event["target_y"])
    return to_keeper_frame(event, followed_team)


def facing_angle(keeper_pos, ball_pos):
    """Degrees the keeper faces: 0 = straight up the pitch (+x), 90 = toward
    y = 68. The keeper always faces the ball. If the ball is at the keeper's
    feet there is no direction, so face up the pitch."""
    dx, dy = ball_pos[0] - keeper_pos[0], ball_pos[1] - keeper_pos[1]
    if math.hypot(dx, dy) < 0.5:
        return 0.0
    return math.degrees(math.atan2(dy, dx))


def off_axis_deg(keeper_pos, facing, event_pos):
    """How many degrees the event is away from where the keeper is facing (0-180)."""
    dx, dy = event_pos[0] - keeper_pos[0], event_pos[1] - keeper_pos[1]
    bearing = math.degrees(math.atan2(dy, dx))
    return abs((bearing - facing + 180) % 360 - 180)


def hides(keeper_pos, event_pos, body_pos, half_width_m=BODY_HALF_WIDTH_M):
    """Does a body standing at body_pos block the keeper's view of event_pos?

    It does when the body is nearer to the keeper than the point (by at least
    BLOCK_MARGIN_M) and the point lies within the angle the body covers. A body
    `d` meters away covers atan(half_width / d) degrees either side of its
    centre, so close bodies hide much more than far ones."""
    point_d = math.hypot(event_pos[0] - keeper_pos[0], event_pos[1] - keeper_pos[1])
    body_d = math.hypot(body_pos[0] - keeper_pos[0], body_pos[1] - keeper_pos[1])
    if body_d < 0.01 or body_d > point_d - BLOCK_MARGIN_M:
        return False  # on top of the keeper, or level with / behind the point
    covered = math.degrees(math.atan(half_width_m / body_d))
    body_bearing = math.degrees(math.atan2(body_pos[1] - keeper_pos[1], body_pos[0] - keeper_pos[0]))
    return off_axis_deg(keeper_pos, body_bearing, event_pos) <= covered


def blockers_of(keeper_pos, event_pos, blockers):
    """The bodies (from `blockers`, a list of (x, y)) that hide event_pos."""
    return [b for b in blockers if hides(keeper_pos, event_pos, b)]


def is_visible(keeper_pos, facing, event_pos, fov_deg=DEFAULT_FOV_DEG, radius_m=DEFAULT_RADIUS_M,
               blockers=()):
    """Can the keeper see this point? Yes when it is within `radius_m`, within
    half the field of view of the facing direction, and no body in `blockers`
    (a list of (x, y) in the same frame) stands in the sightline. Used for
    every event type, so new event types work automatically."""
    distance = math.hypot(event_pos[0] - keeper_pos[0], event_pos[1] - keeper_pos[1])
    if distance > radius_m:
        return False
    if distance < 0.01:
        return True  # the keeper is standing on it
    if off_axis_deg(keeper_pos, facing, event_pos) > fov_deg / 2:
        return False
    return not blockers_of(keeper_pos, event_pos, blockers)


def traffic_in_keeper_frame(event, followed_team):
    """The bodies around an event, as (x, y) in the keeper frame. Events far
    from any goal have no traffic recorded, so nothing blocks there."""
    return [point_to_keeper_frame(event, followed_team, b["x"], b["y"])
            for b in event.get("traffic", [])]


# ---------- The whole match, event by event ----------

def build_timeline(events, followed_team):
    """For every event (in order), the geometry from the followed keeper's side.

    Returns a list with one dict per event, in the same order:
      pos           event position, keeper frame
      keeper        where the followed keeper stands
      ball          where the ball is after the event
      facing_before degrees the keeper was facing just BEFORE the event, toward
                    the ball's previous position: the keeper has not seen this
                    event yet, so this is the direction they were watching
      distance_m    keeper to event
      off_axis      degrees between facing_before and the event
      blockers      the bodies around the event (keeper frame)
      blocked_by    how many of them stand in the keeper's sightline to it
    Whether the event was SEEN is was_seen(entry, fov): it depends on the
    field of view, so callers work it out themselves."""
    keeper = DEFAULT_KEEPER
    ball = (PITCH_LENGTH / 2, PITCH_WIDTH / 2)  # kickoff: the ball starts on the center spot
    timeline = []
    for event in events:
        keeper = keeper_position(event, keeper, followed_team)
        pos = to_keeper_frame(event, followed_team)
        facing_before = facing_angle(keeper, ball)
        blockers = traffic_in_keeper_frame(event, followed_team)
        timeline.append({
            "pos": pos,
            "keeper": keeper,
            "ball": ball_position(event, followed_team),
            "facing_before": facing_before,
            "distance_m": math.hypot(pos[0] - keeper[0], pos[1] - keeper[1]),
            "off_axis": off_axis_deg(keeper, facing_before, pos),
            "blockers": blockers,
            "blocked_by": len(blockers_of(keeper, pos, blockers)),
        })
        ball = timeline[-1]["ball"]
    return timeline


def was_seen(entry, fov_deg=DEFAULT_FOV_DEG, radius_m=DEFAULT_RADIUS_M):
    """Was the event inside the keeper's sightline, with nobody in the way,
    when it happened?"""
    return is_visible(entry["keeper"], entry["facing_before"], entry["pos"], fov_deg, radius_m,
                      entry.get("blockers", ()))
