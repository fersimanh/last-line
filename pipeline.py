"""Agent pipeline for Last Line.

Replays the match through each keeper's eyes: the pipeline reads ONLY
perceived events from perception.PerceptionFilter, never the raw match. What
a keeper did not see never reaches the agents. Only key moments go through
the agents:

    Shot Analyst  ->  Narrator  ->  Personalizer (once per viewer)

If an agent fails, the moment still gets a fallback line built from the
saveability score and verdict, so the feed never goes silent.

Each moment is printed as one line of JSON (JSON Lines), ready for an app.

Run it (sign in first with `az login`):
    python3 pipeline.py                 # whole match
    python3 pipeline.py --only 30:05    # just the moment(s) at 30:05
    python3 pipeline.py --style second_person   # "You're 4 m off your line..." (the Keeper's eyes view)
"""
import argparse
import asyncio
import heapq
import json
from datetime import datetime, timezone

from agents import make_analyst, make_client, make_narrator, make_personalizer
import inspector
from perception import MATCH_PATH, PerceptionFilter, match_info
from replay import clock

AGENT_TIMEOUT_SEC = 90  # give up on a slow agent and use the fallback

# Two example viewers. Each key moment gets one version per viewer.
VIEWERS = [
    {"name": "casual_en", "mode": "casual", "club": "Harbor United", "language": "en"},
    {"name": "analyst_es", "mode": "analyst", "club": "Northgate FC", "language": "es"},
]

# Translations for the fallback line, so Spanish viewers get Spanish
VERDICT_ES = {"should save": "debió pararlo", "tough save": "parada difícil",
              "near-unstoppable": "casi imparable"}


UNSEEN_WINDOW_SEC = 30  # "what did I miss just before this?" window for the agents

# How each kind of sight is put to the Narrator
SIGHT_WORDS = {
    "own": "it was your own action",
    "seen": "you saw it happen",
    "felt": "you did not see it develop; you only knew when the ball reached your goal "
            "or the crowd reacted",
}


class LiveMatch:
    """The shared match-state object, built ONLY from perceived events: one
    PerceptionFilter per keeper, and `team` says whose eyes we are looking
    through right now. The pipeline writes to it; the Shot Analyst's tools
    read from it (see agents.py). It never exposes the missed log."""

    def __init__(self, match, path=MATCH_PATH):
        self.match = match
        self.filters = {team: PerceptionFilter(team, path) for team in (match["home"], match["away"])}
        # A second, fully replayed copy used ONLY to read an event's facts (a pass is
        # described by where the ball went next). The live filters above stay
        # as-of-now, because the Analyst's tools read their numbers.
        self.lookahead = {team: PerceptionFilter(team, path) for team in (match["home"], match["away"])}
        for f in self.lookahead.values():
            f.advance_all()
        self.team = match["home"]  # whose eyes
        self.perceived = None      # the PerceivedEvent being processed now
        self.event = None          # its event (as perceived)
        self.insight = {}          # its scoring insight (empty if none)
        self.facts = None          # PerceptionFilter.facts() for it (perceived-only)
        self.agent_facts = {}      # the compact version the agents see

    @property
    def state(self):
        """The current keeper's own picture of the match (perceived events only)."""
        return self.filters[self.team].state

    @property
    def score(self):
        return self.filters[self.team].score  # goals are always felt, so this is the real score

    @property
    def sight(self):
        return self.perceived.sight if self.perceived else None

    def unseen_count(self, window_sec=UNSEEN_WINDOW_SEC):
        """How many events the current keeper missed in the last `window_sec` seconds."""
        now = self.now()
        return self.filters[self.team].unseen_count(since_sec=now - window_sec, until_sec=now)

    def now(self):
        return self.event["minute"] * 60 + self.event["second"]

    def replay_to_end(self):
        """Replay every keeper's eyes to full time (used for full-time reports)."""
        for f in self.filters.values():
            f.advance_all()


def fallback_text(live, viewer=None):
    """Plain line used when an agent fails: saveability score and verdict."""
    spanish = viewer is not None and viewer["language"] == "es"
    event, insight = live.event, live.insight
    if live.facts and event["type"] not in ("shot", "goal", "keeper_claim", "keeper_sweep",
                                            "keeper_distribution"):
        return inspector.template_text(live.facts, "es" if spanish else "en")  # passes and the rest
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


VOICE_HINT = {
    "first_person": "",
    "second_person": "The narration is in the second person (you). Keep it that way: never switch to 'I'. ",
}


async def personalize(personalizer, text, viewer, errors, context="", style="first_person"):
    """Hand the narration to the Personalizer for one viewer. `context` says
    which club the keeper plays for, so it knows whose side to take."""
    prompt = (f"Viewer: mode={viewer['mode']}, favorite club={viewer['club']}, "
              f"language={viewer['language']}.\n{VOICE_HINT[style]}{context}\n\nNarration:\n{text}")
    return await ask(personalizer, prompt, errors)


async def process_moment(live, agents, viewers, style="first_person"):
    """Run the Analyst -> Narrator -> Personalizer handoffs for one moment
    and return a JSON-ready dict. style "second_person" addresses the keeper
    as "you" (the Keeper's eyes view)."""
    analyst, narrator, personalizer = agents
    event, insight = live.event, live.insight
    errors = []

    # 1. Shot Analyst reads the shared state through its tools
    analysis = await ask(analyst, "Analyse the current moment.", errors)

    # Whose eyes: the keeper this moment belongs to
    keeper_club = live.team
    keeper_name = live.filters[live.team].keeper_name()
    unseen = live.unseen_count()

    # 2. Handoff to the Narrator, telling it who it is and what it could see.
    # It gets the sight and the unseen count, never the missed log itself.
    # If the Analyst failed, pass the perceived insight instead.
    facts = analysis or json.dumps({"event": event, "insight": insight, "facts": live.agent_facts})
    where = (f"The keeper stood {live.perceived.keeper_pos[0]:.0f} m off the goal line; "
             f"this was {live.perceived.distance_m:.0f} m from the keeper. ")
    if style == "second_person":
        who = (f"The goalkeeper is {keeper_name} of {keeper_club}. Write in the SECOND person: "
               "address the keeper as 'you' (for example \"You're 4 m off your line...\") "
               "and never say 'I'. ")
    else:
        who = f"You are {keeper_name}, the {keeper_club} goalkeeper. "
    narration = await ask(narrator, f"{who}Moment at {clock(event)}. {where}"
                          f"Sight: {SIGHT_WORDS[live.sight]}. "
                          f"Events you could not see in the last {UNSEEN_WINDOW_SEC} seconds: "
                          f"{unseen}.\nAnalysis:\n{facts}", errors)

    # 3. Handoff to the Personalizer, once per viewer
    turnover = event["type"] == "keeper_distribution" and insight.get("verdict") == "turnover"
    if event["type"] == "goal":
        news = f"good news for {event['team']}, bad news for {keeper_club}"
    elif turnover:
        news = f"bad news for {keeper_club}: they lost the ball"
    elif event["type"] in ("pass", "through_ball", "cross", "box_entry", "tackle", "possession_change"):
        news = "not decisive for either side"
    else:
        news = f"good news for {keeper_club}"
    context = f"The narrator is the {keeper_club} goalkeeper. This moment was {news}."
    # asyncio.gather runs the Personalizer for every viewer at the same time
    texts = [None] * len(viewers)
    if narration:
        texts = await asyncio.gather(*[personalize(personalizer, narration, viewer, errors,
                                                   context, style)
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
        "sight": live.sight,               # own, seen or felt
        "style": style,                    # first_person or second_person
        "unseen_count": unseen,            # events missed in the last 30 seconds
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
            f"{s['sweeps']} sweeps, {s['close_downs']} times off the line to close down an "
            f"attacker. An average keeper would have made {s['expected_saves']} "
            f"saves from these shots, so goals prevented is {s['goals_prevented']:+} "
            "(more than 0 means better than an average keeper).")


async def keeper_report(live, agents, viewers, kind):
    """Halftime or full-time report. kind is "half_time" or "full_time".
    Each viewer hears from the keeper of their favorite club (the home keeper
    if their club is not playing). Each keeper reports only their OWN perceived
    numbers, the score and how much they could not see: the other keeper is
    100 m away. The Narrator writes it; the Personalizer adapts it."""
    _, narrator, personalizer = agents
    home, away = live.match["home"], live.match["away"]
    # Each keeper's numbers from their own perceived picture
    report = {team: f.state.keeper_report()[team] for team, f in live.filters.items()}
    home_goals, away_goals = live.filters[home].score.split("-")  # score is "home-away"
    score = f"{home} {home_goals}-{away_goals} {away}"
    label = "Halftime" if kind == "half_time" else "Full-time"
    errors = []
    # Which keeper each viewer hears from
    teams = [viewer["club"] if viewer["club"] in report else home for viewer in viewers]

    # 1. The Narrator writes one report per keeper (each team only once)
    narrations = {}
    for team in dict.fromkeys(teams):  # unique teams, in order
        prompt = (f"{label} keeper report. You are the {team} goalkeeper. Score: {score}.\n"
                  f"Your numbers: {stats_in_words(report[team])}\n"
                  f"Events you could not see so far: {live.filters[team].unseen_count()}.")
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

    return {"kind": kind, "score": live.filters[home].score, "keeper_report": report,
            "narrations": narrations, "versions": versions, "errors": errors,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def goal_timed_like_its_shot(goal, shot):
    """A goal is explained together with the shot that caused it, so it takes that shot's time
    (a goal at 52:47 is the 52:46 moment). The fan clock text must follow, or the moment's clock
    and the goal's own clock would disagree and the explanation would never be matched to it."""
    timed = dict(goal, minute=shot["minute"], second=shot["second"])
    if "clock" in shot:
        timed["clock"] = shot["clock"]
    return timed


async def run(only=None, viewers=VIEWERS, path=MATCH_PATH, style="first_person", event_ids=None):
    """Replay the match through both keepers' eyes, in time order. Yield one
    JSON-ready dict per key moment, then the full-time report. With
    `only="30:05"`, send just the moment(s) at that clock to the agents
    (each keeper's perceived picture is still built from everything before it).
    With `event_ids={event_id: keeper_team}`, send exactly those events (any
    type, such as a notable pass) as seen through that keeper's eyes, and no
    reports."""
    live = LiveMatch(match_info(path), path)
    client = make_client()
    agents = (make_analyst(client, live), make_narrator(client), make_personalizer(client))

    # Both keepers' perceived events, merged in time order
    both = heapq.merge(*[f.advance() for f in live.filters.values()],
                       key=lambda pe: (pe.second, pe.event["id"]))
    halftime_done = False
    for pe in both:
        # First event of the second half: the halftime report comes first
        if pe.event["half"] == 2 and not halftime_done:
            halftime_done = True
            if not only and event_ids is None:
                yield await keeper_report(live, agents, viewers, "half_time")
        if event_ids is not None:
            if event_ids.get(pe.event["id"]) != pe.followed_team:
                continue
        elif not pe.key_moment:
            continue

        live.team, live.perceived = pe.followed_team, pe
        live.event, live.insight = pe.event, pe.insight
        live.facts = live.lookahead[live.team].facts(pe.event["id"], reveal=False)
        live.agent_facts = inspector.agent_facts(live.facts)
        if pe.event["type"] == "goal":
            # A goal takes its numbers and its clock from the shot that caused
            # it (shots on target at your goal are always felt, so it is there)
            shot = live.filters[live.team].find_perceived(pe.event["related_to"])
            live.insight = shot.insight
            live.event = goal_timed_like_its_shot(pe.event, shot.event)
        if only and clock(live.event) != only:
            continue
        yield await process_moment(live, agents, viewers, style)

    if not only and event_ids is None:
        live.replay_to_end()
        yield await keeper_report(live, agents, viewers, "full_time")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="process just the moment(s) at this clock, e.g. 30:05")
    parser.add_argument("--style", choices=["first_person", "second_person"], default="first_person")
    args = parser.parse_args()
    async for item in run(args.only, style=args.style):
        # flush=True writes each line right away, even into a file
        print(json.dumps(item, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
