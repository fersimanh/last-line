"""Scoring and live match state for Last Line.

saveability(shot) rates how saveable an on-target shot was, 0-100:
  100 = a routine stop, 0 = nearly unstoppable.
It is a transparent formula (not machine learning) so the Foundry agents
can explain exactly which factors drove it.
"""

SPREAD = 1.7             # how far to stretch scores away from 50
GOAL_HALF_WIDTH = 3.66   # meters (goal is 7.32 m wide)
GOAL_HEIGHT = 2.44       # meters

# How much each attacking event adds to the danger rating
DANGER_WEIGHTS = {"box_entry": 2, "cross": 1, "through_ball": 2, "shot": 3}
DANGER_WINDOW_SEC = 5 * 60


def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def saveability(shot):
    """Return (score, factors) for an on-target shot, or (None, None) otherwise."""
    if shot.get("type") != "shot" or shot.get("outcome") not in ("goal", "saved"):
        return None, None

    # Each factor runs 0 (hard for the keeper) to 1 (easy for the keeper)
    distance = clamp((shot["distance_m"] - 5) / 30)
    speed = 1 - clamp((shot["speed_kmh"] - 70) / 60)
    lateral = abs(shot["end_y"] - 34) / GOAL_HALF_WIDTH
    height = shot["end_z"] / GOAL_HEIGHT
    placement = 1 - clamp(0.6 * lateral + 0.4 * height)
    reach = 1 - clamp(abs(shot["end_y"] - shot["keeper_y"]) / 3.5)

    factors = {"distance": distance, "speed": speed, "placement": placement, "reach": reach}
    raw = 100 * (0.25 * distance + 0.25 * speed + 0.30 * placement + 0.20 * reach)
    # Averaging four factors bunches scores near 50, so stretch them around the
    # midpoint. This spreads verdicts roughly 25% / 50% / 25%.
    score = clamp(50 + SPREAD * (raw - 50), 0, 100)
    return round(score), factors


def verdict(score):
    if score is None:
        return None
    if score >= 65:
        return "should save"
    if score >= 35:
        return "tough save"
    return "near-unstoppable"


HARD_REASONS = {
    "distance": "it was hit from close range",
    "speed": "it was struck very hard",
    "placement": "it was placed in a corner",
    "reach": "the keeper was caught far from the ball's path",
}
EASY_REASONS = {
    "distance": "it came from long range",
    "speed": "it was struck at only moderate pace",
    "placement": "it was hit close to the keeper's body",
    "reach": "the keeper was well positioned",
}


def key_factor(factors, score):
    """Name the factor that best explains the verdict: what made an easy
    save easy, or what made a hard shot hard."""
    if score >= 65:
        best = max(factors, key=factors.get)
        return EASY_REASONS[best]
    worst = min(factors, key=factors.get)
    return HARD_REASONS[worst]


def danger_level(points):
    if points >= 12:
        return "high"
    if points >= 6:
        return "medium"
    return "low"


class MatchState:
    """Tracks each keeper's workload and the danger facing each goal."""

    def __init__(self, home, away):
        self.teams = [home, away]
        self.keeper_stats = {
            t: {"shots_faced": 0, "on_target": 0, "saves": 0, "goals_conceded": 0,
                "claims": 0, "sweeps": 0, "expected_saves": 0.0}
            for t in self.teams
        }
        self.recent = {t: [] for t in self.teams}  # (time_sec, points) against each team

    def other(self, team):
        return self.teams[1] if team == self.teams[0] else self.teams[0]

    def workload(self, team):
        s = self.keeper_stats[team]
        return s["shots_faced"] + s["claims"] + s["sweeps"]

    def danger_points(self, team, now):
        self.recent[team] = [(t, p) for t, p in self.recent[team] if now - t <= DANGER_WINDOW_SEC]
        return sum(p for _, p in self.recent[team])

    def update(self, event):
        """Feed one event. Returns a dict of insights for it (empty dict for quiet events)."""
        now = event["minute"] * 60 + event["second"]
        etype = event["type"]
        insight = {}

        if etype in DANGER_WEIGHTS:  # attacking events create danger for the OTHER team's goal
            defender = self.other(event["team"])
            self.recent[defender].append((now, DANGER_WEIGHTS[etype]))

        if etype == "shot":
            defender = self.other(event["team"])
            stats = self.keeper_stats[defender]
            if event["outcome"] != "blocked":
                stats["shots_faced"] += 1
            score, factors = saveability(event)
            if score is not None:
                stats["on_target"] += 1
                stats["expected_saves"] += score / 100
                if event["outcome"] == "goal":
                    stats["goals_conceded"] += 1
                else:
                    stats["saves"] += 1
                insight = {
                    "defender": defender,
                    "keeper": event["keeper"],
                    "saveability": score,
                    "verdict": verdict(score),
                    "key_factor": key_factor(factors, score),
                    "factors": factors,
                }
        elif etype == "keeper_claim":
            self.keeper_stats[event["team"]]["claims"] += 1
        elif etype == "keeper_sweep":
            self.keeper_stats[event["team"]]["sweeps"] += 1

        return insight

    def snapshot(self, now):
        """Current workload and danger for both goals."""
        return {
            t: {"workload": self.workload(t),
                "danger": danger_level(self.danger_points(t, now))}
            for t in self.teams
        }

    def keeper_report(self):
        """End-of-match numbers per keeper. 'Goals prevented' compares actual
        saves to the saves the saveability scores say were expected."""
        report = {}
        for team, s in self.keeper_stats.items():
            report[team] = dict(s, goals_prevented=round(s["saves"] - s["expected_saves"], 2),
                                expected_saves=round(s["expected_saves"], 2))
        return report
