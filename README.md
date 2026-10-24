# Last Line

**Every shot, explained from the goalkeeper's eyes.**

Live app: https://last-line-cxpf4zgh8noyfeemstwdhl.streamlit.app/

Last Line replays a synthetic football match and explains every shot, save and goalkeeper pass from the keeper's point of view, in plain words, in English or Spanish, for a casual fan or an analyst. The key idea is that the AI only learns what the keeper could perceive: the match is filtered through the keeper's field of view and line of sight before any agent reads it, and a test enforces that rule.

Built for the Microsoft x Premier League "Inside the Game" hackathon.

## Try it in 60 seconds

1. Open the live app and press **Play** in the sidebar. The match replays at 120x (a full match in about 45 seconds). The pitch shows the keeper's sightline as a cone; everything outside it is dimmed.
2. When a key moment card appears (a save, a goal, a keeper pass), press **Show on pitch** on it. The match pauses on that moment and an explanation opens, written to the keeper in the second person. Open **Show the numbers** to see the factors behind it.
3. Switch the **View** control between **Keeper's eyes** and **Reveal**. Reveal draws the events the keeper did not perceive, hollow, with the reason (too far, outside the cone, blocked by a player). Then try **Mode** (Casual fan or Analyst), **Language** (English or Español) and the favorite club selector, which decides which keeper you follow. The **Full-time report** tab has the keeper's own summary.

## Architecture

```
ingest        generate_match.py + sim_engine.py     synthetic match: events + 22-player tracking (deterministic, seeded)
                     |
perceive      perception.py + vision.py             one PerceptionFilter per keeper: what they saw, felt or did (deterministic)
                     |                              the missed log stays here, for the Reveal view only
interpret     scoring.py                            saveability (shots) and decision quality (keeper passes) (deterministic)
                     |
explain       pipeline.py + agents.py               Shot Analyst -> Narrator          (AI)
                     |
personalize   agents.py                             Personalizer, per viewer: mode, club, language   (AI)
                     |
render        app.py + insights.py + inspector.py   Streamlit; text from insight_cache.json, then live agents, then a template
```

Deterministic code (no AI): the match engine, perception, scoring, the cache lookup and the fallback templates. AI: three agents, and only on key moments.

| Agent | What it does |
| --- | --- |
| Shot Analyst | Calls three tools (`get_current_moment`, `get_keeper_stats`, `get_pressure`) that read the keeper's perceived match state, then writes a short factual summary. It is told to use only numbers the tools return. |
| Narrator | Speaks as the goalkeeper (first or second person): 1 to 2 sentences per moment, saying so when the keeper did not see a move develop. Also writes the halftime and full-time reports. |
| Personalizer | Rewrites the narration for one viewer: casual or analyst, favorite club, English or Spanish. |

The agents run one after another and each one's output is the next one's input. If an agent fails or times out (90 s), the moment still gets a fallback line built from the saveability score and verdict, so the feed never goes silent.

## Microsoft technology used

- **Microsoft Foundry**: the agents run on a Foundry project. The model is a `gpt-5-mini` deployment, named in `MODEL_DEPLOYMENT_NAME`.
- **Microsoft Agent Framework** (`agent-framework`, version pinned in `requirements.txt`): `agents.py` uses `Agent`, the `@tool` decorator for the Shot Analyst's tools, and `FoundryChatClient`. That is all it uses: the three agents are plain sequential calls in `pipeline.py`, with no workflow or orchestration feature.
- **Microsoft Entra ID**: the agents sign in with `AzureCliCredential` (`az login`). There is no API key in the code.
- **Hosting**: the live app runs on Streamlit Community Cloud. A `Dockerfile` for the same cache-only app also builds and runs (checked locally).

**The live deployment serves pre-generated texts.** The Foundry agents wrote every AI text in `insight_cache.json` ahead of time (`build_cache.py`), for each moment, mode, club and language. The deployed app has no Azure credentials and runs with `LAST_LINE_LIVE_AGENTS=0`, so it never calls the agents: a text that is in the cache shows as "AI insight", and anything not cached shows a template line marked "Quick insight". The code does call the agents live when `LAST_LINE_LIVE_AGENTS=1` and `PROJECT_ENDPOINT` is set with Azure credentials. The cache stores a hash of `match_events.json` and a text version, and is ignored if either differs, so it never shows text for the wrong match.

## The perception filter

The keeper's field of view is the input, not an overlay.

- **Vision cone**: 120 degrees wide and 85 m long, from the keeper's goal line up to the opponents' box. It points at where the ball was half a second before the event. It is a model, because the tracking data has positions but not eye direction. The keeper looks up the pitch when the ball is at his feet and never turns more than 80 degrees from straight up the pitch.
- **Line of sight and bodies in the way**: the tracking holds all 22 players every 0.5 s. A player 0.6 m wide hides a point when he is nearer the keeper than the point and the sightline passes through him. A player 2 m in front of the keeper hides a wide angle; one 25 m away hides only a sliver. This works anywhere on the pitch.
- **What the keeper knows**: `PerceptionFilter` sorts every event as `own` (the keeper's own save, claim, sweep or pass), `seen` (inside the sightline), `felt` (not seen but impossible to miss: a shot on target at his goal, or any goal) or missed, with a reason: `beyond_radius`, `outside_fov` or `blocked`. For keeper passes, options he could not see are removed and only counted.
- **Architecture test**: `test_architecture.py` reads the source of every module and fails if anything outside the data layer (`generate_match.py`, `legacy_generator.py`, `replay.py`, `scoring.py`, `vision.py`, `perception.py`) reads the raw match, or if `agents.py` or `pipeline.py` touches the missed log. It does not need Azure access.
- **Reveal view**: the display-only counterpart. It shows what the keeper missed and why, next to the official numbers (shot map colored by saveability, goal mouth, workload). The missed log never reaches the agents.

In the demo match (seed 15) the keepers perceive 1,301 (Harbor United) and 1,185 (Northgate FC) of 1,771 events.

## Synthetic data

**Football-realistic, calibrated to published league averages where available; not real match data.** All clubs and players are fictional (Harbor United and Northgate FC).

The match engine (`sim_engine.py`, with `sim_stops.py`, `sim_shots.py`, `sim_keeper.py`; design in `SIM_DESIGN.md`) plays football on a 105 x 68 m pitch rather than generating events at random:

- Formations (4-4-2, 4-3-3, 4-2-3-1) with tactics per team: line height, width, press, directness, crossing. Players have attributes (pace, passing, tackling, shooting, control) and a bench of seven each.
- 22 players and the ball are tracked every 0.5 s (2 Hz) and saved to `tracking.npz`. The events are read off what happens.
- Set pieces: throw-ins, goal kicks, corners, direct free kicks with a wall, penalties. Also fouls, cards, offsides, substitutions, injury stoppages, half time and added time. Every dead ball is a `stoppage` event.
- Shots come with a build-up (open play, cutback, header from a cross, one on one, two on one, rebound, second ball) and 14 saveability factors.
- The demo match is seed 15, chosen from seeds 1 to 60: 2 goals (Northgate FC 2-0), one busy keeper (6 saves) and one quiet one, a goalkeeper back-pass followed by a switch of play, 1,771 events.

### Calibration

`python3 report_calibration.py` runs the engine over 60 seeds and compares it with `calibration.py`. Output from the last run (60 seeds, all targets pass):

| Metric | Simulated | Target | Kind |
| --- | --- | --- | --- |
| Completed passes per match (both teams) | 758.2 | 713 | verified |
| Long passes, share of passes | 12.0% | 11.5% | verified |
| Passes ending in the final third | 35.1% | 34% | verified |
| Goal kicks ending in the opposition half | 48.6% | 48% | verified |
| Goals that are headers | 23.4% | 21% | verified |
| Second-half added time | 387.1 s | 408 s | verified |
| Pass completion | 81.1% | 80-85% | approximate |
| Goals per match | 2.8 | 2.7-2.9 | approximate |
| Shots per match (both teams) | 26.0 | 24-27 | approximate |
| Shots on target per match | 9.0 | 8-9 | approximate (just outside the range, within the 25% tolerance) |
| Corners per match | 10.2 | 10-11 | approximate |
| Fouls per match | 23.7 | 20-24 | approximate |
| Yellow cards per match | 4.3 | 4-5 | approximate |
| Red cards per match | 0.1 | 0.1-0.15 | approximate |
| Offsides per match | 3.7 | 3-4 | approximate |
| Crosses attempted per match | 39.8 | 30-40 | approximate |
| Cross completion | 27.8% | 25-30% | approximate |
| Throw-ins per match | 48.8 | 40-55 | approximate |
| Possession of the team with less of the ball | 46.8% | 40-50% | approximate |

- **Verified** targets are Premier League 2025/26 figures from the first 11 matchweeks. The simulated average must be within 15 percent.
- **Approximate** targets are general football knowledge and are **unverified**. They are ranges, and the simulated average must be within 25 percent.
- Two assumptions of mine: "about 713 completed passes" is read as both teams combined, and a "long" pass is 32 m or more.

### Saveability

`scoring.py` rates each on-target shot from 0 (nearly unstoppable) to 100 (routine stop) with a transparent weighted formula of 14 factors (placement, reaction time, distance, speed, reach, angle, deflection, defenders in the lane, recovery, keeper set, depth, ball shift, swerve, foot or header). It is not machine learning. The weights and the keeper's reaction and dive numbers are hand-picked assumptions, not fitted to real football data.

## Run it locally

```
pip install -r requirements.txt        # the app and the agents; requirements-app.txt is the app only
az login                               # only needed to call the agents
streamlit run app.py
```

Settings go in a `.env` file that is never committed. Variable names only:

- `PROJECT_ENDPOINT`, `MODEL_DEPLOYMENT_NAME`: the Foundry project and deployment the agents use.
- `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_KEY`, `AZURE_OPENAI_DEPLOYMENT`: only for `smoke_test.py`.
- `LAST_LINE_LIVE_AGENTS`: set to `0` to never call the agents (the default is `1`, and the app still needs `PROJECT_ENDPOINT` to call them).

Tests (each file runs on its own with `python3`, or run `python3 -m pytest` for all of them; no Azure access needed):

```
python3 test_sim.py            # engine, tracking and the event contract
python3 test_vision.py         # sightline geometry and frames
python3 test_perception.py     # what each keeper perceives
python3 test_scoring.py        # saveability and shot situations
python3 test_architecture.py   # nothing reads the raw match except the data layer
python3 test_inspector.py      # event wording and perception rules for facts
python3 test_selection.py      # selecting, pausing and going back to live
python3 test_app.py            # the app
python3 test_cache_only.py     # the deployed behavior: no key, cache only
python3 test_theme.py          # design tokens and contrast
```

Regenerate the match and the text cache:

```
python3 generate_match.py              # match_events.json and tracking.npz (seed 15)
python3 report_calibration.py          # the engine against its targets (60 seeds, about 30 s)
python3 build_cache.py --dry-run       # count the agent requests still needed; calls nothing
python3 build_cache.py                 # fill the text cache with the agents (resumable)
python3 pipeline.py --only 49:04       # one moment as JSON, through the agents
```

Commit the match and the cache together. The cache is valid only for the exact `match_events.json` it was built with.

Docker (the cache-only app): `docker build -t last-line .` then `docker run -p 8501:8501 last-line`.

## Limitations and honesty

- The data is synthetic. It is calibrated to published averages where they exist; six targets are verified and the rest are approximate and unverified. It is not real match data and says nothing about real teams or players.
- The sightline is a model: a fixed 120 degree, 85 m cone aimed at the ball. The tracking has no head or eye direction, no peripheral or partial vision, and a body either blocks a point or does not.
- Saveability is a hand-built formula with hand-picked weights, not fitted to real shots. It ranks shots in this simulation; it is not a real expected-goals or expected-saves model.
- Passes have no recorded destination, so their facts come from where the ball was at the next event.
- The engine leaves out fatigue, momentum, VAR, weather and referee judgment beyond a foul rate. Injuries appear only as stoppages.
- The live deployment shows pre-generated texts for one match (seed 15), with template lines where nothing is cached. The agents are not called there.
- AI texts can still be wrong. The agents are told to use only the numbers they are given, and the fallback templates are built straight from the scoring fields, but the generated wording is not checked by hand.
- The cached texts for the key moments were written before the sightline grew from 55 m to 85 m. The moments and their facts do not depend on it, but the "missed" counts inside a few analyst texts may differ slightly.

## Credits

Built solo for the Microsoft x Premier League "Inside the Game" hackathon, October 2026. Developed with AI assistance from Claude Code. Fictional clubs and players. Match engine design, calibration targets and sources are in `SIM_DESIGN.md` and `calibration.py`.
