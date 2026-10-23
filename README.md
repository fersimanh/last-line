# Last Line

Goalkeeper-lens match intelligence for the Microsoft x Premier League "Inside the Game" hackathon. A replayed synthetic match flows through three Microsoft Foundry agents that score each threat on goal, explain it from the keeper's point of view, and adapt the story to each viewer.

## Match engine

The match is produced by a position-based engine: 22 tracked players and a ball move on the pitch, and the events are read off what happens. It is **football-realistic, calibrated to published league averages where available; not real match data.** Design: `SIM_DESIGN.md`. Targets and their sources: `calibration.py`; run `python3 report_calibration.py` (60 seeds by default, `--seeds N`; about 2.5 minutes).

- **Verified** targets are published Premier League 2025/26 figures (first 11 matchweeks): completed passes per match, long-pass share, share of passes ending in the final third, goal kicks ending in the opposition half, header share of goals, second-half added time. The simulated average must be within 15 percent.
- **Approximate** targets are general football knowledge, **UNVERIFIED**, treated as ranges and held to within 25 percent: pass completion, goals, shots, shots on target, corners, fouls, cards, offsides, crosses, throw-ins and possession. The report also says whether a value is inside the range or only within 25 percent of it.
- Assumptions of mine: "about 713 completed passes" is read as both teams combined, and a "long" pass is 32 m or more.
- Over 120 seeds all 19 targets pass: for example 757 completed passes, 12.0% long, 35% ending in the final third, 48.5% of goal kicks reaching the opposition half, 23.3% of goals headers, 384 s of second-half added time, 2.8 goals, 25.6 shots and 10.6 corners per match. Red cards (0.2 against 0.1-0.15) and crosses (40 against 30-40) sit just outside their stated ranges, inside the 25% band. Header share is noisy, so fewer than about 60 seeds can show a false FAIL. A match takes 2-5 s to simulate.
- Known gaps: about 22 goal kicks per match is a little above real football (my rough figure is 16-18, UNVERIFIED); no fatigue, VAR, weather or referee judgment beyond foul and card rates.
- `tracking.npz` holds all 22 players and the ball every 0.5 s in absolute pitch coordinates (int16 centimeters), read with `tracking.py`; it also records which player stands in each slot, so substitutions are visible. `contract.json` freezes the fields the original event types had, and `test_sim.py` checks the engine never drops one.
- The earlier rule-based generator is kept as `legacy_generator.py` (used by one geometry test).

## Synthetic data

All data is invented: fictional clubs (Harbor United, Northgate FC), fictional players, no real match data. `generate_match.py` runs the engine and writes `match_events.json` and `tracking.npz` (seeded, so it is reproducible).

Pitch: 105 x 68 m, goal centered at y = 34 (goal width 7.32 m, height 2.44 m). There are two coordinate frames:

- **Attacking frame** (every event except `keeper_distribution`): the team in possession attacks toward x = 105. Defending events in that possession (saves, claims, sweeps, tackles) use the same frame, so a keeper making a save stands near x = 101-104.
- **Own frame** (`keeper_distribution` only, including `target_x`, `target_y` and every option): the distributing keeper's team attacks toward x = 105, so its keeper stands near x = 2-6. To move a point between frames: x -> 105 - x, y -> 68 - y.

The match uses seed 15, chosen from seeds 1-60 because it has 2 goals (Northgate FC 2-0), one busy keeper (Mateo Rios, 6 saves) and one quiet one (Elias Novak, 2 saves), a goalkeeper back-pass followed by a switch of play (49:04), a corner the keeper claims (06:40) and a direct free kick with a four-man wall (13:55). It has 1,771 events, 7 corners, 46 throw-ins and 22 goal kicks. Each event carries `clock`, the time a fan sees: the first half runs 00:00 to 45:00 and then added time as `45+3:34`; the second half starts again at 45:00 and runs to 90:00, then `90+8:11`. The fields `minute` and `second` stay on the engine's own continuous clock (no half-time gap), which the app uses to order and scrub. (The numbers further down in the distribution and saveability sections were measured on the earlier generator, seeds 1-40, and are kept as design notes.)

### Fields on every event

`id`, `minute`, `second`, `half`, `team`, `player`, `type`, `x`, `y`

### Traffic: the players around an event

Events in the attacking third (within 35 m of a goal: `x` of 70 or more in their frame), except keeper actions and goal events, also carry `traffic`: the other players standing around, each with `team`, `role` (`defender` or `attacker`) and `x`, `y` in the same frame as the event. Keeper distributions carry their own `traffic` (in the distributing team's frame): `presser`s, one per `opponents_close`, within 10 m of the keeper, and one `marker` per passing option standing exactly that option's `open_m` away. The bodies always agree with the numbers on the event: a shot has exactly `defenders_in_lane` defenders inside the triangle between the ball and the posts, and every option's nearest opponent is its marker. The data has no full 22-player tracking, so events further from goal have no traffic and nothing blocks the view there.

### Event types and extra fields

| type | extra fields |
| --- | --- |
| pass | receiver, success |
| cross, through_ball, box_entry | none |
| shot | outcome (goal, saved, off_target, blocked), distance_m, speed_kmh, body_part, keeper, keeper_x, keeper_y, defenders_in_lane (0-3), deflected (true/false), swerve (0-1), keeper_set (true/false), end_y and end_z (not on blocked shots), plus its situation: see [Shot situations](#shot-situations) |
| goal | related_to (shot id), score |
| keeper_save | related_to (shot id), end_z, held (true = caught, false = parried) |
| keeper_claim, keeper_sweep | none |
| keeper_close_down | target_player: the attacker the keeper came off the line to close down (1-on-1 and 2-on-1). Recorded in the attacking frame, like saves |
| keeper_distribution | see [Keeper distribution](#keeper-distribution) below, plus `traffic` |
| tackle, possession_change | none |

### Keeper distribution

Every time a keeper gives the ball away there is a `keeper_distribution` event (`player` is the keeper, `team` the keeper's team, `x`/`y` where the keeper released it, in the own frame).

| field | values |
| --- | --- |
| trigger | why the keeper has the ball: `goal_kick` (after the other team's off-target shot), `after_save`, `after_claim`, `back_pass` (a teammate passed back) |
| method | `throw`, `roll`, `ground_pass`, `kick`. Throws and rolls only from the hands (after a save or claim) and only up to 30 m; a back pass must be played with the feet |
| technique | throw: `overarm`, `sidearm`; roll: `bowled`; ground_pass: `side_foot`, `pass_out_from_back`; kick: `driven_low`, `lofted`, `drop_kick`, `volley`, `goal_kick_long` |
| kind | `short` or `long` (long = kick), kept from the old format |
| target_player, target_role | who received it; role is `CB`, `FB`, `DM`, `CM`, `W` or `ST` |
| target_x, target_y, distance_m | where the target stood (own frame) and how far away |
| direction | `forward`, `lateral` or `backward` |
| pressure, opponents_close | `low` (0 opponents close to the keeper), `medium` (1), `high` (2-3) |
| options | the 2-4 teammates on the pitch for this pass, each with `player`, `role`, `x`, `y`, `distance_m`, `open_m` (meters to the nearest opponent) and `visible`: whether the keeper could see it while scanning up the pitch: inside the sightline and not hidden behind a presser or marker (see [Perception](#perception)). The keeper only chooses among visible options, so the target is always visible |
| reason | `free_man`, `relieve_press`, `break_press_long`, `switch_play`, `safe_retention`, `quick_counter` |
| outcome | `completed`, `intercepted`, `contested_won`, `contested_lost` (completed and contested_won keep the ball) |
| x_gain_m | meters the ball moved up the pitch (target_x minus keeper x) |
| led_to_shot, shot_id | true, with the shot's id, when the team shoots within 30 s of a completed distribution without the other team touching the ball |

How the simulation behaves (checked over seeds 1-40): short ground passes complete about 92% at low pressure and 70% at high pressure; long kicks succeed about 57%; throws and rolls about 88%. Short passes are the most common choice at low pressure, long kicks at high pressure. About 1 option per distribution is out of the keeper's sight, beyond the cone or behind a body (74% of distributions have at least one), which is why far strikers are chosen less often. The keeper picks the best visible option about 78% of the time.

### Distribution rating

`scoring.distribution_insight(event)` rates each distribution 0-100 using the same rules the generator uses (`pick_method`, `pass_success_prob`, `option_value` in `scoring.py`):

- **difficulty**: distance 35%, pressure 30%, method 20% (rolls easiest, kicks hardest), how tightly the receiver was marked 15%.
- **decision_score**: each option's value is its chance of success times the ground it gains, minus the cost of losing the ball (losing it close to your own goal costs much more). It is judged against the best option the keeper could SEE: choosing it scores 100; each 0.005 of value given up costs one point.
- **quality**: decision 40% + outcome 30% (completed 100, contested won 80, contested lost 25, intercepted 0) + difficulty 30%, where difficulty only counts when the pass worked.
- **verdict**: `turnover` if the ball was lost, `excellent` at quality 80+, `risky` if the decision was under 60 or difficulty 60+, otherwise `safe`. A short `key_factor` says why.

A distribution is a key moment (a `DIST` line in `replay.py`, an agent explanation and an app card) when it was under high pressure, intercepted, led to a shot, or the decision was very poor (under 50) or very good on a hard pass (95+ with difficulty 55+). Routine ones stay quiet. `keeper_report()` adds `distributions`, `completed`, `distribution_completion_pct`, `long_attempts`, `long_completed`, `long_ball_pct`, `pressure_completions`, `progressive_m`, `avg_decision_score` and `attacks_started`.

### Shot situations

Every shot comes from a situation, and the generator adds the build-up events that lead to it. The situation decides where the shot is struck from, where the keeper stands, how likely the keeper is to be set, and how dangerous the chance is.

| situation | build-up | keeper |
| --- | --- | --- |
| open_play | struck near where the move ended | set unless the ball just moved across them |
| cutback | a winger reaches the byline and pulls it back (a `pass` with `assist: "cutback"`) | guarding the near post, set about 40% |
| header_from_cross | a `cross` from wide, then a header | shifted toward the cross, set about 60% |
| one_on_one | a `through_ball`, then the keeper comes out (`keeper_close_down` on the shooter) | off the line narrowing the angle, set about 55% |
| two_on_one | a `through_ball`; the keeper closes down the ball carrier, who squares it (`pass` with `assist: "square"`) to the free attacker | stranded and moving, set about 10% |
| rebound | the keeper parries a save (`held: false`) and an attacker follows up within 1-4 s | still where they saved it, set about 10% |
| second_ball | a blocked shot falls to another attacker | set about 85% |

Each shot also records `situation`, `assist_id` and `assist_type` (the action that set it up), `assist_seconds`, `ball_shift_m` (how far the ball moved sideways from the assist to the shot), and `seconds_since_keeper_action` (how long since the defending keeper last had to act: a save, claim, sweep, close-down or distribution; null if never). Shooters aim at the side the keeper has left open. Across seeds 1-40, shots convert at about 10% from open play, 12% from crosses, 17% from cutbacks, 24% one on one, 30% two on one, 13% from rebounds and 4% from second balls.

## Saveability score

`scoring.py` rates every on-target shot from 0 (nearly unstoppable) to 100 (routine stop): 65+ is "should save", 35-64 "tough save", below 35 "near-unstoppable". It is a transparent weighted formula, not machine learning. Each factor runs from 0 (hard for the keeper) to 1 (easy):

| Factor | Weight | Easier for the keeper when |
| --- | --- | --- |
| placement | 16% | the shot is low and near the middle of the goal |
| reaction | 14% | the ball's flight time is long compared with the keeper's reaction (0.25 s) plus dive (4.5 m/s) time |
| distance | 11% | the shot is struck from far away |
| speed | 11% | the shot is slower |
| reach | 9% | the keeper is already close to where the ball ends up |
| angle | 7% | the shot comes from near the goal's center line |
| no_deflection | 5% | the shot is a clean strike |
| lane | 5% | no defenders stand between the ball and the keeper |
| recovery | 5% | the keeper has not had to act for a while (fully ready again 4.5 s after a save or close-down) |
| keeper_set | 5% | the keeper was balanced and ready when it was struck |
| depth | 4% | the keeper stands at the ideal distance off the line (further out against long shots; one on one, about 6 m from the shooter to narrow the angle) |
| shift | 4% | the ball did not move across the keeper fast just before the shot (a square pass at 12 m/s or more scores 0) |
| swerve | 3% | the ball flies straight |
| foot_strike | 1% | it is a foot strike, not a header |

The weighted sum is stretched around a midpoint (`CENTER = 50`, the average raw score over seeds 1-40) by `SPREAD = 2.0`, which gives about 25% "should save", 50% "tough save" and 25% "near-unstoppable". The weights, the reaction, dive and recovery numbers are hand-picked assumptions, not fitted to real football data; the midpoint and spread are calibrated on the synthetic seeds only. Reaction overlaps with distance, speed and reach on purpose: it asks whether the keeper had enough time, while the others show what drove that. Average scores by situation (seeds 1-40): two on one 26, cutback 40, one on one 44, rebound 47, open play 54, header 56, second ball 75. `defenders_in_lane`, `deflected` and `swerve` come from a separate random stream; `keeper_set` now follows from the situation and changes the chance of a goal.

## Perception

The keeper's field of view is the INPUT, not an overlay: the agents only ever learn what the keeper could perceive.

- `vision.py` (pure geometry): converts every event into the followed keeper's frame (own goal at x = 0, y = 34; see the two data frames above), tracks where the keeper stands, points them at the ball, and decides visibility with one function, `is_visible(keeper_pos, facing, event_pos, fov_deg=120, radius_m=55, blockers=())`. An event counts as seen when it was inside the cone the keeper was facing just BEFORE it happened (toward the ball's previous position) and no body from its `traffic` stood in the line of sight. A body 0.6 m wide hides a point when it is nearer the keeper than the point and the sightline passes through it, so a player 2 m in front of the keeper hides a wide angle and one 25 m away hides only a sliver.
- `perception.py`: `PerceptionFilter(team)` replays the match through one keeper's eyes and sorts each event:
  - **perceived** (`PerceivedEvent`, with a `sight`): `own` (the keeper's own save, claim, sweep or distribution), `seen` (inside the sightline), or `felt` (not seen, but impossible to miss: a shot that reaches their goal, or any goal). For distributions, options outside the sightline are removed and counted in `unseen_options`.
  - **missed**: the missed log, with a reason (`beyond_radius`, `outside_fov`, `blocked` by a body, `unseen_option`). It is only for the Reveal view; it never reaches the agents.
  - `state` is the keeper's own picture of the match (a `MatchState` fed with perceived events only), and `unseen_count()` says how much they missed.

Each keeper perceives about 790-830 of the 1,410 events. Most misses are beyond 55 m (the far half); about 50 per keeper are close but outside the cone, and 10-12 are hidden behind a body. Every key moment reaches its keeper. Defenders in a shot's lane usually narrow the angle rather than fully hide the shooter: only a few screened shots are actually blocked from the keeper's eye.

`test_architecture.py` enforces the rule: only the data layer (`generate_match.py`, `legacy_generator.py`, `replay.py`, `scoring.py`, `vision.py`, `perception.py`) may read the raw match, and `agents.py` and `pipeline.py` may never touch the missed log. Every other module, `app.py` included, reads the match only through `PerceptionFilter` (the app also uses its `missed` list and `reveal()` for the Reveal view, which is display only).

## Architecture

```
match_events.json -> PerceptionFilter (one per keeper: perceived events + missed log)
                                            |
                         perceived key moment? (save, goal, claim, sweep, notable distribution)
                                            |
              Shot Analyst -> Narrator -> Personalizer (once per viewer) -> JSON line
                    |              |                         \
     tools read LiveMatch     gets sight +           fallback: saveability score + verdict
     (perceived only)         unseen count, never the missed log
```

Each keeper's perceived events update their own picture of the match; only key moments call the agents, which keeps cost and latency down. The handoffs are plain sequential calls, each agent's output becomes the next agent's input. If any agent fails or times out, that moment still gets a fallback line built from the saveability score and verdict.

| Agent | Role |
| --- | --- |
| Shot Analyst | Calls tools (`get_current_moment`, `get_keeper_stats`, `get_pressure`) that read the keeper's perceived match state (with the sight and unseen count), then writes a short factual summary. Only uses numbers from the tools. |
| Narrator | Speaks as the goalkeeper: 1-2 first-person sentences per moment (saying so when they did not see a move develop), plus halftime and full-time reports built from the keeper's own perceived numbers and how much they could not see. |
| Personalizer | Adapts the narration per viewer: casual or analyst mode, favorite club, English or Spanish. |

Built with Microsoft Agent Framework (`Agent` + `FoundryChatClient`) against a Foundry project, authenticated with Entra ID (`az login`), no API key. Code: `agents.py` (the agents and tools), `pipeline.py` (state, handoffs, fallback, JSON output).

Each output line is JSON with `clock`, `match_second`, `type`, `player`, `keeper`, `score`, `sight`, `unseen_count` (events missed in the 30 seconds before), `saveability`, `verdict`, `key_factor`, `analysis`, `narration`, `versions` (one per viewer, with a `fallback` flag), `errors` and a UTC `generated_at` timestamp. A `half_time` line arrives before the first second-half event, and the last line is the `full_time` report.

## Streamlit app

`app.py` has two views of the same match, switched with the **View** control in the sidebar. Switching never restarts the match.

- **Keeper's eyes** (the default): a 2D pitch from the followed goal line to just past halfway. A translucent lime cone is the keeper's **modeled sightline** (the data has no real eyeline): 120 degrees by default, 55 m long, always turned toward the ball. Everything outside the cone is dimmed. The last 8 perceived events appear as markers with a fading trail: circle = seen, square = your own action, diamond = felt but not seen, star = goal. A top panel shows the workload meter, the danger level (a shape and a word, not only a color) and **how much the keeper missed** (in the last 30 s and so far). Cards for key moments are written to the keeper in the second person ("You're 4 m off your line..."), each with a mono label row, a headline carrying the verdict, a sight pill (**Seen clearly**, **Late sight** or **Your action**; text, not color alone) and a **Show the numbers** expander.
- **Reveal**: what the keeper did not perceive. The same pitch also draws the events the keeper missed, hollow, with a list of why (too far away, outside the cone, blocked by a player, passing options out of sight), then the official numbers: shot map colored by saveability, goal mouth, workload and danger from the full match.
- **Top bar**: the score and the clock in large numerals, and a segmented timeline of the whole match, added time included, with a tick at half time and a diamond for every goal.
- **Sidebar**: view, mode (Casual fan or Analyst), favorite club (decides which keeper you follow; with **Both** a small selector switches keepers), language (English or Spanish), replay speed (default 120x, a full match in 45 s), **field of view** (90-180 degrees), Play, Pause and Restart.
- **Full-time report** tab: the keeper's numbers as the keeper knows them (shot stopping and distribution) plus the Narrator's report.

### Click to inspect

Click any event to see what happened and why. Selecting an event **pauses the match**; **Back to live** closes the inspector and resumes. Three ways to pick one:

- **Click a marker on the pitch** (the last 8 events), or a shot on the Reveal shot map.
- **Click a row in the Events list** (the second tab beside Key moments): scrollable, newest first, with filters for All, Shots, Passes, Keeper and Other.
- **Drag the minute scrubber** under the timeline, or use **Previous / Next moment**, which jump to the keeper's key moments, select them and pause. Small ticks on the timeline mark the key moments so far (goals stay diamonds).

The perception rule holds: in **Keeper's eyes** only events the keeper perceived can be picked (a forced or stale selection of anything else is refused with a notice); in **Reveal** every event can be picked, and missed ones are flagged with the reason.

The inspector shows a header (minute, event type, sight, whether the text is an **AI insight** or a **Quick insight**, and the players), a small snapshot of that moment (the cone shows where the keeper was looking just before it), the explanation in the current mode, language and view, a line saying how many events you saw and missed in the 30 seconds before (Reveal lists the missed ones), and a **Show the numbers** expander: the 14 saveability factors for shots, difficulty and decision quality for passes out, and distance, direction, pressure and outcome for ordinary passes.

Where the text comes from (`inspector.py`, `insights.get_event_text`): every event type has an instant second-person **Quick insight** template in English and Spanish. Key moments and **notable passes** also have cached **AI insight** text: every keeper pass, passes that gain 20 m or more going forward, long balls of 45 m or more, passes that set up a shot, and passes lost in the team's own third (none in this match: its possessions only break down in the attacking half). Each notable pass is explained for the one keeper it matters to (the one defending the nearer goal). On a cache miss the app asks the agents live and stores the answer; if they are unreachable it shows the Quick insight. Pass facts come from the ball's next position (the data has no pass destination), and anything that depends on an event the keeper did not perceive is left out of Keeper's eyes.

The field-of-view slider is a what-if for the visuals: the cone, the dimming and the missed counts follow it, while the explanations were written for the 120 degree sightline (the app says so under the slider).

The match position lives in `st.session_state`. The live area is an `st.fragment` with `run_every`, so only it reruns while playing (the sidebar and the stylesheet are not re-sent); Pause switches the timer off. The match clock advances by the real time that passed times the replay speed, so playback speed stays right however often the screen refreshes, and a sleeping browser tab cannot make the match jump (a step is capped at 2 s).

Card and report text comes from `insights.py`: first `insight_cache.json` (instant), then the agents on a cache miss (slow, then cached), then a template fallback line built from the scoring fields, in English and Spanish. The cache key is moment, mode, club, language and view; the Reveal view reuses the Keeper's eyes texts. `python3 build_cache.py` fills the cache (key moments, notable passes and the full-time reports; resumable, it skips anything already cached) so the demo does not depend on live API calls: `--dry-run` only counts the requests, `--only notable` or `--only moments` fills one part. (`insights.py --warm` is the older all-in-one fill for the key moments; `--view broadcast` also generates first-person texts.) The cache records a hash of `match_events.json` plus a text version (`TEXT_VERSION` in `insights.py`, bumped when the agents' input changes) and is ignored when either differs, so it never shows text for the wrong moment or from an older pipeline. Set `LAST_LINE_LIVE_AGENTS=0` to never call the agents.

### The look

Dark only, in the style of the "Onside look" brief; Last Line has its own name and mark. Every color, font, radius and spacing is defined once in `theme.py` and used by both the CSS (`theme.build_css()`, sent once per full run by `inject_css()` in `app.py`) and the Plotly charts, and `.streamlit/config.toml` repeats the few colors Streamlit needs before Python runs (`test_theme.py` checks they match). Fonts load from Google Fonts with fallbacks: Fraunces (wordmark, headings, big numbers; fallback Georgia), Outfit (body and controls; fallback system-ui), JetBrains Mono (small uppercase labels and timestamps; fallback ui-monospace). Streamlit's built-in red, blue and other accent hues are repainted from the palette, so no default color shows.

Accessibility: all reading text is at least 4.5:1 (body text 8.4:1 on cards, headings 15:1, dark text on lime 14.8:1). The mono label color (#51694d, about 3:1) is used only for small labels, never for text people must read; the faint caption color is not used anywhere. Every control has a lime focus ring, `prefers-reduced-motion` switches animations and transitions off, and there are no emojis. The hard-to-save end of the saveability scale (#3f4f22) is only 2:1 against the pitch, so every shot marker also has a light outline and its own shape, and the chart keeps a legend and hover labels.

## Run it

```
pip install -r requirements.txt
az login                            # only needed for the agents
python3 generate_match.py            # match_events.json and tracking.npz (seed 15)
python3 report_calibration.py       # the engine against its targets
python3 test_sim.py                 # engine, tracking and contract tests
streamlit run app.py                # the app
python3 test_app.py                 # app tests (no Azure needed)
python3 test_vision.py              # sightline geometry and frames
python3 test_perception.py          # what each keeper perceives
python3 test_scoring.py             # shot situations in the saveability score
python3 test_inspector.py           # event wording, notable passes, perception rules for facts
python3 test_selection.py           # the rules for selecting, pausing and going back to live
python3 test_architecture.py        # nothing reads the raw match except the data layer
python3 test_theme.py               # design tokens, fonts, contrast, Streamlit config
python3 build_cache.py --dry-run    # count the agent requests still needed (calls nothing)
python3 build_cache.py              # fill the text cache (resumable)
python3 hello_agent.py              # checks Foundry auth
python3 pipeline.py --only 49:04    # one moment as JSON (the keeper's back-pass and switch)
python3 pipeline.py > moments.jsonl # whole match as JSON
```

Settings go in a `.env` file (never committed): `PROJECT_ENDPOINT`, `MODEL_DEPLOYMENT_NAME` for the agents; `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_KEY`, `AZURE_OPENAI_DEPLOYMENT` for `smoke_test.py`.

## Status

Built for the hackathon, October 2026. Done: position-based match engine with tracking, live replay, saveability scoring, Foundry agents, Streamlit interface. Not deployed yet.