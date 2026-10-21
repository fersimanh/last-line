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
| shot | outcome (goal, saved, off_target, blocked), distance_m, speed_kmh, body_part, keeper, keeper_x, keeper_y, end_y and end_z (not on blocked shots) |
| goal | related_to (shot id), score |
| keeper_save | related_to (shot id), end_z |
| keeper_claim, keeper_sweep | none |
| keeper_distribution | kind (short or long), outcome (completed or lost) |
| tackle, possession_change | none |

## Run it

```
pip install openai python-dotenv
python3 generate_match.py
```

Azure settings go in a `.env` file (never committed): `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_KEY`, `AZURE_OPENAI_DEPLOYMENT`.

## Status

Built for the hackathon, October 2026. In progress: live replay, saveability scoring, Foundry agents, Streamlit interface.