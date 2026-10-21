"""Synthetic match generator for Last Line.

Coordinates are meters on a 105 x 68 pitch. Each possession is recorded in the
frame of the team attacking: they always attack toward x = 105, with the goal
centered at y = 34. Defending events (saves, claims, tackles) in that
possession use the same frame. Everything here is invented: fictional clubs,
fictional players, no real data.
"""
import json
import math
import random

SEED = 42
random.seed(SEED)

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

events = []
clock = [0]
score = {name: 0 for name in TEAMS}


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


def distribute(team, opp, keeper_x, keeper_y):
    """Keeper restarts play. Returns the team that gets the ball."""
    tick(3, 8)
    kind = random.choice(["short", "long"])
    completed = random.random() < (0.85 if kind == "short" else 0.55)
    add(opp, TEAMS[opp]["keeper"], "keeper_distribution", keeper_x, keeper_y,
        kind=kind, outcome="completed" if completed else "lost")
    return opp if completed else team


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
        return opp

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
    if random.random() < 0.5:
        return distribute(team, opp, keeper_x, keeper_y)
    return opp


def end_with_turnover(opp, x, y):
    tick(1, 3)
    defender = random.choice(TEAMS[opp]["outfield"])
    etype = "tackle" if random.random() < 0.5 else "possession_change"
    add(opp, defender, etype, x, y)
    return opp


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
        return end_with_turnover(opp, x, y)

    roll = random.random()
    if roll < 0.70:
        return take_shot(team, opp)
    keeper = TEAMS[opp]["keeper"]
    tick(1, 3)
    if roll < 0.82:  # cross claimed by the keeper
        kx = random.uniform(100, 103.5)
        ky = clamp(random.gauss(34, 2.5), 30, 38)
        add(opp, keeper, "keeper_claim", kx, ky)
        return distribute(team, opp, kx, ky)
    if roll < 0.90:  # keeper sweeps up a through ball
        add(opp, keeper, "keeper_sweep", random.uniform(88, 96),
            clamp(random.gauss(34, 6), 20, 48))
        return opp
    return end_with_turnover(opp, x, y)


def main():
    team = random.choice(list(TEAMS))
    while clock[0] < MATCH_SECONDS:
        team = play_possession(team)

    out = [{"id": i, **e} for i, e in enumerate(events)]
    names = list(TEAMS)
    match = {
        "match_id": "SYN-001",
        "home": names[0],
        "away": names[1],
        "seed": SEED,
        "final_score": dict(score),
        "pitch": {"length_m": 105, "width_m": 68, "goal_width_m": 7.32, "goal_height_m": 2.44},
        "coordinate_note": "Each possession is in the attacking team's frame: attacking toward x=105, goal centered at y=34.",
    }
    with open("match_events.json", "w") as f:
        json.dump({"match": match, "events": out}, f, indent=2)

    print(f"Final score: {names[0]} {score[names[0]]} - {score[names[1]]} {names[1]}")
    for name in names:
        shots = [e for e in out if e["type"] == "shot" and e["team"] == name]
        on_target = [e for e in shots if e["outcome"] in ("goal", "saved")]
        print(f"{name}: {len(shots)} shots, {len(on_target)} on target, {score[name]} goals")
    print(f"Total events: {len(out)}")


if __name__ == "__main__":
    main()