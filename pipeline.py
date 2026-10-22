"""Agent pipeline for Last Line.

Replays the match event by event. Every event updates the shared match
state, but only key moments go through the agents:

    Shot Analyst  ->  Narrator  ->  Personalizer (once per viewer)

If an agent fails, the moment still gets a fallback line built from the
saveability score and verdict, so the feed never goes silent.

Each moment is printed as one line of JSON (JSON Lines), ready for an app.

Run it (sign in first with `az login`):
    python3 pipeline.py                 # whole match
    python3 pipeline.py --only 67:03    # just the moment at 67:03
"""
import argparse
import asyncio
import json
from datetime import datetime, timezone

from agents import make_analyst, make_client, make_narrator, make_personalizer
from replay import clock, is_key_moment, load_match, stream
from scoring import MatchState

AGENT_TIMEOUT_SEC = 90  # give up on a slow agent and use the fallback

# Two example viewers. Each key moment gets one version per viewer.
VIEWERS = [
    {"name": "casual_en", "mode": "casual", "club": "Harbor United", "language": "en"},
    {"name": "analyst_es", "mode": "analyst", "club": "Northgate FC", "language": "es"},
]

# Translations for the fallback line, so Spanish viewers get Spanish
VERDICT_ES = {"should save": "debió pararlo", "tough save": "parada difícil",
              "near-unstoppable": "casi imparable"}


class LiveMatch:
    """The shared match-state object. The pipeline writes to it; the Shot
    Analyst's tools read from it (see agents.py)."""

    def __init__(self, match):
        self.match = match
        self.state = MatchState(match["home"], match["away"])
        self.score = "0-0"
        self.event = None      # the event being processed now
        self.insight = {}      # its saveability insight (empty if none)
        self.shot_insights = {}  # shot id -> insight, so a goal can find its shot

    def now(self):
        return self.event["minute"] * 60 + self.event["second"]


def fallback_text(live, viewer=None):
    """Plain line used when an agent fails: saveability score and verdict."""
    spanish = viewer is not None and viewer["language"] == "es"
    event, insight = live.event, live.insight
    if insight.get("type") == "distribution":
        if spanish:
            return f"{event['player']} a {event['target_player']}: calidad {insight['quality']}/100."
        return (f"{event['player']} to {event['target_role']} {event['target_player']}: quality "
                f"{insight['quality']}/100, {insight['verdict']} ({insight['key_factor']}).")
    if insight:
        verdict = insight["verdict"]
        if spanish:
            return f"Salvabilidad {insight['saveability']}/100: {VERDICT_ES[verdict]}."
        return f"Saveability {insight['saveability']}/100: {verdict} ({insight['key_factor']})."
    # Claims and sweeps have no saveability score
    action = {"keeper_claim": ("claims the cross", "atrapa el centro"),
              "keeper_sweep": ("sweeps off the line", "sale a despejar")}[event["type"]]
    return f"{event['player']} {action[1] if spanish else action[0]}."


async def ask(agent, prompt, errors):
    """Run one agent. On any failure, record the error and return None."""
    try:
        response = await asyncio.wait_for(agent.run(prompt), AGENT_TIMEOUT_SEC)
        return response.text.strip() or None
    except Exception as e:  # network, auth, timeout, content filter...
        errors.append(f"{agent.name}: {type(e).__name__}: {e}"[:300])
        return None


async def personalize(personalizer, text, viewer, errors, context=""):
    """Hand the narration to the Personalizer for one viewer. `context` says
    which club the keeper plays for, so it knows whose side to take."""
    prompt = (f"Viewer: mode={viewer['mode']}, favorite club={viewer['club']}, "
              f"language={viewer['language']}.\n{context}\n\nNarration:\n{text}")
    return await ask(personalizer, prompt, errors)


async def process_moment(live, agents, viewers):
    """Run the Analyst -> Narrator -> Personalizer handoffs for one moment
    and return a JSON-ready dict."""
    analyst, narrator, personalizer = agents
    event, insight = live.event, live.insight
    errors = []

    # 1. Shot Analyst reads the shared state through its tools
    analysis = await ask(analyst, "Analyse the current moment.", errors)

    # Whose point of view: claims, sweeps and distributions are done by the
    # keeper's own team; shots and goals come from the other team.
    if event["type"] in ("keeper_claim", "keeper_sweep", "keeper_distribution"):
        keeper_club = event["team"]
    else:
        keeper_club = live.state.other(event["team"])
    keeper_name = insight.get("keeper", event["player"])

    # 2. Handoff to the Narrator, telling it who it is. If the Analyst failed,
    # pass the raw insight instead.
    facts = analysis or json.dumps({"event": event, "insight": insight})
    narration = await ask(narrator, f"You are {keeper_name}, the {keeper_club} goalkeeper. "
                          f"Moment at {clock(event)}. Analysis:\n{facts}", errors)

    # 3. Handoff to the Personalizer, once per viewer
    turnover = event["type"] == "keeper_distribution" and insight.get("verdict") == "turnover"
    if event["type"] == "goal":
        news = f"good news for {event['team']}, bad news for {keeper_club}"
    elif turnover:
        news = f"bad news for {keeper_club}: they lost the ball"
    else:
        news = f"good news for {keeper_club}"
    context = f"The narrator is the {keeper_club} goalkeeper. This moment was {news}."
    # asyncio.gather runs the Personalizer for every viewer at the same time
    texts = [None] * len(viewers)
    if narration:
        texts = await asyncio.gather(*[personalize(personalizer, narration, viewer, errors, context)
                                       for viewer in viewers])
    versions = [{"viewer": viewer, "text": text or fallback_text(live, viewer),
                 "fallback": text is None}
                for viewer, text in zip(viewers, texts)]

    return {
        "kind": "moment",
        "event_id": event["id"],
        "clock": clock(event),
        "match_second": live.now(),
        "type": event["type"],
        "team": event["team"],
        "player": event["player"],
        "keeper": insight.get("keeper", event["player"]),
        "score": live.score,
        "saveability": insight.get("saveability"),
        "verdict": insight.get("verdict"),
        "key_factor": insight.get("key_factor"),
        # distribution moments only (None otherwise)
        "quality": insight.get("quality"),
        "decision_score": insight.get("decision_score"),
        "difficulty": insight.get("difficulty"),
        "analysis": analysis,
        "narration": narration,
        "versions": versions,
        "errors": errors,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def stats_in_words(s):
    """Keeper numbers as plain words, so the agents don't copy field names."""
    return (f"{s['shots_faced']} shots faced ({s['on_target']} on target), {s['saves']} saves, "
            f"{s['goals_conceded']} goals conceded, {s['claims']} crosses claimed, "
            f"{s['sweeps']} sweeps. An average keeper would have made {s['expected_saves']} "
            f"saves from these shots, so goals prevented is {s['goals_prevented']:+} "
            "(more than 0 means better than an average keeper).")


async def keeper_report(live, agents, viewers, kind):
    """Halftime or full-time report. kind is "half_time" or "full_time".
    Each viewer hears from the keeper of their favorite club (the home keeper
    if their club is not playing). The Narrator writes it; the Personalizer adapts it."""
    _, narrator, personalizer = agents
    report = live.state.keeper_report()
    home, away = live.state.teams
    home_goals, away_goals = live.score.split("-")  # score is "home-away"
    score = f"{home} {home_goals}-{away_goals} {away}"
    label = "Halftime" if kind == "half_time" else "Full-time"
    errors = []
    # Which keeper each viewer hears from
    teams = [viewer["club"] if viewer["club"] in report else home for viewer in viewers]

    # 1. The Narrator writes one report per keeper (each team only once)
    narrations = {}
    for team in dict.fromkeys(teams):  # unique teams, in order
        opponent = live.state.other(team)
        prompt = (f"{label} keeper report. You are the {team} goalkeeper. Score: {score}.\n"
                  f"Your numbers: {stats_in_words(report[team])}\n"
                  f"The {opponent} keeper's numbers: {stats_in_words(report[opponent])}")
        narrations[team] = await ask(narrator, prompt, errors)

    # 2. The Personalizer adapts it for every viewer at the same time
    async def adapt(viewer, team):
        if not narrations[team]:
            return None
        context = f"The narrator is the {team} goalkeeper. Score: {score}."
        return await personalize(personalizer, narrations[team], viewer, errors, context)

    texts = await asyncio.gather(*[adapt(viewer, team) for viewer, team in zip(viewers, teams)])
    versions = [{"viewer": viewer, "keeper_team": team,
                 "text": text or json.dumps(report[team]), "fallback": text is None}
                for viewer, team, text in zip(viewers, teams, texts)]

    return {"kind": kind, "score": live.score, "keeper_report": report,
            "narrations": narrations, "versions": versions, "errors": errors,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


async def run(only=None, viewers=VIEWERS, path="match_events.json"):
    """Replay the match. Yield one JSON-ready dict per key moment, then the
    full-time report. With `only="67:03"`, send just that moment to the agents
    (the state is still built from every event before it)."""
    match, events = load_match(path)
    live = LiveMatch(match)
    client = make_client()
    agents = (make_analyst(client, live), make_narrator(client), make_personalizer(client))

    halftime_done = False
    for event, insight, _ in stream(events, live.state, speed=0):
        # First event of the second half: the halftime report comes first.
        # (The state already includes this event, but it is never a shot on
        # target, so the keeper numbers are still the first-half numbers.)
        if event["half"] == 2 and not halftime_done:
            halftime_done = True
            if not only:
                yield await keeper_report(live, agents, viewers, "half_time")

        live.event, live.insight = event, insight
        if insight:
            live.shot_insights[event["id"]] = insight
        if event["type"] == "goal":
            live.score = event["score"]
            live.insight = live.shot_insights.get(event["related_to"], {})
            # The moment is timed at the shot (e.g. 67:03), not the celebration
            shot = next(e for e in events if e["id"] == event["related_to"])
            live.event = dict(event, minute=shot["minute"], second=shot["second"])

        if not is_key_moment(event):
            continue
        if only and clock(live.event) != only:
            continue
        yield await process_moment(live, agents, viewers)

    if not only:
        yield await keeper_report(live, agents, viewers, "full_time")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="process just the moment at this clock, e.g. 67:03")
    args = parser.parse_args()
    async for item in run(args.only):
        # flush=True writes each line right away, even into a file
        print(json.dumps(item, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
