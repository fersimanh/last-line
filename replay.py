"""Live replay for Last Line.

Feeds the synthetic match to the scoring engine one event at a time, like a
live feed. `stream()` is a generator so the Streamlit app can reuse it later.

Run it:
    python3 replay.py              # whole match in about 9 seconds
    python3 replay.py --speed 60   # 1 match minute per real second
    python3 replay.py --speed 0    # no delay, instant
"""
import argparse
import json
import time

from scoring import MatchState


def load_match(path="match_events.json"):
    with open(path) as f:
        data = json.load(f)
    return data["match"], data["events"]


def stream(events, state, speed=600):
    """Yield (event, insight, snapshot) for each event, pausing between them.

    speed = match seconds per real second (600 = a 90-minute match in about
    9 seconds). speed = 0 means no pause.
    """
    previous = 0
    for event in events:
        now = event["minute"] * 60 + event["second"]
        if speed > 0 and now > previous:
            time.sleep((now - previous) / speed)
        previous = now
        insight = state.update(event)
        yield event, insight, state.snapshot(now)


def clock(event):
    return f"{event['minute']:02d}:{event['second']:02d}"


def describe(event, insight):
    """One printable line for a key moment, or None for quiet events."""
    t = clock(event)
    kind = event["type"]
    if kind == "shot":
        line = (f"{t}  SHOT   {event['team']} {event['player']} "
                f"({event['distance_m']} m, {event['speed_kmh']} km/h) -> {event['outcome']}")
        if insight:
            line += (f"\n         {insight['keeper']}: saveability {insight['saveability']}/100, "
                     f"{insight['verdict']} ({insight['key_factor']})")
        return line
    if kind == "goal":
        return f"{t}  GOAL!  {event['player']} scores. Score now {event['score']}"
    if kind == "keeper_save":
        return f"{t}  SAVE   {event['player']}"
    if kind == "keeper_claim":
        return f"{t}  CLAIM  {event['player']} collects the cross"
    if kind == "keeper_sweep":
        return f"{t}  SWEEP  {event['player']} comes out to clear"
    return None


def print_status(snapshot, minute):
    parts = [f"{team}: workload {s['workload']}, danger {s['danger']}"
             for team, s in snapshot.items()]
    print(f"--- {minute}' | " + " | ".join(parts))


def print_report(state):
    print("\n=== KEEPER REPORT ===")
    for team, r in state.keeper_report().items():
        print(f"{team}: faced {r['on_target']} on target, saved {r['saves']}, "
              f"conceded {r['goals_conceded']}, expected saves {r['expected_saves']}, "
              f"goals prevented {r['goals_prevented']:+}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--speed", type=float, default=600,
                        help="match seconds per real second (0 = instant)")
    parser.add_argument("--file", default="match_events.json")
    args = parser.parse_args()

    match, events = load_match(args.file)
    state = MatchState(match["home"], match["away"])
    print(f"{match['home']} vs {match['away']}\n")

    next_status = 15
    for event, insight, snapshot in stream(events, state, args.speed):
        if event["minute"] >= next_status:
            print_status(snapshot, next_status)
            next_status += 15
        line = describe(event, insight)
        if line:
            print(line)

    print(f"\nFull time: {match['home']} {match['final_score'][match['home']]} - "
          f"{match['final_score'][match['away']]} {match['away']}")
    print_report(state)


if __name__ == "__main__":
    main()
