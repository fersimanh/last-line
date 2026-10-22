"""Scoring and live match state for Last Line.

saveability(shot) rates how saveable an on-target shot was, 0-100:
  100 = a routine stop, 0 = nearly unstoppable.
It is a transparent formula (not machine learning) so the Foundry agents
can explain exactly which factors drove it.
"""

import math

SPREAD = 1.7            # how far to stretch scores away from the center
CENTER = 60              # the raw score that maps to a score of 50: the average raw
                         # score with these weights, so a typical shot lands near 50
GOAL_HALF_WIDTH = 3.66   # meters (goal is 7.32 m wide)
GOAL_HEIGHT = 2.44       # meters

# Assumptions behind the reaction-time factor
KEEPER_DELAY_SEC = 0.25  # time for the keeper to read the shot and start moving
KEEPER_DIVE_MS = 4.5     # sideways speed of a dive, meters per second

# How much each factor counts toward the score (adds up to 1.0)
WEIGHTS = {
    "placement": 0.18,    # where the ball crosses the line
    "reaction": 0.16,     # time the ball gives the keeper vs time the keeper needs
    "distance": 0.12,     # how far the shot was struck from
    "speed": 0.12,        # how hard it was struck
    "reach": 0.10,        # how far the keeper was from where the ball ended up
    "angle": 0.08,        # how wide of the goal's center line it was struck from
    "no_deflection": 0.06,  # a deflection takes away reaction time
    "lane": 0.05,         # defenders standing between the ball and the keeper
    "depth": 0.04,        # keeper's distance off the goal line vs the ideal for this shot
    "swerve": 0.04,       # late movement in the air
    "keeper_set": 0.04,   # keeper balanced and ready, or caught moving
    "foot_strike": 0.01,  # headers are harder to read than foot strikes
}

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
    miss_m = abs(shot["end_y"] - shot["keeper_y"])  # sideways distance the keeper must cover
    reach = 1 - clamp(miss_m / 3.5)

    # Reaction: seconds the ball takes to arrive vs seconds the keeper needs
    # (reading the shot, then diving sideways). A ratio of 2 or more is easy.
    flight_sec = shot["distance_m"] / (shot["speed_kmh"] / 3.6)
    needed_sec = KEEPER_DELAY_SEC + miss_m / KEEPER_DIVE_MS
    reaction = clamp(flight_sec / needed_sec / 2)

    # Angle: a shot from wide of the goal's center line is harder to cover
    angle_deg = math.degrees(math.atan2(abs(shot["y"] - 34), 105 - shot["x"]))
    angle = 1 - clamp(angle_deg / 60)

    # Depth: the ideal spot off the line is further out against longer shots
    depth_m = 105 - shot["keeper_x"]
    depth = 1 - clamp(abs(depth_m - (1 + shot["distance_m"] / 15)) / 2.5)

    factors = {
        "placement": placement,
        "reaction": reaction,
        "distance": distance,
        "speed": speed,
        "reach": reach,
        "angle": angle,
        "no_deflection": 0.0 if shot["deflected"] else 1.0,
        "lane": 1 - shot["defenders_in_lane"] / 3,
        "depth": depth,
        "swerve": 1 - shot["swerve"],
        "keeper_set": 1.0 if shot["keeper_set"] else 0.0,
        "foot_strike": 0.0 if shot["body_part"] == "head" else 1.0,
    }
    raw = 100 * sum(WEIGHTS[name] * value for name, value in factors.items())
    # Averaging many factors bunches scores near the middle, so stretch them
    # around the center. This spreads verdicts roughly 25% / 50% / 25%.
    score = clamp(50 + SPREAD * (raw - CENTER), 0, 100)
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
    "placement": "it was placed high or wide, away from the keeper's body",
    "reach": "the keeper was caught far from the ball's path",
    "reaction": "the keeper had very little time to react",
    "angle": "it was struck from a wide angle",
    "no_deflection": "it took a deflection",
    "lane": "defenders blocked the keeper's view",
    "depth": "the keeper was off the ideal depth for this shot",
    "swerve": "it moved late in the air",
    "keeper_set": "the keeper was caught moving",
    "foot_strike": "it was a header",
}
EASY_REASONS = {
    "distance": "it came from long range",
    "speed": "it was struck at only moderate pace",
    "placement": "it was hit close to the keeper's body",
    "reach": "the keeper was well positioned",
    "reaction": "the keeper had plenty of time to react",
    "angle": "it was struck from straight on",
    "no_deflection": "it was a clean strike",
    "lane": "the keeper had a clear view",
    "depth": "the keeper stood at the ideal depth",
    "swerve": "it flew straight",
    "keeper_set": "the keeper was set and ready",
    "foot_strike": "it was a foot strike",
}


def key_factor(factors, score):
    """Name the factor that best explains the verdict: what made an easy
    save easy, or what made a hard shot hard. Factors are ranked by weight, so
    a heavy factor beats a trivial one (a clean strike is not much of a reason)."""
    if score >= 65:
        best = max(factors, key=lambda name: WEIGHTS[name] * factors[name])
        return EASY_REASONS[best]
    worst = max(factors, key=lambda name: WEIGHTS[name] * (1 - factors[name]))
    return HARD_REASONS[worst]


def danger_level(points):
    if points >= 12:
        return "high"
    if points >= 6:
        return "medium"
    return "low"


# ---------- Distribution: how the keeper gives the ball away ----------
# These rules are shared with generate_match.py, so the decision score judges
# the keeper with the same numbers the simulation used.

HANDS_TRIGGERS = ("after_save", "after_claim")  # the keeper holds the ball in their hands
PRESSURE_LEVEL = {"low": 0.0, "medium": 0.5, "high": 1.0}
LONG_PASS_M = 32  # feet passes longer than this are kicked
SUCCESS = ("completed", "contested_won")  # outcomes where the keeper's team keeps the ball

# Chance a pass reaches a teammate before distance, pressure and openness
BASE_SUCCESS = {"roll": 0.95, "throw": 0.92, "ground_pass": 0.90, "kick": 0.56}


def pick_method(trigger, distance_m):
    """How a keeper plays a pass of this length. Throws and rolls only when the
    keeper holds the ball (after a save or claim); a back pass must be played
    with the feet."""
    if trigger in HANDS_TRIGGERS:
        if distance_m <= 15:
            return "roll"
        if distance_m <= 30:
            return "throw"
        return "kick"
    return "ground_pass" if distance_m <= LONG_PASS_M else "kick"


def pass_success_prob(method, distance_m, open_m, pressure):
    """Chance (0-1) that a pass reaches its target."""
    p = BASE_SUCCESS[method]
    if method == "kick":
        p -= 0.003 * max(0, distance_m - 40)   # longer kicks are harder to land
        p -= 0.04 * PRESSURE_LEVEL[pressure]   # a rushed kick is a little less accurate
        p += 0.02 * (open_m - 4)               # a free receiver wins more headers
    else:
        p -= 0.004 * max(0, distance_m - 12)   # longer short passes give time to intercept
        p -= 0.20 * PRESSURE_LEVEL[pressure]   # pressing forwards cut out short passes
        p += 0.015 * (open_m - 5)              # a free receiver is easy to find
    return clamp(p, 0.15, 0.98)


def option_value(trigger, option, pressure, keeper_x):
    """How good one passing option is: the chance it works times how far it
    moves the team forward, minus the cost of losing the ball. Losing it close
    to your own goal (target under 40 m) costs much more than losing it far away."""
    method = pick_method(trigger, option["distance_m"])
    p = pass_success_prob(method, option["distance_m"], option["open_m"], pressure)
    gain = option["x"] - keeper_x
    loss_cost = 1.0 if option["x"] < 40 else 0.4
    return p * (1 + gain / 80) - (1 - p) * loss_cost


# Outcome points for the quality score
OUTCOME_POINTS = {"completed": 100, "contested_won": 80, "contested_lost": 25, "intercepted": 0}
METHOD_DIFFICULTY = {"roll": 0.0, "throw": 0.2, "ground_pass": 0.3, "kick": 0.8}

REASON_TEXT = {
    "free_man": "found the free teammate",
    "relieve_press": "played out calmly under pressure",
    "break_press_long": "went long over the press",
    "switch_play": "switched the play to the other side",
    "safe_retention": "kept the ball safely",
    "quick_counter": "released it fast to start a counter",
}


def distribution_insight(event):
    """Rate one keeper_distribution event. Every score runs 0-100."""
    pressure = event["pressure"]
    success = event["outcome"] in SUCCESS
    target = next(o for o in event["options"] if o["player"] == event["target_player"])

    # Difficulty: long passes, pressure, kicks and tightly marked receivers are harder
    difficulty = 100 * (0.35 * clamp(event["distance_m"] / 70)
                        + 0.30 * PRESSURE_LEVEL[pressure]
                        + 0.20 * METHOD_DIFFICULTY[event["method"]]
                        + 0.15 * (1 - clamp(target["open_m"] / 12)))

    # Decision: the chosen option's value against the best option on offer.
    # Each 0.005 of value given up costs 1 point; choosing the best scores 100.
    values = {o["player"]: option_value(event["trigger"], o, pressure, event["x"])
              for o in event["options"]}
    best_player = max(values, key=values.get)
    decision = 100 * clamp(1 - (values[best_player] - values[event["target_player"]]) / 0.5)

    # Quality: decision 40%, outcome 30%, difficulty 30%. Difficulty only counts
    # when the pass worked: a hard pass that comes off deserves credit, a hard
    # pass that fails does not.
    quality = (0.40 * decision + 0.30 * OUTCOME_POINTS[event["outcome"]]
               + 0.30 * (difficulty if success else 0))

    if not success:
        dist_verdict = "turnover"
    elif quality >= 80:
        dist_verdict = "excellent"
    elif decision < 60 or difficulty >= 60:
        dist_verdict = "risky"
    else:
        dist_verdict = "safe"

    best = next(o for o in event["options"] if o["player"] == best_player)
    if not success and pressure == "high":
        factor = "the press closed in before the pass got away"
    elif decision < 60:
        factor = f"a better option was on: the {best['role']} {best['player']}"
    elif not success:
        factor = "the receiver was too closely marked"
    else:
        factor = REASON_TEXT[event["reason"]]

    return {
        "difficulty": round(difficulty),
        "decision_score": round(decision),
        "quality": round(quality),
        "verdict": dist_verdict,
        "key_factor": factor,
        "best_option": best_player,
    }


class MatchState:
    """Tracks each keeper's workload and the danger facing each goal."""

    def __init__(self, home, away):
        self.teams = [home, away]
        self.keeper_stats = {
            t: {"shots_faced": 0, "on_target": 0, "saves": 0, "goals_conceded": 0,
                "claims": 0, "sweeps": 0, "expected_saves": 0.0,
                # distribution
                "distributions": 0, "completed": 0, "progressive_m": 0.0,
                "pressure_completions": 0, "led_to_shot": 0,
                "long_attempts": 0, "long_completed": 0, "decision_total": 0}
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
                    "type": "shot",
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
        elif etype == "keeper_distribution":
            stats = self.keeper_stats[event["team"]]
            rating = distribution_insight(event)
            completed = event["outcome"] in SUCCESS
            long_ball = event["method"] == "kick"
            stats["distributions"] += 1
            stats["decision_total"] += rating["decision_score"]
            stats["long_attempts"] += long_ball
            if completed:
                stats["completed"] += 1
                stats["long_completed"] += long_ball
                stats["progressive_m"] += max(0.0, event["x_gain_m"])  # forward meters only
                stats["pressure_completions"] += event["pressure"] == "high"
            stats["led_to_shot"] += event["led_to_shot"]
            insight = dict(rating, type="distribution", keeper=event["player"], team=event["team"])

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
            n = s["distributions"]
            row = dict(s, goals_prevented=round(s["saves"] - s["expected_saves"], 2),
                       expected_saves=round(s["expected_saves"], 2),
                       progressive_m=round(s["progressive_m"], 1),
                       distribution_completion_pct=round(100 * s["completed"] / n, 1) if n else 0.0,
                       long_ball_pct=round(100 * s["long_attempts"] / n, 1) if n else 0.0,
                       avg_decision_score=round(s["decision_total"] / n, 1) if n else 0.0,
                       attacks_started=s["led_to_shot"])
            del row["decision_total"]  # only needed for the average
            report[team] = row
        return report
