# Last Line

Goalkeeper-lens match intelligence for the Microsoft x Premier League "Inside the Game" hackathon. A replayed synthetic match flows through three Microsoft Foundry agents that score each threat on goal, explain it from the keeper's point of view, and adapt the story to each viewer.

## Synthetic data

All data is invented: fictional clubs (Harbor United, Northgate FC), fictional players, no real match data. `generate_match.py` writes `match_events.json` (seeded, so it is reproducible).

Pitch: 105 x 68 m. Each event is in the frame of the team in possession, attacking toward x = 105, goal centered at y = 34 (goal width 7.32 m, height 2.44 m).

### Fields on every event

`id`, `minute`, `second`, `half`, `team`, `player`, `type`, `x`, `y`

### Event types and extra fields

| type | extra fields |
| --- | --- |
| pass | receiver, success |
| cross, through_ball, box_entry | none |
| shot | outcome (goal, saved, off_target, blocked), distance_m, speed_kmh, body_part, keeper, keeper_x, keeper_y, defenders_in_lane (0-3), deflected (true/false), swerve (0-1), keeper_set (true/false), end_y and end_z (not on blocked shots) |
| goal | related_to (shot id), score |
| keeper_save | related_to (shot id), end_z |
| keeper_claim, keeper_sweep | none |
| keeper_distribution | kind (short or long), outcome (completed or lost) |
| tackle, possession_change | none |

## Saveability score

`scoring.py` rates every on-target shot from 0 (nearly unstoppable) to 100 (routine stop): 65+ is "should save", 35-64 "tough save", below 35 "near-unstoppable". It is a transparent weighted formula, not machine learning. Each factor runs from 0 (hard for the keeper) to 1 (easy):

| Factor | Weight | Easier for the keeper when |
| --- | --- | --- |
| placement | 18% | the shot is low and near the middle of the goal |
| reaction | 16% | the ball's flight time is long compared with the keeper's reaction (0.25 s) plus dive (4.5 m/s) time |
| distance | 12% | the shot is struck from far away |
| speed | 12% | the shot is slower |
| reach | 10% | the keeper is already close to where the ball ends up |
| angle | 8% | the shot comes from near the goal's center line |
| no_deflection | 6% | the shot is a clean strike |
| lane | 5% | no defenders stand between the ball and the keeper |
| depth | 4% | the keeper stands at the ideal distance off the line (further out against long shots) |
| swerve | 4% | the ball flies straight |
| keeper_set | 4% | the keeper was balanced and ready when it was struck |
| foot_strike | 1% | it is a foot strike, not a header |

The weighted sum is stretched around a midpoint (`CENTER`) so scores spread out. The weights, the reaction and dive numbers, and the midpoint are hand-picked assumptions, not fitted to real football data. Reaction overlaps with distance, speed and reach on purpose: it asks whether the keeper had enough time, while the others show what drove that. The synthetic generator draws `defenders_in_lane`, `deflected`, `swerve` and `keeper_set` from a separate random stream, so they are simulated context and do not change who scores.

## Architecture

```
match_events.json -> replay.stream() -> LiveMatch (shared state, wraps scoring.MatchState)
                                            |
                          key moment? (saved shot, goal, claim, sweep)
                                            |
              Shot Analyst -> Narrator -> Personalizer (once per viewer) -> JSON line
                    |                                       \
          tools read LiveMatch                 fallback: saveability score + verdict
```

Every event updates the shared state; only key moments call the agents, which keeps cost and latency down. The handoffs are plain sequential calls, each agent's output becomes the next agent's input. If any agent fails or times out, that moment still gets a fallback line built from the saveability score and verdict.

| Agent | Role |
| --- | --- |
| Shot Analyst | Calls tools (`get_current_moment`, `get_keeper_stats`, `get_pressure`) that read the live match state, then writes a short factual summary. Only uses numbers from the tools. |
| Narrator | Speaks as the goalkeeper: 1-2 first-person sentences per moment, plus halftime and full-time keeper reports. |
| Personalizer | Adapts the narration per viewer: casual or analyst mode, favorite club, English or Spanish. |

Built with Microsoft Agent Framework (`Agent` + `FoundryChatClient`) against a Foundry project, authenticated with Entra ID (`az login`), no API key. Code: `agents.py` (the agents and tools), `pipeline.py` (state, handoffs, fallback, JSON output).

Each output line is JSON with `clock`, `match_second`, `type`, `player`, `keeper`, `score`, `saveability`, `verdict`, `key_factor`, `analysis`, `narration`, `versions` (one per viewer, with a `fallback` flag), `errors` and a UTC `generated_at` timestamp. A `half_time` line arrives before the first second-half event, and the last line is the `full_time` report.

## Streamlit app

`app.py` replays the match through the followed keeper's eyes:

- **Shot map**: a half pitch of the shots the keeper faced, appearing as the match plays. Color is saveability on a colorblind-safe red (hard) to gray to blue (easy) scale; off-target and blocked shots have no score and stay light gray. Each outcome has its own marker (star goal, circle saved, x off target, square blocked) and every marker has a hover label.
- **Goal mouth**: where each on-target shot crossed the 7.32 x 2.44 m goal, from the shooter's view.
- **Workload meter and danger indicator** for the followed goal (danger shows an icon and a word, not only a color).
- **Insight cards** for key moments, newest first.
- **Full-time report** tab: `keeper_report()` numbers plus the Narrator's report.
- **Sidebar**: mode (Casual fan or Analyst), favorite club (decides which keeper you follow, or Both), language (English or Spanish), replay speed (default 120x, a full match in 45 s), Play, Pause and Restart.

The match position lives in `st.session_state`, so changing any option mid-match re-renders the cards in the new mode and language without restarting.

Card and report text comes from `insights.py`: first `insight_cache.json` (instant), then the agents on a cache miss (slow, then cached), then a fallback line with the saveability score and verdict. `python3 insights.py --warm` fills the cache for every moment, mode, club and language, so the demo does not depend on live API calls. Set `LAST_LINE_LIVE_AGENTS=0` to never call the agents.

## Run it

```
pip install -r requirements.txt
az login                            # only needed for the agents
python3 generate_match.py
streamlit run app.py                # the app
python3 test_app.py                 # app tests (no Azure needed)
python3 insights.py --warm          # refill the text cache
python3 hello_agent.py              # checks Foundry auth
python3 pipeline.py --only 67:03    # one moment as JSON
python3 pipeline.py > moments.jsonl # whole match as JSON
```

Settings go in a `.env` file (never committed): `PROJECT_ENDPOINT`, `MODEL_DEPLOYMENT_NAME` for the agents; `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_KEY`, `AZURE_OPENAI_DEPLOYMENT` for `smoke_test.py`.

## Status

Built for the hackathon, October 2026. Done: synthetic data, live replay, saveability scoring, Foundry agents, Streamlit interface. Not deployed yet.