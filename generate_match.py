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

from scoring import SUCCESS, option_value, pass_success_prob, pick_method

SEED = 42

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


# ---------- Match state (reset by generate) ----------

events = []
clock = [0]
score = {name: 0 for name in TEAMS}
context_rng = random.Random()  # extra shot context, separate stream (see generate)


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


def distribute(team, trigger, keeper_x, keeper_y):
    """The keeper of `team` plays the ball. keeper_x/keeper_y are in the
    team's OWN frame (keeper near x = 2-6). Returns the team with the ball next."""
    tick(*DELAY_SEC[trigger])
    keeper_x = clamp(keeper_x, 2.0, 6.0)  # a keeper on the line steps forward to release
    close = random.choices([0, 1, 2, 3], weights=CLOSE_OPPONENT_WEIGHTS[trigger])[0]
    pressure = "low" if close == 0 else "medium" if close == 1 else "high"

    # Choose a target: usually, not always, the best option
    options = passing_options(team, keeper_x, keeper_y, pressure)
    values = [option_value(trigger, o, pressure, keeper_x) for o in options]
    best = options[values.index(max(values))]
    if random.random() < BEST_OPTION_RATE:
        target = best
    else:
        target = random.choice([o for o in options if o is not best])

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
        shot_id=None)
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

def shot_context(distance):
    """Extra facts about how a shot was struck, used by the saveability score."""
    # Each of 3 defenders may stand in the shooting lane; more likely on long shots
    p_defender = clamp(0.1 + distance / 60, 0.1, 0.6)
    return {
        "defenders_in_lane": sum(context_rng.random() < p_defender for _ in range(3)),
        "deflected": context_rng.random() < 0.08,
        "swerve": round(context_rng.random(), 2),  # 0 = straight, 1 = big late movement
        "keeper_set": context_rng.random() < 0.85,  # balanced and ready when struck
    }


def take_shot(team, opp):
    """One shot, including the keeper's reaction. Returns the team with the ball next."""
    shooter = random.choices(TEAMS[team]["outfield"], weights=SHOOTER_WEIGHTS)[0]
    keeper = TEAMS[opp]["keeper"]
    x = random.uniform(80, 101)
    y = clamp(random.gauss(34, 9), 6, 62)
    distance = math.hypot(105 - x, 34 - y)
    speed = random.randint(75, 125)
    body_part = "head" if (x > 94 and random.random() < 0.18) else "foot"
    keeper_x = 105 - random.uniform(0.8, 4.0)
    keeper_y = clamp(34 + (y - 34) * 0.12 + random.gauss(0, 0.6), 31.0, 37.0)
    base = {
        "distance_m": round(distance, 1),
        "speed_kmh": speed,
        "body_part": body_part,
        "keeper": keeper,
        "keeper_x": round(keeper_x, 1),
        "keeper_y": round(keeper_y, 1),
        **shot_context(distance),
    }
    tick(1, 3)
    roll = random.random()

    if roll < 0.15:  # blocked
        add(team, shooter, "shot", x, y, outcome="blocked", **base)
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

    # on target: goal or save, harder to stop when placed in a corner and hit hard
    end_y = clamp(random.gauss(34, 2.0), GOAL_Y_MIN + 0.2, GOAL_Y_MAX - 0.2)
    end_z = random.uniform(0.15, 2.3)
    placement = 0.5 * abs(end_y - 34) / 3.66 + 0.5 * end_z / GOAL_H
    p_goal = clamp(0.02 + 0.30 * placement + 0.15 * (speed - 75) / 50
                   + 0.20 * max(0.0, (30 - distance) / 30), 0.02, 0.85)
    goal = random.random() < p_goal
    shot_id = add(team, shooter, "shot", x, y, outcome="goal" if goal else "saved",
                  end_y=round(end_y, 2), end_z=round(end_z, 2), **base)
    tick(1, 2)

    if goal:
        score[team] += 1
        add(team, shooter, "goal", x, y, related_to=shot_id,
            score="-".join(str(score[n]) for n in TEAMS))
        return opp

    add(opp, keeper, "keeper_save", keeper_x,
        clamp(end_y + random.gauss(0, 0.3), GOAL_Y_MIN, GOAL_Y_MAX),
        related_to=shot_id, end_z=round(end_z, 2))
    if random.random() < 0.5:  # the keeper held it: convert to the keeper's own frame
        return distribute(opp, "after_save", 105 - keeper_x, 68 - keeper_y)
    return opp


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
        return take_shot(team, opp)
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
    events.clear()
    clock[0] = 0
    for name in score:
        score[name] = 0

    team = random.choice(list(TEAMS))
    while clock[0] < MATCH_SECONDS:
        team = play_possession(team)

    out = [{"id": i, **e} for i, e in enumerate(events)]
    mark_shots_from_distribution(out)
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
