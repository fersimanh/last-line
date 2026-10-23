"""Shots, saves, goals, rebounds and the fight for crosses and corners.

This is one part of the engine (see sim_engine.py). Everything here works from the
real positions: who stands in the shooting lane, where the keeper is and how fast he
is moving, who can reach a loose ball first.
"""
import math

import numpy as np

# ---- tuning knobs ----
SHOT_MIN_X, SHOT_MAX_D = 68.0, 31.0          # a shot is considered from here, in the attacking frame
SHOT_BASE, SHOT_W = -2.5, 9.0                # how much a carrier fancies a shot: base + weight * chance
XG_LOGIT = (-1.0, -0.12, 1.6)                # chance of scoring: intercept, per meter, per radian of goal angle
REBOUND_BONUS = 1.6                          # a follow-up shot is almost automatic
BLOCK_P = 0.22                               # chance each defender in the lane blocks a shot
AIM_SIGMA = (2.6, 0.17, 1.7)                 # aiming error: base, per meter, extra under pressure
HELD_SAVE_RATE = 0.55                        # saves the keeper holds; the rest are parried
WIDE_CORNER = 0.30                           # off-target shots that end as corners
CLEAR_CORNER = 0.13                           # cleared crosses put behind for a corner
PARRY_CORNER = 0.40                          # parries pushed out for a corner
BLOCK_CORNER = 0.35                          # blocked shots deflected out for a corner
HEADER_SHOT_P = 0.52                         # an attacker who wins a header at a cross shoots
CLAIM_REACH = 8.0                            # meters: a keeper comes for a cross inside this
AIR_ATT, AIR_DEF, AIR_OUT = 1.0, 1.15, 0.01   # weights in the fight for a corner or a free-kick delivery
KEEPER_AIR = 2.6
SITUATION_BONUS = {"cutback": 0.05, "header_from_cross": 0.0, "one_on_one": 0.13, "two_on_one": 0.20,
                   "rebound": 0.20, "second_ball": 0.0, "open_play": 0.0, "corner": 0.0, "free_kick": 0.0}
SHOT_POW = 0.6                               # below 1: players also shoot from range, not only from six yards
HEADER_PENALTY = 0.0
P_GOAL_BASE = -0.10
PENALTY_GOAL_P = 0.78
NO_ASSIST = ("stoppage", "foul", "card", "offside", "substitution", "goal", "off_ball_run", "keeper_close_down",
             "corner", "free_kick", "penalty")      # these events cannot set up a shot; corners/free kicks are noted separately


def clip(v, lo, hi):
    return max(lo, min(hi, v))


class ShotsMixin:
    def init_shots(self):
        self.last_by_team = [None, None]       # each team's latest event that can set up a shot: (event, ball y, time)
        self.ctx = {"rebound": None, "second": None, "close_down": [None, None], "delivery": [None, None]}

    # ---------- remembering what set a shot up ----------

    def note_event(self, event, team, t):
        """Called for every event: remember the latest one that could set up a shot."""
        if event["type"] not in NO_ASSIST:
            self.last_by_team[team] = (event, float(self.f(team, self.ball)[1]), t)
        elif event["type"] in ("corner", "free_kick"):
            self.last_by_team[team] = (event, float(self.f(team, self.ball)[1]), t)

    def step_to(self, i, spot, limit=2.0):
        """Move player `i` toward `spot` by at most `limit` meters (he reaches for the ball; nobody teleports)."""
        gap = np.asarray(spot, dtype=float) - self.pos[i]
        dist = float(np.linalg.norm(gap))
        if dist > 1e-9:
            self.pos[i] = self.pos[i] + gap / dist * min(dist, limit)

    def window(self, name, team, t):
        """Is a short-lived context (a rebound, a second ball) still open for this team?"""
        w = self.ctx.get(name)
        return w is not None and w["team"] == team and t <= w["until"]

    # ---------- geometry ----------

    def goal_angle(self, me):
        """The angle (radians) the goal fills as seen from a point in the attacking frame."""
        dx = 105.0 - me[0]
        if dx < 0.5:
            return 1.5
        return abs(math.atan2(me[1] - 30.34, dx) - math.atan2(me[1] - 37.66, dx))

    def lane_defenders(self, team, me, extra=()):
        """Opponent outfield players standing inside the triangle between the ball and the two posts."""
        count = 0
        a, b, c = np.array(me, float), np.array([105.0, 30.34]), np.array([105.0, 37.66])
        for i in list(self.outfield(1 - team)) + list(extra):
            p = self.f(team, self.pos[i])
            if p[0] <= me[0] + 0.5:
                continue

            def side(u, v, w):
                return (v[0] - u[0]) * (w[1] - u[1]) - (v[1] - u[1]) * (w[0] - u[0])
            s1, s2, s3 = side(a, b, p), side(b, c, p), side(c, a, p)
            if (s1 >= 0 and s2 >= 0 and s3 >= 0) or (s1 <= 0 and s2 <= 0 and s3 <= 0):
                count += 1
        return count

    def xg_of(self, d, angle, press_m, lanes):
        logit = XG_LOGIT[0] + XG_LOGIT[1] * d + XG_LOGIT[2] * angle - 0.35 * lanes - 0.5 * clip(1 - press_m / 4.0, 0, 1)
        return 1.0 / (1.0 + math.exp(-logit))

    # ---------- deciding to shoot ----------

    def shot_option(self, c, team, me, press_m, t):
        """How much the carrier fancies a shot right now, or None if it is not on."""
        d = math.hypot(105.0 - me[0], 34.0 - me[1])
        if self.slot[c] == "GK" or me[0] < SHOT_MIN_X or d > SHOT_MAX_D:
            return None
        xg = self.xg_of(d, self.goal_angle(me), press_m, self.lane_defenders(team, me))
        xg *= 0.55 + 0.9 * self.shooting[c]
        bonus = REBOUND_BONUS if (self.window("rebound", team, t) or self.window("second", team, t)) else 0.0
        return SHOT_BASE + SHOT_W * xg ** SHOT_POW + bonus

    def classify_situation(self, c, team, t, head, context):
        if context.get("situation"):
            return context["situation"]
        if self.window("rebound", team, t):
            return "rebound"
        if self.window("second", team, t):
            return "second_ball"
        cd = self.ctx["close_down"][1 - team]
        if cd is not None and t - cd["t"] <= 6.0:
            return "one_on_one" if cd["target"] == c else "two_on_one"
        last = self.last_by_team[team]
        if head and last is not None and last[0]["type"] == "cross" and t - last[2] <= 4.0:
            return "header_from_cross"
        if last is not None and last[0]["type"] in ("pass", "cross") and last[0]["x"] >= 98 \
                and abs(last[0]["y"] - 34) > 12 and t - last[2] <= 4.0:
            return "cutback"
        return "open_play"

    # ---------- taking the shot ----------

    def take_shot(self, c, t, press_m, context=None):
        """The carrier shoots. Everything about the shot comes from the state of the game."""
        context = context or {}
        team = int(self.team_of[c])
        opp = 1 - team
        start_abs = context.get("start", self.pos[c]).copy()
        me = self.f(team, start_abs)
        d = math.hypot(105.0 - me[0], 34.0 - me[1])
        gk = self.gk(opp)
        kp = self.f(team, self.pos[gk])
        kv = self.vel[gk] * self.dir[team]
        lanes = self.lane_defenders(team, me, extra=context.get("wall", ()))
        head = bool(context.get("head", False))
        situation = self.classify_situation(c, team, t, head, context)
        skill = self.shooting[c]
        press = clip(1 - press_m / 5.0, 0, 1)
        penalty = situation == "penalty"

        # aim at the side the keeper has left open, with an error that grows with distance and pressure
        side = -1.0 if kp[1] > 34.5 else (1.0 if kp[1] < 33.5 else self.rng.choice([-1.0, 1.0]))
        aim_y = 34.0 + side * self.rng.uniform(1.2, 3.2)
        aim_z = self.rng.uniform(0.8, 2.1) if head else self.rng.uniform(0.25, 2.0)
        sigma = (AIM_SIGMA[0] + AIM_SIGMA[1] * d + AIM_SIGMA[2] * press) * (1.55 - skill)
        if penalty:
            sigma = 0.9
        end_y = aim_y + self.rng.gauss(0, sigma)
        end_z = max(0.1, aim_z + self.rng.gauss(0, 0.6 * sigma))
        on_target = 30.34 + 0.15 <= end_y <= 37.66 - 0.15 and end_z <= 2.44
        wall_n = len(context.get("wall", ()))
        block_p = 0.0 if penalty else 1 - (1 - BLOCK_P) ** lanes
        if wall_n:
            block_p = max(block_p, 0.12 * wall_n)
        blocked = self.rng.random() < block_p
        speed = clip(self.rng.gauss(88 if not head else 62, 11), 45, 128)
        if penalty:
            speed = self.rng.uniform(95, 115)
        deflected = (not blocked) and self.rng.random() < 0.04 * lanes
        swerve = round(self.rng.random(), 2)

        since_keeper = t - self.last_keeper_action[opp] if self.last_keeper_action[opp] > -50 else None
        last = self.last_by_team[team]
        assist_s = (t - last[2]) if last else 99.0
        shift_speed = abs(me[1] - last[1]) / max(assist_s, 0.5) if last else 0.0
        keeper_set = bool(float(np.linalg.norm(kv)) < 1.3 and (since_keeper is None or since_keeper >= 2.5)
                          and shift_speed < 8.0)
        rebound_like = situation in ("rebound",)
        if rebound_like:
            keeper_set = False

        outcome, goal = "off_target", False
        if blocked:
            outcome = "blocked"
        elif on_target:
            placement = 0.5 * abs(end_y - 34) / 3.66 + 0.5 * end_z / 2.44
            reach_gap = abs(end_y - kp[1])
            p_goal = (P_GOAL_BASE + 0.34 * placement + 0.0030 * (speed - 80) + 0.012 * max(0.0, 24 - d)
                      + 0.22 * clip((reach_gap - 1.2) / 3.0, 0, 1) + (0.0 if keeper_set else 0.07)
                      + SITUATION_BONUS.get(situation, 0.0))
            if head:
                p_goal -= HEADER_PENALTY                                  # headers are harder to place
            p_goal = PENALTY_GOAL_P if penalty else clip(p_goal, 0.03, 0.88)
            goal = self.rng.random() < p_goal
            outcome = "goal" if goal else "saved"

        fields = dict(outcome=outcome, distance_m=round(d, 1), speed_kmh=int(round(speed)),
                      body_part="head" if head else "foot", keeper=self.names[gk],
                      keeper_x=round(float(kp[0]), 1), keeper_y=round(float(kp[1]), 1),
                      defenders_in_lane=int(min(lanes, 3)), deflected=bool(deflected), swerve=swerve,
                      keeper_set=keeper_set, situation=situation,
                      assist_id=last[0]["_k"] if last else None, assist_type=last[0]["type"] if last else "dribble",
                      assist_seconds=int(round(assist_s)) if last else 0,
                      ball_shift_m=round(abs(me[1] - last[1]), 1) if last else 0.0,
                      seconds_since_keeper_action=None if since_keeper is None else int(round(since_keeper)))
        if outcome != "blocked":
            fields.update(end_y=round(float(end_y), 2), end_z=round(float(end_z), 2))
        event = self.emit(t, "shot", team, c, team, start_abs, **fields)
        if context.get("on_shot"):
            context["on_shot"](event)
        self.ctx["rebound"] = self.ctx["second"] = None

        # the ball travels; the outcome is applied when it arrives
        if outcome == "blocked":
            end = start_abs + (self.f(team, [105.0, 34.0]) - start_abs) / (d + 1e-9) * min(d * 0.3, 6.0)
        else:
            end = self.f(team, np.array([105.0, clip(float(end_y), 25.0, 43.0)]))
        duration = max(0.5, float(np.linalg.norm(end - start_abs)) / (speed / 3.6))
        self.flight = {"start": start_abs, "end": end, "t0": t, "t1": t + duration, "kind": "shot", "passer": c,
                       "receiver": None, "interceptor": None, "team": team, "waited": 0.0, "ptype": "shot",
                       "event": event, "resolve": self.land_shot, "success": None, "last_team": team,
                       "dive": gk if outcome in ("saved", "goal") else None, "shot": {"outcome": outcome, "end_z": end_z}}
        self.carrier = -1
        self.carry = None

    def land_shot(self, t, fl):
        team, opp = fl["team"], 1 - fl["team"]
        event, outcome = fl["event"], fl["shot"]["outcome"]
        shooter = fl["passer"]
        if outcome == "goal":
            self.goal_scored(t, team, shooter, event)                 # sim_stops
        elif outcome == "saved":
            gk = self.gk(opp)
            held = self.rng.random() < HELD_SAVE_RATE
            self.emit(t, "keeper_save", opp, gk, team, self.pos[gk], related_to=event["_k"],
                      end_z=round(float(fl["shot"]["end_z"]), 2), held=bool(held))
            self.last_keeper_action[opp] = t
            if held:
                self.give_ball(gk, t, wait=self.rng.uniform(1.5, 4.0), trigger="after_save")
            elif self.rng.random() < PARRY_CORNER:
                self.ball_out(t, opp, self.f(team, np.array([105.0, 34.0 + self.rng.uniform(-6, 6)])))
            else:
                kt = self.f(team, self.pos[gk])                    # the keeper, in the attackers' frame
                spot = self.f(team, np.array([kt[0] - self.rng.uniform(3, 7), kt[1] + self.rng.uniform(-4, 4)]))
                self.loose_ball(t, spot, shooter_team=team, kind="parry", window=("rebound", event))
        elif outcome == "blocked":
            if self.rng.random() < BLOCK_CORNER:
                self.ball_out(t, opp, self.f(team, np.array([105.0, 34.0 + self.rng.uniform(-10, 10)])))
            else:
                self.loose_ball(t, fl["end"], shooter_team=team, kind="block", window=("second", event))
        else:                                                         # off target: over the bar or wide
            if self.rng.random() < WIDE_CORNER:                       # a last touch by a defender sends it behind: a corner
                self.ball_out(t, 1 - team, fl["end"])
            else:
                self.ball_out(t, team, fl["end"])

    # ---------- a ball that is loose: who gets it first? ----------

    def loose_ball(self, t, spot, shooter_team, kind, window=None):
        """After a parry or a block the ball is loose at `spot`. The player who can get there
        first wins it; the attackers get a short window to shoot again if they do."""
        spot = np.array([clip(spot[0], 1.0, 104.0), clip(spot[1], 1.0, 67.0)])
        best = None
        for i in range(22):
            if not self.active[i] or np.linalg.norm(self.pos[i] - spot) > 25:
                continue
            reach = 0.35 + float(np.linalg.norm(self.pos[i] - spot)) / (self.vmax[i] * 0.9) + self.rng.uniform(0, 0.5)
            if best is None or reach < best[0]:
                best = (reach, i)
        if best is None:
            self.ball_out(t, shooter_team, spot)
            return
        reach, winner = best
        start = self.ball.copy()
        self.flight = {"start": start, "end": spot, "t0": t, "t1": t + max(0.8, reach), "kind": "loose",
                       "passer": None, "receiver": None, "interceptor": winner, "team": shooter_team, "waited": 0.0,
                       "ptype": "loose", "event": None, "resolve": self.land_loose, "success": None,
                       "last_team": shooter_team, "window": window, "reason": kind}
        self.carrier = -1
        self.carry = None

    def land_loose(self, t, fl):
        winner = fl["interceptor"]
        team = int(self.team_of[winner])
        shooter_team = fl["team"]
        if team == shooter_team:                                      # the attackers get it back
            self.give_ball(winner, t, wait=self.rng.uniform(0.3, 1.0))
            if fl["window"]:
                name, ev = fl["window"]
                self.ctx[name] = {"team": team, "until": t + 3.5, "shot": ev["_k"]}
        elif self.slot[winner] == "GK":                               # the keeper gets his hands on it
            self.emit(t, "keeper_claim", team, winner, shooter_team, self.pos[winner])
            self.last_keeper_action[team] = t
            self.give_ball(winner, t, wait=self.rng.uniform(1.5, 4.0), trigger="after_claim")
        else:
            self.won_ball(winner, t, "possession_change", loser=shooter_team, reason="clearance")

    # ---------- crosses, corners and free-kick deliveries ----------

    def resolve_cross(self, t, fl):
        """A cross arrives. If it found a team-mate, an attacker wins the header or the
        control; if not, the keeper, a defender or the end line wins it."""
        team = fl["team"]
        if fl["kind"] == "out":
            self.ball_out(t, team, fl["end"])
        elif fl["kind"] == "offside":
            self.call_offside(t, fl)
        elif fl["success"]:
            self.attacker_wins_air(t, fl["receiver"], fl["event"], "header_from_cross")
        else:
            self.defence_wins_air(t, team, fl["end"], fl["event"])

    def attacker_wins_air(self, t, winner, delivery_event, situation):
        """An attacker gets to the ball first: most often he heads it at goal."""
        if winner is None or not self.active[winner]:
            return
        team = int(self.team_of[winner])
        if self.rng.random() < HEADER_SHOT_P:
            self.step_to(winner, self.ball)
            self.take_shot(winner, t, 3.0, {"head": True, "situation": situation if situation != "header_from_cross" else None})
        else:
            self.give_ball(winner, t, wait=self.rng.uniform(0.6, 1.6))
        if delivery_event is not None and "outcome" in delivery_event and delivery_event["outcome"] is None:
            delivery_event["outcome"] = "header_shot" if self.flight and self.flight.get("kind") == "shot" else "controlled"

    def defence_wins_air(self, t, att_team, spot, delivery_event=None, allow_keeper=True):
        """The defence deals with a ball into the box: the keeper claims or punches it, or a defender clears."""
        opp = 1 - att_team
        gk = self.gk(opp)
        kdist = float(np.linalg.norm(self.pos[gk] - spot))
        inside = self.in_own_box(opp, spot)
        if allow_keeper and inside and kdist <= CLAIM_REACH and self.active[gk] \
                and self.rng.random() < clip(1.15 - kdist / 9.0, 0.15, 0.95):
            if self.rng.random() < 0.65:
                self.emit(t, "keeper_claim", opp, gk, att_team, self.pos[gk])
                self.last_keeper_action[opp] = t
                self.give_ball(gk, t, wait=self.rng.uniform(1.5, 4.0), trigger="after_claim")
                result = "claimed"
            else:
                self.emit(t, "keeper_punch", opp, gk, att_team, self.pos[gk])
                self.last_keeper_action[opp] = t
                away = self.f(att_team, np.array([self.f(att_team, self.pos[gk])[0] - self.rng.uniform(8, 14),
                                                 34.0 + self.rng.uniform(-14, 14)]))
                self.loose_ball(t, away, shooter_team=att_team, kind="punch")
                result = "punched"
        else:
            defenders = self.outfield(opp)
            winner = min(defenders, key=lambda i: np.linalg.norm(self.pos[i] - spot))
            self.step_to(winner, spot)
            spot = self.pos[winner].copy()
            self.emit(t, "possession_change", opp, winner, att_team, spot, reason="clearance")
            self.carrier, self.poss, self.carry, self.runs = winner, opp, None, {}
            self.flight = None
            self.ball = self.pos[winner].copy()
            if self.rng.random() < CLEAR_CORNER:                           # headed behind: another corner
                self.carrier = -1
                self.ball_out(t, opp, self.f(att_team, np.array([105.0, 34.0 + self.rng.choice([-1, 1]) * 12.0])))
            else:
                self.next_decision = t + self.rng.uniform(0.6, 1.4)
            result = "cleared"
        if delivery_event is not None and delivery_event.get("outcome") is None:
            delivery_event["outcome"] = result

    def deliver_box(self, t, taker, event, source, decision):
        """A corner or a wide free kick is whipped into the box; resolved when it lands."""
        team = int(self.team_of[taker])
        spot = self.ball.copy()
        zone = event["target_zone"]
        zx = {"near_post": 98.0, "penalty_spot": 94.0, "far_post": 97.0}[zone]
        zy = {"near_post": 34.0 + 4.5, "penalty_spot": 34.0 + self.rng.uniform(-2, 2), "far_post": 34.0 - 9.0}[zone]
        side = 1.0 if self.f(team, spot)[1] > 34 else -1.0
        land_team = np.array([zx + self.rng.uniform(-1.5, 1.5), 34.0 + side * (zy - 34.0) + self.rng.uniform(-1.5, 1.5)])
        end = self.f(team, land_team)
        duration = max(1.0, float(np.linalg.norm(end - spot)) / 18.0)
        self.flight = {"start": spot, "end": end, "t0": t, "t1": t + duration, "kind": "delivery", "passer": taker,
                       "receiver": None, "interceptor": None, "team": team, "waited": 0.0, "ptype": "cross",
                       "event": event, "resolve": self.resolve_delivery, "success": None, "last_team": team,
                       "source": source, "decision": decision}
        self.carrier = -1
        self.carry = None

    def resolve_delivery(self, t, fl):
        """The fight for a corner or a free-kick delivery, decided by who is near the landing spot."""
        team, opp = fl["team"], 1 - fl["team"]
        spot, event, decision = fl["end"], fl["event"], fl["decision"]
        attackers = [i for i in self.outfield(team) if np.linalg.norm(self.pos[i] - spot) < 7.0]
        defenders = [i for i in self.outfield(opp) if np.linalg.norm(self.pos[i] - spot) < 7.0]
        gk = self.gk(opp)
        att_w = {i: AIR_ATT / (1 + np.linalg.norm(self.pos[i] - spot)) * (0.6 + 0.7 * self.role_air(i)) for i in attackers}
        def_w = {i: AIR_DEF / (1 + np.linalg.norm(self.pos[i] - spot)) * (0.6 + 0.7 * self.role_air(i)) for i in defenders}
        a_total, d_total = sum(att_w.values()), sum(def_w.values())
        if decision in ("miss", "stay"):
            k_total = 0.0
            if decision == "miss":
                a_total *= 1.6                                         # the keeper came and missed: the attackers profit
        else:
            k_total = KEEPER_AIR if float(np.linalg.norm(self.pos[gk] - spot)) <= CLAIM_REACH + 2 else 0.0
        out = AIR_OUT * (a_total + d_total + k_total + 0.3)
        who = self.rng.choices(["attacker", "defender", "keeper", "out"], weights=[a_total + 1e-6, d_total + 1e-6, k_total + 1e-6, out])[0]
        if who == "attacker" and att_w:
            winner = self.rng.choices(list(att_w), weights=list(att_w.values()))[0]
            self.attacker_wins_air(t, winner, event, "corner" if fl["source"] == "corner" else "free_kick")
            if event.get("outcome") is None:
                event["outcome"] = "controlled"
        elif who == "keeper":
            self.defence_wins_air(t, team, spot, event)
        elif who == "defender" and def_w:
            self.defence_wins_air(t, team, spot, None, allow_keeper=False)
            event["outcome"] = "cleared"
        else:
            self.ball_out(t, team, spot)
            event["outcome"] = "out"

    def role_air(self, i):
        """How good a player is in the air (0 to 1), by role."""
        return {"CB": 0.9, "ST": 0.85, "DM": 0.55, "CM": 0.5, "FB": 0.4, "W": 0.35, "GK": 0.6}[self.role[i]]
