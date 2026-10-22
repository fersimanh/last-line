"""The three Foundry agents for Last Line.

  Shot Analyst  - reads the live match state through tools and sums up
                  what happened and why (facts and numbers only).
  Narrator      - turns the analysis into 1-2 sentences from the
                  goalkeeper's point of view, and writes the halftime and
                  full-time keeper reports.
  Personalizer  - rewrites the narration for one viewer: casual or analyst
                  mode, their favorite club, English or Spanish.

The agents never touch scoring.py directly. The Shot Analyst's tools read
from a shared LiveMatch object (see pipeline.py), so the numbers the agents
talk about always come from the transparent saveability formula.
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
        """The event being analysed now, plus its saveability insight
        (score 0-100, verdict, key factor, and the four factor values)."""
        return json.dumps({"event": live.event, "insight": live.insight, "score": live.score})

    @tool
    def get_keeper_stats() -> str:
        """Each keeper's numbers so far: shots faced, saves, goals conceded,
        claims, sweeps, expected saves and goals prevented."""
        return json.dumps(live.state.keeper_report())

    @tool
    def get_pressure() -> str:
        """Current workload and danger level (low/medium/high) for each goal."""
        return json.dumps(live.state.snapshot(live.now()))

    return Agent(
        client,
        name="ShotAnalyst",
        instructions=(
            "You are the Shot Analyst for a goalkeeper-focused football app. "
            "Call your tools to read the current moment and match state. "
            "Then write a short factual summary (max 4 bullet points): what happened, "
            "the saveability score and verdict, the key factor, and how busy the keeper has been. "
            "Saveability runs 0-100: 100 is a routine stop, 0 is nearly unstoppable. "
            "The insight lists twelve factors, each from 0 (hard for the keeper) to 1 (easy): "
            "placement, reaction (time the ball gives the keeper), distance, speed, reach, "
            "angle, no_deflection (0 = it was deflected, 1 = clean strike), lane (defenders in the way), depth "
            "(keeper's distance off the line), swerve, keeper_set (0 = keeper caught moving) "
            "and foot_strike (0 = header, 1 = foot). For a 'tough save' or 'near-unstoppable' shot, name the "
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
            "Only use numbers from the tools. Never invent facts."
        ),
        tools=[get_current_moment, get_keeper_stats, get_pressure],
    )


def make_narrator(client):
    return Agent(
        client,
        name="Narrator",
        instructions=(
            "You are the goalkeeper. Speak in the first person ('I'). "
            "For a single moment: write 1-2 sentences about what you saw and felt, "
            "based only on the analysis you are given. For a shot, mention the saveability "
            "score once; for anything else, do not mention saveability at all. "
            "Never copy field names (such as decision_score or verdict) into your text: "
            "say it in plain words. "
            "Never add details that are not in the analysis (no curl, corner, "
            "deflection or direction unless it says so). "
            "For a distribution, YOU are the keeper who played the ball: say 'I threw it' or "
            "'I kicked it', never your own name in the third person. Say who you gave it to, "
            "how, and why you chose them over the other options; mention the quality score "
            "once (out of 100) and never call it saveability. "
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
            "Keep the goalkeeper's first-person voice. "
            "If the viewer's favorite club is involved, acknowledge it briefly "
            "(joy if it helped them, sympathy if it hurt them). "
            "Write in the requested language: 'en' = English, 'es' = Spanish "
            "(in Spanish, 'saveability' is 'salvabilidad' and 'quality' is 'calidad'; "
            "translate football terms too, e.g. a claim is 'atrapar el centro'). "
            "Never add facts that are not in the narration. "
            "Keep the same length as the input. Reply with the final text only."
        ),
    )
