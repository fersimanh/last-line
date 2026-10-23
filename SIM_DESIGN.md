# Match engine design (position-based)

**Goal.** Replace the event-by-event generator with an engine that plays football on a pitch: 22 players and a ball move in continuous time, decisions come from real positions, and the events (plus a 2 Hz tracking file) are *read off* what happened. It must stay football-realistic and calibrated to published averages where they exist. It is synthetic: fictional clubs and players, not real match data.

**Branch and safety.** Work happens on `realism`. Until Stage 3 the old `generate_match.py` and `match_events.json` are untouched, so the app and every test keep working. The engine writes `sim_events.json` and `sim_tracking.npz`; Stage 3 swaps them in.

## The contract (kept exactly)
- Event types: `pass cross through_ball box_entry shot goal keeper_save keeper_claim keeper_sweep keeper_close_down keeper_distribution tackle possession_change`. New types may be added (`dribble stoppage throw_in goal_kick corner free_kick offside foul card substitution off_ball_run ...`).
- Every event: `id minute second half team player type x y`, sorted by time, ids sequential. New fields: `t` (exact seconds), `end_x end_y length_m pass_type pressure_m` on passes.
- **Frame rule (unchanged):** a possession is recorded in the *attacking* team's frame (it attacks toward x = 105, goal at y = 34). Defending events (`tackle possession_change keeper_save keeper_claim keeper_sweep keeper_close_down`) sit in the *attacker's* frame. `keeper_distribution` is in the distributor's own frame.
- Shots keep the 14-factor save-score fields and the build-up context; `traffic` keeps its shape (`team role x y`), now taken from real positions.

## Coordinates and tracking
- **Absolute pitch:** x 0-105, y 0-68. The home team attacks +x in the first half; sides swap at half time.
- **Team frame** (= event frame = keeper frame): flip `(x, y) -> (105 - x, 68 - y)` when the team attacks -x. The keeper frame of a followed team is that team's frame, so one function serves all three.
- **Tracking:** all 22 players and the ball every 0.5 s for the whole match (stoppages included), stored as int16 centimeters in `*.npz`. `tracking.py` loads it, interpolates (`positions_at`), and converts to any frame.

## Teams
Formation anchors per slot (4-4-2, 4-3-3, 4-2-3-1) in the team frame. Tactics: defensive line height, width, press intensity, directness (long-ball share), crossing tendency. Attributes per player (pace, passing, tackling, shooting, control) depend on role plus a little noise. Same fictional names; a bench of seven each for substitutions.

## Movement (every 0.5 s)
Target = anchor, widened by the width tactic, pushed forward when in possession and back when not (line height decides how far), pulled toward the ball by compactness. The nearest defenders press by intensity; attackers make runs into space; the receiver runs onto the pass; the keeper tracks the ball. Steering is limited by max speed and acceleration, with a small repulsion so players do not stack.

## Possession loop
The ball carrier acts every 1-3 s (faster under pressure). Options: pass to each teammate, dribble (and, from Stage 2, shoot). Each pass is classed from geometry: short, back, switch (lateral over 30 m), long (32 m or more), through, cross. An option's score blends progression, success chance, receiver openness, zone and tactics (directness, crossing), with noise, and the choice is a softmax. Success chance depends on pass type and length, pressure on the passer, how marked the receiver is, lane obstruction and passer skill. A failure becomes an interception, a lost duel, or the ball going out of play.

## Stages
1. **Formations, tracking, possession loop** with pass success and failure. The ball going out stops play briefly (a `stoppage` event) and the opponent restarts; no set pieces yet. The keeper is tracked but not yet in possession.
2. Stoppages and set pieces (throw-ins, goal kicks, corners, fouls, free kicks, offsides, penalties, cards, substitutions, half time, added time), keeper involvement, shots, goals.
3. Calibration against `calibration.py` until every target passes; pick the demo seed; switch the app over.
4. Perception on real positions (line of sight and screening from tracking); retire the synthetic `traffic` workaround only if every test still passes.

## Stage 2: stoppages, set pieces, keeper, shots (built)
- **Files:** `sim_engine.py` (core loop), `sim_stops.py` (dead balls, fouls, cards, subs, half time, added time, off-ball runs), `sim_shots.py` (shots, goals, crosses, corner and free-kick deliveries), `sim_keeper.py` (the keeper in possession).
- **Stoppages:** every dead ball is a `stoppage` event (reason + duration). The ball is carried back to the restart spot, and players walk to set-piece positions in the tracking (a wall at 9.15 m, the box filling up for a corner).
- **Set pieces:** throw-ins (nearest outfielder passes), goal kicks (a long or short choice by team directness), corners (inswinger/outswinger/short, box occupancy counted from tracking, keeper decision claim/punch/miss/stay), direct free kicks (wall size and offset, keeper vs the near post), penalties.
- **Shots:** location, defenders in the lane (counted from the tracked positions), body part, speed and a goal probability from distance, angle, pressure and the keeper's position. The build-up context (assist, rebound, second ball, one-on-one, two-on-one) is kept.
- **Referee:** fouls come from challenges on the carrier; cards from fouls (a second yellow is a red); penalties for fouls in the box. Offsides use the real line of the last defender.
- **Substitutions:** up to 5 per team in up to 3 windows; the tracking records `who` stands in each slot, so a name swap is visible at the moment of the change.
- **Added time:** a share of the stoppage time that counted (goals, cards, subs, penalties, ...) plus a little noise.
- **Contract:** `contract.json` freezes the field list of every original event type; `test_sim.py` checks the engine never drops one.

## Stage 4: perception on real positions (built)
`vision.build_timeline` reads `tracking.npz` through `perception.load_tracking`: the keeper's tracked position, a gaze toward where the ball was 0.5 s before each event, and every other player on the pitch as a body that may block the view (`Tracking.frame_arrays` builds the keeper-frame arrays once). The engine no longer writes `traffic`; files without tracking fall back to it. `PerceptionFilter.state_at` and `snapshot` also return the players in view, which the app draws.

## Calibration
Every target lives in `calibration.py` with a source label: **verified** (Premier League 2025/26, first 11 matchweeks; within 15%) or **approximate** (general knowledge, unverified; ranges, within 25%). `report_calibration.py` runs 60 seeds by default (header goals are rare, so fewer seeds are too noisy to judge) (`--seeds N`) and prints PASS or FAIL per metric. Metrics that need a later stage print `n/a`. Approximate ranges are UNVERIFIED; the report also says whether a value is inside the range or only within 25% of it.

## Left out on purpose
Fatigue, momentum, VAR, injuries, weather, referees' judgment beyond a foul rate.
