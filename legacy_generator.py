"""Synthetic match generator for Last Line.

Coordinates are meters on a 105 x 68 pitch. There are two frames:
  - Attacking frame (most events): each possession is recorded in the frame
    of the team attacking. They always attack toward x = 105, with the goal
    centered at y = 34. Defending events in that possession (saves, claims,
    sweeps, tackles) use the same frame.
  - Own frame (keeper_distribution only): the distributing keeper's team
    attacks toward x = 105, so their own keeper stands near x = 2-6.
Everything here is invented: fictional clubs, fictional players, no real data.
"""
import json
import math
import random

import vision
from scoring import SUCCESS, option_value, pass_success_prob, pick_method

SEED = 58  # in range (20-35 shots, 2-6 goals); both keepers concede and every shot situation appears

MATCH_SECONDS = 90 * 60
GOAL_Y_MIN, GOAL_Y_MAX, GOAL_H = 30.34, 37.66, 2.44
SHOOTER_WEIGHTS = [6, 5, 4, 3, 3, 2, 2, 1, 1, 1]

TEAMS = {
    "Harbor United": {
        "keeper": "Mateo Rios",
        "outfield": ["Luca Ferro", "Dani Okoye", "Sam Varga", "Ivo Marsh", "Theo Brandt",
                     "Nico Alves", "Jonas Keller", "Remy Cole", "Andre Salas", "Kofi Mensah"],
        "attack_rate": 0.19,
    },
    "Northgate FC": {
        "keeper": "Elias Novak",
        "outfield": ["Pavel Drum", "Hugo Lind", "Marco Tesch", "Ruben Okafor", "Tomas Reyes",
                     "Aiden Frost", "Viktor Haas", "Leo Santos", "Ben Arkwright", "Yusuf Demir"],
        "attack_rate": 0.16,
    },
}

# ---------- Distribution settings ----------

# Each squad's role, in the same order as its outfield list (first = striker,
# so the most frequent shooters are attackers)
ROLES = ["ST", "W", "CM", "CM", "W", "FB", "CB", "CB", "FB", "DM"]
SHORT_ROLES = ("CB", "FB", "DM")

# Where each role stands when its keeper has the ball, in the keeper's own
# frame: (x range, y range). Full-backs and wingers can be on either flank.
ROLE_AREAS = {
    "CB": ((10, 22), (14, 54)),
    "FB": ((14, 34), (3, 14)),
    "DM": ((22, 38), (24, 44)),
    "CM": ((32, 55), (14, 54)),
    "W": ((48, 72), (3, 14)),
    "ST": ((58, 80), (24, 44)),
}

# How many opponents are close to the keeper, by trigger: weights for 0, 1, 2, 3.
# Back passes happen when a team is being pressed, so they bring more pressure.
CLOSE_OPPONENT_WEIGHTS = {
    "goal_kick": [45, 35, 15, 5],
    "after_save": [60, 30, 8, 2],
    "after_claim": [55, 32, 10, 3],
    "back_pass": [30, 38, 22, 10],
}
# Seconds before the ball is played, by trigger
DELAY_SEC = {"goal_kick": (10, 25), "after_save": (3, 8), "after_claim": (3, 8), "back_pass": (2, 5)}
BACK_PASS_RATE = 0.20    # share of quiet possessions that go back to the keeper
BEST_OPTION_RATE = 0.70  # how often the keeper picks the best option
SHOT_WINDOW_SEC = 30     # a distribution "led to a shot" if one follows within this

# ---------- Traffic: the bodies around an event ----------
# Events in the attacking third (at least this far up the pitch, i.e. within
# 35 m of the goal) record the players standing around them, so vision.py can
# tell whether a body blocks the keeper's line of sight.
TRAFFIC_FROM_X = 70
DEFENDING_TYPES = ("tackle", "possession_change")  # done by the defending team


# ---------- Match state (reset by generate) ----------

events = []
clock = [0]
score = {name: 0 for name in TEAMS}
context_rng = random.Random()  # extra shot context, separate stream (see generate)
traffic_rng = random.Random()  # where the other players stand, separate stream too


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def other(team):
    return next(name for name in TEAMS if name != team)


def tick(low, high):
    clock[0] += random.randint(low, high)


def add(team, player, etype, x, y, **extra):
    minute, second = divmod(clock[0], 60)
    event = {
        "minute": minute,
        "second": second,
        "half": 1 if minute < 45 else 2,
        "team": team,
        "player": player,
        "type": etype,
        "x": round(x, 1),
        "y": round(y, 1),
    }
    event.update(extra)
    events.append(event)
    return len(events) - 1


# ---------- Keeper distribution ----------

def passing_options(team, keeper_x, keeper_y, pressure):
    """2-4 teammates the keeper could pass to, with where they stand and how
    open they are (open_m = meters to the nearest opponent)."""
    picks = random.sample(range(10), random.randint(2, 4))
    if not any(ROLES[i] in SHORT_ROLES for i in picks):  # always one short option
        picks[0] = random.choice([i for i, r in enumerate(ROLES) if r in SHORT_ROLES])
    options = []
    for i in picks:
        role = ROLES[i]
        (x0, x1), (y0, y1) = ROLE_AREAS[role]
        x, y = random.uniform(x0, x1), random.uniform(y0, y1)
        if role in ("FB", "W") and random.random() < 0.5:
            y = 68 - y  # other flank
        if role in SHORT_ROLES:
            # Near the keeper, the press decides how open you are
            open_m = {"low": random.uniform(4, 14), "medium": random.uniform(2.5, 10),
                      "high": random.uniform(1, 7)}[pressure]
        else:
            open_m = random.uniform(1.5, 9)
        options.append({"player": TEAMS[team]["outfield"][i], "role": role,
                        "x": round(x, 1), "y": round(y, 1),
                        "distance_m": round(math.hypot(x - keeper_x, y - keeper_y), 1),
                        "open_m": round(open_m, 1)})
    return options


def pick_technique(trigger, method, distance_m):
    if method == "throw":
        return "overarm" if distance_m > 20 else "sidearm"
    if method == "roll":
        return "bowled"
    if method == "ground_pass":
        return "pass_out_from_back" if trigger in ("goal_kick", "back_pass") else "side_foot"
    # kicks
    if trigger == "goal_kick":
        return "goal_kick_long"
    if trigger == "back_pass":
        return "driven_low" if distance_m < 45 else "lofted"
    return random.choice(["drop_kick", "volley"])  # from the hands


def pick_reason(trigger, method, pressure, target, keeper_y):
    """Why the keeper chose this pass, from the situation."""
    long_ball = method == "kick"
    if trigger in ("after_save", "after_claim") and target["x"] > 40 and pressure == "low":
        return "quick_counter"
    if long_ball and pressure != "low":
        return "break_press_long"
    if abs(target["y"] - keeper_y) > 22:
        return "switch_play"
    if pressure != "low":
        return "relieve_press"
    if target["open_m"] >= 8:
        return "free_man"
    return "safe_retention"


def direction_of(dx, dy):
    if dx < -2:
        return "backward"
    if abs(dy) > dx:
        return "lateral"
    return "forward"


def body(team, role, x, y):
    """One player standing on the pitch (part of an event's traffic)."""
    return {"team": team, "role": role,
            "x": round(clamp(x, 0.5, 104.5), 1), "y": round(clamp(y, 0.5, 67.5), 1)}


def distribution_traffic(team, keeper_x, keeper_y, close, options):
    """Opponents around a distribution, in the keeper's own frame:
      - `close` pressers 3-10 m in front of the keeper (that is what pressure means)
      - for each option, its nearest opponent exactly `open_m` away from it
    Positions are re-drawn until every option's nearest opponent really is its
    marker at open_m (nobody else stands closer to it)."""
    opp = other(team)

    def crowds(x, y, skip=None):
        """Would a body here stand closer to some option than its marker?"""
        return any(o is not skip and math.hypot(x - o["x"], y - o["y"]) < o["open_m"] for o in options)

    bodies = []
    for _ in range(close):
        for _ in range(40):
            d = traffic_rng.uniform(3, 9.8)
            a = math.radians(traffic_rng.uniform(-70, 70))  # in front of the keeper
            x, y = keeper_x + d * math.cos(a), keeper_y + d * math.sin(a)
            if not crowds(x, y):
                break
        bodies.append(body(opp, "presser", x, y))
    for o in options:
        for _ in range(40):
            a = traffic_rng.uniform(0, 2 * math.pi)
            x, y = o["x"] + o["open_m"] * math.cos(a), o["y"] + o["open_m"] * math.sin(a)
            if 0.5 <= x <= 104.5 and 0.5 <= y <= 67.5 and not crowds(x, y, skip=o):
                break
        bodies.append(body(opp, "marker", x, y))

    # If no clean spot was found, keep the data honest: open_m becomes the real
    # distance to the nearest opponent
    for o in options:
        nearest = min(math.hypot(b["x"] - o["x"], b["y"] - o["y"]) for b in bodies)
        if abs(nearest - o["open_m"]) > 0.15:
            o["open_m"] = round(nearest, 1)
    return bodies


def in_shot_lane(x, y, ball_x, ball_y):
    """Inside the triangle between the ball and the two posts (attacking frame)?"""
    def side(ax, ay, bx, by):
        return (bx - ax) * (y - ay) - (by - ay) * (x - ax)
    p1, p2 = (105.0, GOAL_Y_MIN), (105.0, GOAL_Y_MAX)
    s1 = side(ball_x, ball_y, *p1)
    s2 = side(*p1, *p2)
    s3 = side(*p2, ball_x, ball_y)
    return (s1 >= 0 and s2 >= 0 and s3 >= 0) or (s1 <= 0 and s2 <= 0 and s3 <= 0)


def rounded(x, y):
    """A position exactly as body() will store it, so lane checks see the same numbers."""
    return round(clamp(x, 0.5, 104.5), 1), round(clamp(y, 0.5, 67.5), 1)


def lane_spot(bx, by):
    """A spot inside the shooting lane, between 20% and 85% of the way to goal."""
    for _ in range(60):
        t = traffic_rng.uniform(0.2, 0.85)
        aim = traffic_rng.uniform(GOAL_Y_MIN + 0.5, GOAL_Y_MAX - 0.5)
        x, y = rounded(bx + t * (105 - bx), by + t * (aim - by))
        if in_shot_lane(x, y, bx, by) and math.hypot(x - bx, y - by) > 1.0:
            return x, y
    return rounded(bx + 0.5 * (105 - bx), by + 0.5 * (34 - by))  # halfway to the goal centre


def off_lane_spot(bx, by, x_range):
    """A spot near the goal that is NOT in the shooting lane."""
    for _ in range(80):
        x, y = rounded(traffic_rng.uniform(*x_range), clamp(traffic_rng.gauss(34, 12), 1, 67))
        if not in_shot_lane(x, y, bx, by) and math.hypot(x - bx, y - by) > 1.5:
            return x, y
    return rounded(x_range[0], 3.0)  # far wide, never in the lane


def event_traffic(event, attacking, defending, out):
    """The bodies around an attacking-third event (attacking frame, goal at
    x = 105). For a shot, exactly `defenders_in_lane` defenders stand in the
    shooting lane and everybody else stands outside it, so the number in the
    data and the bodies agree."""
    bx, by = event["x"], event["y"]
    bodies = []
    breakaway = event.get("situation") in ("one_on_one", "two_on_one")
    if event["type"] == "shot":
        for _ in range(event["defenders_in_lane"]):
            bodies.append(body(defending, "defender", *lane_spot(bx, by)))
        if breakaway:
            # Beaten defenders chasing back, behind the ball (never in the lane)
            for _ in range(traffic_rng.randint(1, 2)):
                x, y = rounded(bx - traffic_rng.uniform(3, 12), by + traffic_rng.gauss(0, 4))
                bodies.append(body(defending, "defender", x, y))
        else:
            for _ in range(traffic_rng.randint(1, 3)):
                bodies.append(body(defending, "defender",
                                   *off_lane_spot(bx, by, (max(bx - 4, 75), 103.5))))
    else:
        # Defenders drop between the ball and their goal, most of them off the direct line
        for _ in range(traffic_rng.randint(3, 6) if bx >= 88 else traffic_rng.randint(2, 4)):
            t = traffic_rng.uniform(0.2, 0.95)
            x = bx + t * (105 - bx)
            y = by + t * (traffic_rng.gauss(34, 3) - by) + traffic_rng.gauss(0, 4)
            if math.hypot(x - bx, y - by) < 1.5:
                y += 2.0  # not on top of the ball
            bodies.append(body(defending, "defender", x, y))
    if event["type"] == "shot" and breakaway:
        # Alone (one on one), or with the teammate who just squared it (two on one)
        if event["situation"] == "two_on_one":
            passer = out[event["assist_id"]]
            if not in_shot_lane(passer["x"], passer["y"], bx, by):
                bodies.append(body(attacking, "attacker", passer["x"], passer["y"]))
    elif bx >= 80:  # attackers waiting in the box (kept out of a shot's lane)
        for _ in range(traffic_rng.randint(1, 3)):
            for _ in range(40):
                x, y = rounded(traffic_rng.uniform(90, 103), traffic_rng.uniform(24, 44))
                if event["type"] != "shot" or not in_shot_lane(x, y, bx, by):
                    break
            if event["type"] == "shot" and in_shot_lane(x, y, bx, by):
                x, y = off_lane_spot(bx, by, (90, 103))
            bodies.append(body(attacking, "attacker", x, y))
    return bodies


def add_traffic(out):
    """Give every attacking-third event (except keeper actions and goal
    celebrations, which need none) the bodies standing around it."""
    for e in out:
        if e["type"].startswith("keeper_") or e["type"] == "goal" or e["x"] < TRAFFIC_FROM_X:
            continue
        if e["type"] in DEFENDING_TYPES:  # recorded in the ATTACKING team's frame
            attacking, defending = other(e["team"]), e["team"]
        else:
            attacking, defending = e["team"], other(e["team"])
        e["traffic"] = event_traffic(e, attacking, defending, out)


def distribute(team, trigger, keeper_x, keeper_y):
    """The keeper of `team` plays the ball. keeper_x/keeper_y are in the
    team's OWN frame (keeper near x = 2-6). Returns the team with the ball next."""
    tick(*DELAY_SEC[trigger])
    keeper_x = clamp(keeper_x, 2.0, 6.0)  # a keeper on the line steps forward to release
    close = random.choices([0, 1, 2, 3], weights=CLOSE_OPPONENT_WEIGHTS[trigger])[0]
    pressure = "low" if close == 0 else "medium" if close == 1 else "high"

    # The keeper can only choose what they can see. They scan up the pitch
    # (toward the center spot); options outside that sightline, or hidden
    # behind a presser or a marker, are invisible.
    options = passing_options(team, keeper_x, keeper_y, pressure)
    traffic = distribution_traffic(team, keeper_x, keeper_y, close, options)
    blockers = [(b["x"], b["y"]) for b in traffic]
    facing = vision.facing_angle((keeper_x, keeper_y), (52.5, 34.0))
    for o in options:
        o["visible"] = vision.is_visible((keeper_x, keeper_y), facing, (o["x"], o["y"]),
                                         blockers=blockers)
    seen = [o for o in options if o["visible"]]
    if not seen:  # nothing in view: the keeper turns to the nearest teammate
        nearest = min(options, key=lambda o: o["distance_m"])
        nearest["visible"] = True
        seen = [nearest]

    # Choose a target among the visible options: usually, not always, the best one
    values = [option_value(trigger, o, pressure, keeper_x) for o in seen]
    best = seen[values.index(max(values))]
    if random.random() < BEST_OPTION_RATE or len(seen) == 1:
        target = best
    else:
        target = random.choice([o for o in seen if o is not best])

    method = pick_method(trigger, target["distance_m"])
    p = pass_success_prob(method, target["distance_m"], target["open_m"], pressure)
    success = random.random() < p
    if method == "kick":  # long balls are often contested in the air
        contested = random.random() < 0.6
        outcome = ("contested_won" if contested else "completed") if success else \
                  ("contested_lost" if contested else "intercepted")
    else:
        outcome = "completed" if success else "intercepted"

    add(team, TEAMS[team]["keeper"], "keeper_distribution", keeper_x, keeper_y,
        kind="long" if method == "kick" else "short",
        trigger=trigger,
        method=method,
        technique=pick_technique(trigger, method, target["distance_m"]),
        target_player=target["player"],
        target_role=target["role"],
        target_x=target["x"],
        target_y=target["y"],
        distance_m=target["distance_m"],
        direction=direction_of(target["x"] - keeper_x, target["y"] - keeper_y),
        pressure=pressure,
        opponents_close=close,
        options=options,
        reason=pick_reason(trigger, method, pressure, target, keeper_y),
        outcome=outcome,
        x_gain_m=round(target["x"] - keeper_x, 1),
        led_to_shot=False,  # filled in by mark_shots_from_distribution()
        shot_id=None,
        traffic=traffic)
    return team if outcome in SUCCESS else other(team)


def mark_shots_from_distribution(out):
    """A completed distribution 'led to a shot' if the same team shoots within
    SHOT_WINDOW_SEC seconds without the other team touching the ball first."""
    def seconds(e):
        return e["minute"] * 60 + e["second"]
    for i, d in enumerate(out):
        if d["type"] != "keeper_distribution" or d["outcome"] not in SUCCESS:
            continue
        for later in out[i + 1:]:
            if seconds(later) - seconds(d) > SHOT_WINDOW_SEC or later["team"] != d["team"]:
                break  # too late, or the other team had the ball
            if later["type"] == "shot":
                d["led_to_shot"], d["shot_id"] = True, later["id"]
                break


# ---------- Shots and possessions ----------

# ---------- Shot situations ----------
# Every shot comes from a situation, with the build-up events that lead to it.
# The situation decides where the shot is struck from, where the keeper is,
# whether the keeper is set, and how dangerous it is.
SITUATION_WEIGHTS = {  # for a shot at the end of an attack
    "open_play": 0.55, "cutback": 0.12, "header_from_cross": 0.12,
    "one_on_one": 0.11, "two_on_one": 0.10,
}
# Rebound (after a parried save) and second_ball (after a blocked shot) come
# from what happens to an earlier shot, not from this table.
SITUATION_GOAL_BONUS = {  # extra chance of a goal on top of placement, pace and distance
    "open_play": 0.0, "cutback": 0.05, "header_from_cross": 0.0, "one_on_one": 0.13,
    "two_on_one": 0.20, "rebound": 0.20, "second_ball": 0.0,
}
SITUATION_SET_CHANCE = {  # chance the keeper is balanced and ready when the shot is struck
    "cutback": 0.40, "header_from_cross": 0.60, "one_on_one": 0.60,
    "two_on_one": 0.12, "rebound": 0.15, "second_ball": 0.70,
}  # open play depends on how far the ball moved just before (see build_up)
SITUATION_LANE_CHANCE = {  # chance each of 3 defenders is in the shooting lane
    "one_on_one": 0.02, "two_on_one": 0.06, "rebound": 0.25,
}  # others: more likely on long shots (see shot_context)
HELD_SAVE_RATE = 0.55        # saves the keeper holds; the rest are parried
REBOUND_RATE = 0.40          # parried saves an attacker follows up
SECOND_BALL_RATE = 0.30      # blocked shots that fall to an attacker
AIM_AWAY = 1.2               # how strongly shooters aim at the side the keeper left open


def shot_context(distance, situation, set_chance):
    """Extra facts about how a shot was struck, used by the saveability score."""
    p_defender = SITUATION_LANE_CHANCE.get(situation, clamp(0.1 + distance / 60, 0.1, 0.6))
    return {
        "defenders_in_lane": sum(context_rng.random() < p_defender for _ in range(3)),
        "deflected": context_rng.random() < 0.08,
        "swerve": round(context_rng.random(), 2),  # 0 = straight, 1 = big late movement
        "keeper_set": context_rng.random() < set_chance,  # balanced and ready when struck
    }


def side_of_goal():
    """-1 for the y = 0 side of the pitch, +1 for the y = 68 side."""
    return random.choice([-1, 1])


def build_up(team, opp, situation, last_x, last_y):
    """Add the events that lead to a shot in this situation, and return how the
    shot happens: shooter, where it is struck, where the keeper stands, and how
    likely the keeper is to be set. Everything is in the attacking frame."""
    squad, keeper = TEAMS[team]["outfield"], TEAMS[opp]["keeper"]
    shooter = random.choices(squad, weights=SHOOTER_WEIGHTS)[0]
    teammate = random.choice([p for p in squad if p != shooter])
    shot = {"shooter": shooter, "body_part": "foot", "speed": random.randint(75, 125),
            "keeper_x": 105 - random.uniform(0.8, 4.0), "keeper_y": None}

    if situation == "open_play":
        # Struck near where the move ended, drifting toward the middle
        shot["x"] = clamp(last_x + random.uniform(0, 6), 80, 101)
        shot["y"] = clamp(last_y + (34 - last_y) * 0.35 + random.gauss(0, 3), 6, 62)
        if shot["x"] > 94 and random.random() < 0.18:
            shot["body_part"] = "head"
        # The more the ball moved across just before, the less likely the keeper is set
        shot["set_chance"] = clamp(0.92 - 0.02 * abs(shot["y"] - last_y), 0.5, 0.92)
        shot["assist_id"], shot["assist_type"] = len(events) - 1, events[-1]["type"]

    elif situation == "cutback":
        # A winger reaches the byline and pulls it back to a runner arriving in the middle
        side = side_of_goal()
        tick(2, 4)
        px, py = random.uniform(99, 103.5), 34 + side * random.uniform(16, 26)
        shot["assist_id"] = add(team, teammate, "pass", px, py, receiver=shooter, success=True,
                                assist="cutback")
        shot["assist_type"] = "cutback"
        shot["x"], shot["y"] = random.uniform(88, 95), clamp(random.gauss(34, 4), 24, 44)
        shot["keeper_y"] = 34 + side * random.uniform(1.5, 3.0)  # was guarding the near post
        shot["keeper_x"] = 105 - random.uniform(0.5, 1.5)

    elif situation == "header_from_cross":
        side = side_of_goal()
        tick(2, 4)
        cx, cy = random.uniform(82, 98), 34 + side * random.uniform(18, 28)
        shot["assist_id"] = add(team, teammate, "cross", cx, cy)
        shot["assist_type"] = "cross"
        shot["x"], shot["y"] = random.uniform(93, 100), clamp(random.gauss(34, 3.5), 26, 42)
        shot["body_part"], shot["speed"] = "head", random.randint(50, 85)
        shot["keeper_y"] = 34 + side * random.uniform(0.5, 2.0)  # moved toward the cross

    elif situation == "one_on_one":
        # A through ball sends the shooter clear; the keeper comes out to narrow the angle
        tick(2, 4)
        shot["assist_id"] = add(team, teammate, "through_ball", random.uniform(55, 72),
                                random.uniform(20, 48))
        shot["assist_type"] = "through_ball"
        shot["x"], shot["y"] = random.uniform(89, 96), clamp(random.gauss(34, 5), 22, 46)
        tick(2, 3)
        kx = 105 - random.uniform(4, 9)
        ky = 34 + (shot["y"] - 34) * 0.5
        add(opp, keeper, "keeper_close_down", kx, ky, target_player=shooter)
        shot["keeper_x"], shot["keeper_y"] = kx, ky

    elif situation == "two_on_one":
        # Two attackers against the keeper: the keeper closes down the ball
        # carrier, who squares it to the free attacker
        tick(2, 4)
        add(team, random.choice([p for p in squad if p not in (shooter, teammate)]),
            "through_ball", random.uniform(55, 72), random.uniform(20, 48))
        side = side_of_goal()
        ax, ay = random.uniform(88, 95), 34 + side * random.uniform(4, 9)
        tick(2, 3)
        kx = 105 - random.uniform(3, 7)
        ky = 34 + (ay - 34) * 0.6
        add(opp, keeper, "keeper_close_down", kx, ky, target_player=teammate)
        tick(1, 1)  # the square pass comes straight away
        shot["x"], shot["y"] = random.uniform(90, 97), clamp(ay - side * random.uniform(7, 13), 18, 50)
        shot["assist_id"] = add(team, teammate, "pass", ax, ay, receiver=shooter, success=True,
                                assist="square")
        shot["assist_type"] = "square"
        # The keeper scrambles back about a meter toward the new shooter
        shot["keeper_x"] = kx
        shot["keeper_y"] = ky + (1.0 if shot["y"] > ky else -1.0)

    shot["set_chance"] = shot.get("set_chance", SITUATION_SET_CHANCE.get(situation, 0.85))
    if shot["keeper_y"] is None:
        shot["keeper_y"] = 34 + (shot["y"] - 34) * 0.12 + random.gauss(0, 0.6)
    shot["keeper_y"] = clamp(shot["keeper_y"], 26.0, 42.0)
    return shot


def follow_up(team, opp, situation, ball_x, ball_y, keeper_x, keeper_y, assist_id, depth):
    """A second shot straight after a parried save (rebound) or a block
    (second ball). The keeper is wherever the first shot left them."""
    squad = TEAMS[team]["outfield"]
    shot = {"shooter": random.choices(squad, weights=SHOOTER_WEIGHTS)[0], "body_part": "foot",
            "assist_id": assist_id, "assist_type": situation,
            "set_chance": SITUATION_SET_CHANCE[situation]}
    if situation == "rebound":
        # The ball spills a few meters from the keeper; a snap shot from close in
        shot["x"] = clamp(ball_x - random.uniform(5, 11), 93, 100)
        shot["y"] = clamp(ball_y + random.gauss(0, 5), 24, 44)
        shot["speed"] = random.randint(60, 110)
        shot["keeper_x"], shot["keeper_y"] = keeper_x, keeper_y  # still where they saved it
    else:
        shot["x"] = random.uniform(82, 95)
        shot["y"] = clamp(random.gauss(34, 8), 12, 56)
        shot["speed"] = random.randint(75, 125)
        shot["keeper_x"] = 105 - random.uniform(0.8, 3.0)
        shot["keeper_y"] = clamp(34 + (shot["y"] - 34) * 0.12 + random.gauss(0, 0.6), 26, 42)
    return take_shot(team, opp, situation=situation, plan=shot, depth=depth)


def take_shot(team, opp, last_x=90.0, last_y=34.0, situation=None, plan=None, depth=0):
    """One shot, its build-up and the keeper's reaction. Returns the team with
    the ball next. `plan` is given for follow-up shots (rebound, second ball);
    otherwise a situation is drawn and its build-up events are added first."""
    keeper = TEAMS[opp]["keeper"]
    if plan is None:
        situation = random.choices(list(SITUATION_WEIGHTS), weights=SITUATION_WEIGHTS.values())[0]
        plan = build_up(team, opp, situation, last_x, last_y)
    shooter, x, y = plan["shooter"], plan["x"], plan["y"]
    distance = math.hypot(105 - x, 34 - y)
    keeper_x, keeper_y = plan["keeper_x"], plan["keeper_y"]
    context = shot_context(distance, situation, plan["set_chance"])
    base = {
        "situation": situation,
        "assist_id": plan["assist_id"],
        "assist_type": plan["assist_type"],
        "distance_m": round(distance, 1),
        "speed_kmh": plan["speed"],
        "body_part": plan["body_part"],
        "keeper": keeper,
        "keeper_x": round(keeper_x, 1),
        "keeper_y": round(keeper_y, 1),
        **context,
        # filled in by add_shot_timing(): seconds_since_keeper_action, ball_shift_m, assist_seconds
    }
    if situation in ("rebound", "two_on_one"):
        tick(1, 2)  # no time to waste: the shot comes straight away
    else:
        tick(1, 3)
    roll = random.random()

    if roll < 0.15:  # blocked
        shot_id = add(team, shooter, "shot", x, y, outcome="blocked", **base)
        if depth < 2 and random.random() < SECOND_BALL_RATE:  # it falls to another attacker
            tick(1, 3)
            return follow_up(team, opp, "second_ball", x, y, keeper_x, keeper_y, shot_id, depth + 1)
        return opp

    if roll < 0.15 + 0.85 * 0.45:  # off target: wide or over the bar
        if random.random() < 0.5:
            end_y = random.choice([random.uniform(26, GOAL_Y_MIN - 0.3),
                                   random.uniform(GOAL_Y_MAX + 0.3, 42)])
            end_z = random.uniform(0.2, 2.2)
        else:
            end_y = random.uniform(GOAL_Y_MIN, GOAL_Y_MAX)
            end_z = random.uniform(2.6, 4.0)
        add(team, shooter, "shot", x, y, outcome="off_target",
            end_y=round(end_y, 2), end_z=round(end_z, 2), **base)
        # Goal kick from the six-yard box, in the keeper's own frame
        return distribute(opp, "goal_kick", 5.5, random.uniform(26, 42))

    # On target: goal or save. Shooters aim away from the keeper: the further
    # the keeper is off-centre, the more the aim goes to the side left open.
    # Harder to stop when placed in a corner, hit hard, from close in, from a
    # dangerous situation, or with the keeper not set.
    aim = 34 - (keeper_y - 34) * AIM_AWAY
    end_y = clamp(random.gauss(aim, 2.0), GOAL_Y_MIN + 0.2, GOAL_Y_MAX - 0.2)
    end_z = random.uniform(0.15, 2.3)
    placement = 0.5 * abs(end_y - 34) / 3.66 + 0.5 * end_z / GOAL_H
    p_goal = clamp(-0.09 + 0.30 * placement + 0.15 * (plan["speed"] - 75) / 50
                   + 0.20 * max(0.0, (30 - distance) / 30)
                   + SITUATION_GOAL_BONUS[situation]
                   + (0.0 if context["keeper_set"] else 0.06), 0.02, 0.85)
    goal = random.random() < p_goal
    shot_id = add(team, shooter, "shot", x, y, outcome="goal" if goal else "saved",
                  end_y=round(end_y, 2), end_z=round(end_z, 2), **base)
    tick(1, 2)

    if goal:
        score[team] += 1
        add(team, shooter, "goal", x, y, related_to=shot_id,
            score="-".join(str(score[n]) for n in TEAMS))
        return opp

    save_y = clamp(end_y + random.gauss(0, 0.3), GOAL_Y_MIN, GOAL_Y_MAX)
    held = random.random() < HELD_SAVE_RATE
    save_id = add(opp, keeper, "keeper_save", keeper_x, save_y,
                  related_to=shot_id, end_z=round(end_z, 2), held=held)
    if held:  # the keeper holds it: convert to the keeper's own frame
        return distribute(opp, "after_save", 105 - keeper_x, 68 - save_y)
    if depth < 2 and random.random() < REBOUND_RATE:  # parried, and an attacker follows up
        tick(1, 2)
        return follow_up(team, opp, "rebound", keeper_x, save_y, keeper_x, save_y, save_id, depth + 1)
    return opp


def add_shot_timing(out):
    """Fill in the timing facts on every shot, from the events around it:
      assist_seconds              seconds from the assist to the shot
      ball_shift_m                how far the ball moved sideways from the assist to the shot
      seconds_since_keeper_action seconds since the defending keeper last had to act
                                  (save, claim, sweep, close-down or distribution), or None"""
    def seconds(e):
        return e["minute"] * 60 + e["second"]
    for shot in out:
        if shot["type"] != "shot":
            continue
        assist = out[shot["assist_id"]]
        shot["assist_seconds"] = seconds(shot) - seconds(assist)
        shot["ball_shift_m"] = round(abs(shot["y"] - assist["y"]), 1)
        last_action = next((e for e in reversed(out[:shot["id"]])
                            if e["player"] == shot["keeper"] and e["type"].startswith("keeper_")), None)
        shot["seconds_since_keeper_action"] = (seconds(shot) - seconds(last_action)
                                               if last_action else None)


def end_with_turnover(opp, x, y):
    tick(1, 3)
    defender = random.choice(TEAMS[opp]["outfield"])
    etype = "tackle" if random.random() < 0.5 else "possession_change"
    add(opp, defender, etype, x, y)
    return opp


def back_pass(team):
    """A defender plays it back to their own keeper, who then distributes."""
    tick(2, 5)
    defenders = [p for p, r in zip(TEAMS[team]["outfield"], ROLES) if r in ("CB", "FB", "DM")]
    add(team, random.choice(defenders), "pass", random.uniform(14, 32), random.uniform(12, 56),
        receiver=TEAMS[team]["keeper"], success=True)
    return distribute(team, "back_pass", random.uniform(2, 6), clamp(random.gauss(34, 4), 26, 42))


def play_possession(team):
    """Plays one possession. Returns the team that gets the ball next."""
    opp = other(team)
    squad = TEAMS[team]["outfield"]
    rate = TEAMS[team]["attack_rate"] + (0.06 if clock[0] > 70 * 60 else 0.0)
    is_attack = random.random() < rate
    start_x = random.uniform(15, 50)
    steps = random.randint(5, 12) if is_attack else random.randint(3, 8)
    top_x = 100 if is_attack else random.uniform(55, 78)
    xs = sorted(random.uniform(start_x, top_x) for _ in range(steps))
    entered_box = False
    x, y = start_x, 34.0

    for x in xs:
        y = random.uniform(8, 60)
        player = random.choice(squad)
        tick(2, 6)
        if x >= 88 and not entered_box:
            entered_box = True
            add(team, player, "box_entry", x, y)
        elif x > 72 and (y < 16 or y > 52) and random.random() < 0.3:
            add(team, player, "cross", x, y)
        elif x > 55 and random.random() < 0.12:
            add(team, player, "through_ball", x, y)
        else:
            receiver = random.choice([p for p in squad if p != player])
            add(team, player, "pass", x, y, receiver=receiver, success=True)

    if not is_attack:
        if random.random() < BACK_PASS_RATE:  # pressed: recycle through the keeper
            return back_pass(team)
        return end_with_turnover(opp, x, y)

    roll = random.random()
    if roll < 0.70:
        return take_shot(team, opp, x, y)
    keeper = TEAMS[opp]["keeper"]
    tick(1, 3)
    if roll < 0.82:  # cross claimed by the keeper (attacking frame)
        kx = random.uniform(100, 103.5)
        ky = clamp(random.gauss(34, 2.5), 30, 38)
        add(opp, keeper, "keeper_claim", kx, ky)
        return distribute(opp, "after_claim", 105 - kx, 68 - ky)  # convert to own frame
    if roll < 0.90:  # keeper sweeps up a through ball
        add(opp, keeper, "keeper_sweep", random.uniform(88, 96),
            clamp(random.gauss(34, 6), 20, 48))
        return opp
    return end_with_turnover(opp, x, y)


def generate(seed):
    """Play a whole match with this seed and return {"match": ..., "events": [...]}.
    The same seed always gives the same match."""
    random.seed(seed)
    context_rng.seed(seed + 1)  # separate stream for the extra shot context
    traffic_rng.seed(seed + 2)  # separate stream for where the other players stand
    events.clear()
    clock[0] = 0
    for name in score:
        score[name] = 0

    team = random.choice(list(TEAMS))
    while clock[0] < MATCH_SECONDS:
        team = play_possession(team)

    out = [{"id": i, **e} for i, e in enumerate(events)]
    mark_shots_from_distribution(out)
    add_shot_timing(out)
    add_traffic(out)
    names = list(TEAMS)
    match = {
        "match_id": "SYN-001",
        "home": names[0],
        "away": names[1],
        "seed": seed,
        "final_score": dict(score),
        "pitch": {"length_m": 105, "width_m": 68, "goal_width_m": 7.32, "goal_height_m": 2.44},
        "coordinate_note": ("Most events are in the attacking team's frame: attacking toward "
                            "x=105, goal centered at y=34. keeper_distribution events (and their "
                            "target_x/target_y and options) are in the distributing team's own "
                            "frame: that team attacks toward x=105, so its keeper is near x=2-6."),
    }
    return {"match": match, "events": out}


def main():
    data = generate(SEED)
    with open("match_events.json", "w") as f:
        json.dump(data, f, indent=2)

    out, names = data["events"], list(TEAMS)
    print(f"Final score: {names[0]} {score[names[0]]} - {score[names[1]]} {names[1]}")
    for name in names:
        shots = [e for e in out if e["type"] == "shot" and e["team"] == name]
        on_target = [e for e in shots if e["outcome"] in ("goal", "saved")]
        dists = [e for e in out if e["type"] == "keeper_distribution" and e["team"] == name]
        print(f"{name}: {len(shots)} shots, {len(on_target)} on target, {score[name]} goals, "
              f"{len(dists)} keeper distributions")
    print(f"Total events: {len(out)}")


if __name__ == "__main__":
    main()
