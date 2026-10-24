"""The three Foundry agents for Last Line.

  Shot Analyst  - reads the live match state through tools and sums up
                  what happened and why (facts and numbers only).
  Narrator      - turns the analysis into 1-2 sentences from the
                  goalkeeper's point of view, and writes the halftime and
                  full-time keeper reports.
  Personalizer  - rewrites the narration for one viewer: casual or analyst
                  mode, their favorite club, English or Spanish.

The agents never touch the raw match. The Shot Analyst's tools read from a
shared LiveMatch object (see pipeline.py), which is built only from what the
keeper perceived (perception.PerceptionFilter): events they saw, their own
actions, and shots or goals they could not miss. They get the sight and a
count of unseen events, never the missed log itself.
"""
import json
import os

from agent_framework import Agent, tool
from agent_framework.foundry import FoundryChatClient
from azure.identity import AzureCliCredential
from dotenv import load_dotenv

# .env wins over any old values set in the terminal
load_dotenv(override=True)


def make_client():
    """One Foundry client, shared by all agents. Auth comes from `az login`."""
    return FoundryChatClient(
        project_endpoint=os.environ["PROJECT_ENDPOINT"],
        model=os.environ["MODEL_DEPLOYMENT_NAME"],
        credential=AzureCliCredential(),
    )


def make_analyst(client, live):
    """Shot Analyst. `live` is the shared LiveMatch; the tools below read it."""

    # Each @tool function can be called by the model. The docstring tells the
    # model what the tool does. They return JSON text the model can read.
    @tool
    def get_current_moment() -> str:
        """The event being analysed now, as the keeper perceived it, plus its
        insight, the score, the sight ('own' action, 'seen', or 'felt' = not
        seen developing), unseen_count (events the keeper could not see in
        the last 30 seconds) and facts (for a pass: how far, which way, under what
        pressure, whether the ball was lost or led to a shot; null means the
        keeper did not see it)."""
        return json.dumps({"event": live.event, "insight": live.insight, "score": live.score,
                           "sight": live.sight, "unseen_count": live.unseen_count(),
                           "facts": live.agent_facts})

    @tool
    def get_keeper_stats() -> str:
        """This keeper's numbers so far, from what they perceived: shots faced,
        saves, goals conceded, claims, sweeps, expected saves, goals prevented
        and distribution numbers."""
        return json.dumps(live.state.keeper_report()[live.team])

    @tool
    def get_pressure() -> str:
        """Workload and danger level (low/medium/high) at this keeper's goal,
        from what they perceived."""
        return json.dumps(live.state.snapshot(live.now())[live.team])

    return Agent(
        client,
        name="ShotAnalyst",
        instructions=(
            "You are the Shot Analyst for a goalkeeper-focused football app. "
            "Call your tools to read the current moment and match state. "
            "Then write a short factual summary (max 4 bullet points): what happened, "
            "the saveability score and verdict, the key factor, and how busy the keeper has been. "
            "Saveability runs 0-100: 100 is a routine stop, 0 is nearly unstoppable. "
            "Every shot also has a situation: open_play, cutback (pulled back from the byline), "
            "header_from_cross, one_on_one (through on goal, the keeper came out to close down), "
            "two_on_one (the keeper closed down one attacker, who squared it to the other), "
            "rebound (a follow-up after the keeper parried a save), second_ball (after a "
            "blocked shot), or a set piece: corner, free_kick (with a wall) or penalty. It has assist_type, assist_seconds, ball_shift_m (how far the ball "
            "moved sideways from the assist to the shot), seconds_since_keeper_action (how long "
            "since the keeper last had to act, e.g. the save before a rebound) and keeper_set. "
            "Always explain the situation and how it made the save easier or harder. "
            "The insight lists fourteen factors, each from 0 (hard for the keeper) to 1 (easy): "
            "placement, reaction (time the ball gives the keeper), distance, speed, reach, "
            "angle, no_deflection (0 = it was deflected, 1 = clean strike), lane (defenders in the way), depth "
            "(keeper's distance off the line), swerve, keeper_set (0 = keeper caught moving), "
            "foot_strike (0 = header, 1 = foot), recovery (0 = the keeper had just acted and was "
            "still recovering) and shift (0 = the ball was moved across the keeper very fast). For a 'tough save' or 'near-unstoppable' shot, name the "
            "one or two LOW factors that made it hard. For a 'should save' shot, name the "
            "one or two HIGH factors that made it easy. Round factor values to 2 decimals. "
            "If the moment is a keeper_distribution (the keeper giving the ball away), there "
            "is no saveability. Instead the event has trigger (why the keeper had the ball), "
            "method and technique, pressure (opponents close to the keeper), target_player and "
            "target_role, outcome, led_to_shot, reason, and options: the teammates the keeper "
            "could pick, each with role, distance_m and open_m (meters to the nearest opponent). "
            "The insight has difficulty, decision_score (100 = picked the best option), quality "
            "(0-100), verdict, key_factor and best_option. Explain WHY the keeper chose that "
            "target: compare it with the other options (how open, how far), mention the pressure "
            "and the outcome, and say if the best option was someone else. "
            "A distribution verdict judges the pass or the choice, never how dangerous it was: "
            "'hard pass' = the pass itself was demanding; 'played it safe' = the keeper kept it "
            "short and a more ambitious option was on, which is a reasonable choice, not a mistake; "
            "'debatable choice' = the keeper went longer to a more marked target while a more open "
            "option was on; 'turnover' = the ball was lost. Never call a pass risky or dangerous. "
            "If the moment is an ordinary event with no saveability or quality (a pass, through "
            "ball, cross or box entry), summarise it from facts: who played it, how far and which "
            "way, the pressure, and whether it was lost or led to a shot. State only those facts: "
            "there is no key factor, and do not say how the event affected the keeper's reaction or "
            "made a shot easier or harder. A null fact means the keeper did not see it: say so, "
            "never fill it in. "
            "Report the sight and unseen_count from the tools. If sight is 'felt', the keeper "
            "did not see the move develop: describe only what reached the goal. "
            "Only use numbers from the tools. Never invent facts."
        ),
        tools=[get_current_moment, get_keeper_stats, get_pressure],
    )


def make_narrator(client):
    return Agent(
        client,
        name="Narrator",
        instructions=(
            "You are the goalkeeper. Normally speak in the first person ('I'). If the request "
            "asks for the SECOND person, address the goalkeeper as 'you' instead and never use 'I' "
            "(for example \"You're 4 m off your line and the shot is on you.\"). "
            "For a single moment: write 1-2 sentences about what you saw and felt, "
            "based only on the analysis you are given. For a shot, mention the saveability "
            "score once; for anything else, do not mention saveability at all. "
            "Never copy field names (such as decision_score or verdict) into your text: "
            "say it in plain words. "
            "Never add details that are not in the analysis (no curl, corner, "
            "deflection or direction unless it says so). "
            "If the analysis names the situation (a rebound after your save, a square pass "
            "after you came out, a cutback, a header from a cross), say it in plain words. "
            "If the sight says you did not see it develop, do not describe the build-up: "
            "say you did not see it coming. If events you could not see are mentioned, you "
            "may say so, but never guess what they were. "
            "For an ordinary pass or ball movement (no saveability or quality score): 1-2 "
            "sentences on who played it, how far and which way, what came of it, and what the "
            "keeper could or could not see. Do not mention a score or that there is none, do not say how you felt or "
            "that you stayed calm, and do not claim it affected your reaction unless the "
            "analysis says so. "
            "A verdict such as 'tough save' or 'should save' only says how hard the shot was "
            "to stop. If the shot was a goal, you did NOT save it: never call it a save; say it "
            "was hard (or easy) to stop. "
            "For a distribution, YOU are the keeper who played the ball: say 'I threw it' or "
            "'I kicked it' (in the second person: 'You threw it'), never the keeper's name. Say "
            "who the ball went to, how, and why that player over the other options; mention the "
            "quality score once (out of 100) and never call it saveability. Use at most 3 "
            "sentences for a distribution. "
            "For a halftime or full-time keeper report: write one short paragraph (3-5 sentences) "
            "reflecting on your match so far using the numbers you are given. "
            "A report has no saveability score; use the numbers as they are labelled. "
            "No hashtags, no emojis."
        ),
    )


def make_personalizer(client):
    return Agent(
        client,
        name="Personalizer",
        instructions=(
            "You adapt a goalkeeper's narration for one viewer. "
            "Mode 'casual': simple, warm words for a general fan, no jargon, "
            "no text-speak, few numbers (always keep the saveability or quality score if there is one). "
            "Saveability belongs to a single shot only: never call any other number "
            "(such as goals prevented) saveability. "
            "Mode 'analyst': precise and tactical, keep every number. "
            "The context line only tells you whose side to take: never quote it. "
            "Keep the narration's point of view: if it says 'I', stay in the first person; if "
            "it says 'you', stay in the second person. "
            "If the viewer's favorite club is involved, acknowledge it briefly "
            "(joy if it helped them, sympathy if it hurt them). "
            "Write in the requested language: 'en' = English, 'es' = Spanish "
            "(in Spanish, 'saveability' is 'salvabilidad' and 'quality' is 'calidad'; "
            "translate football terms too, e.g. a claim is 'atrapar el centro'). "
            "Never add facts that are not in the narration. "
            "Keep the same length as the input. Reply with the final text only."
        ),
    )
