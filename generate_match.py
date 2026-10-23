"""Writes the match the app replays: match_events.json and tracking.npz.

The match comes from the position-based engine (sim_engine.py): 22 players
moving on a pitch, with events and 2 Hz tracking produced from those positions.
Everything is invented: fictional clubs and players, no real match data. The
same seed always gives the same match.

    python3 generate_match.py              # the demo seed
    python3 generate_match.py --seed 7     # another match
The older rule-based generator lives on in legacy_generator.py.
"""
import argparse
import json

import sim_engine

SEED = 99  # chosen from seeds 1-120: 2 goals, one busy keeper (6 saves) vs one quiet, a keeper back-pass and switch, a claimed corner, a free-kick wall
EVENTS_PATH, TRACKING_PATH = "match_events.json", "tracking.npz"


def generate(seed):
    """Play a whole match with this seed and return {"match": ..., "events": [...]}."""
    result = sim_engine.simulate(seed)
    return {"match": result["match"], "events": result["events"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    result = sim_engine.simulate(args.seed)
    sim_engine.save(result, EVENTS_PATH, TRACKING_PATH)
    match = result["match"]
    home, away = match["home"], match["away"]
    print(f"Seed {args.seed}: {home} {match['final_score'][home]} - {match['final_score'][away]} {away}, "
          f"{len(result['events'])} events")


if __name__ == "__main__":
    main()
