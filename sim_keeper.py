"""The goalkeeper in possession: rushing out, goal kicks, back passes, distribution.

One part of the engine (see sim_engine.py). When the keeper has the ball (after a
save, a claim, a goal kick or a back pass) he chooses among a few visible team-mates
and plays it. The decision keeps every field the app already reads from a
keeper_distribution event: trigger, method, technique, options, pressure, reason...
"""
import numpy as np

import vision
from scoring import option_value, pick_method

BEST_OPTION_RATE = 0.70    # how often the keeper picks the best visible option
GOAL_KICK_LONG = (0.12, 0.75)   # chance a goal kick goes long: base + directness * slope
CLOSE_DOWN_P = 0.25        # a lone attacker through on goal: how often the keeper comes out
LONG_PASS_M = 32.0


def clip(v, lo, hi):
    return max(lo, min(hi, v))


def pick_technique(trigger, method, distance_m, rng):
    if method == "throw":
        return "overarm" if distance_m > 20 else "sidearm"
    if method == "roll":
        return "bowled"
    if method == "ground_pass":
        return "pass_out_from_back" if trigger in ("goal_kick", "back_pass") else "side_foot"
    if trigger == "goal_kick":                       # kicks
        return "goal_kick_long"
    if trigger == "back_pass":
        return "driven_low" if distance_m < 45 else "lofted"
    return rng.choice(["drop_kick", "volley"])       # from the hands


def pick_reason(trigger, method, pressure, target, keeper_y):
    """Why the keeper chose this pass, from the situation."""
    if trigger in ("after_save", "after_claim") and target["x"] > 40 and pressure == "low":
        return "quick_counter"
    if method == "kick" and pressure != "low":
        return "break_press_long"
    if abs(target["y"] - keeper_y) > 22:
        return "switch_play"
    if pressure != "low":
        return "relieve_press"
    if target["open_m"] >= 8:
        return "free_man"
    return "safe_retention"


def direction_of(dx, dy):
    if dx < -2:
        return "backward"
    if abs(dy) > dx:
        return "lateral"
    return "forward"


class KeeperMixin:
    def init_keeper(self):
        self.keeper_trigger = "back_pass"       # why the keeper has the ball
        self.keeper_since = 0.0
        self.keeper_out = [None, None]          # while a keeper rushes out: {"until", "target"}
        self.last_keeper_action = [-99.0, -99.0]  # when each keeper last did something (a save, a claim, a pass...)

    # ---------- coming off the line ----------

    def keeper_targets(self, tgt, urgency, t):
        """A keeper who has decided to close down an attacker heads out toward him."""
        for team in (0, 1):
            out = self.keeper_out[team]
            if out is None or t >= out["until"]:
                continue
            g = self.gk(team)
            attacker = self.f(team, self.pos[out["target"]])          # in the keeper's own frame
            spot = np.array([clip(attacker[0] - 9.0, 3.0, 14.0), 34.0 + 0.6 * (attacker[1] - 34.0)])
            tgt[g], urgency[g] = self.f(team, spot), 1.0

    def maybe_close_down(self, c, team, me, t):
        """An attacker is through on goal with nobody between him and the keeper: the keeper may rush out."""
        opp = 1 - team
        g = self.gk(opp)
        out = self.keeper_out[opp]
        if (out is not None and t < out["until"]) or not self.active[g]:
            return
        if me[0] < 80 or abs(me[1] - 34) > 24:
            return
        for i in self.outfield(opp):                                   # a defender goal-side: not a lone attacker
            p = self.f(team, self.pos[i])
            if p[0] > me[0] - 1 and abs(p[1] - me[1]) < 7:
                return
        if self.rng.random() > CLOSE_DOWN_P:
            return
        self.emit(t, "keeper_close_down", opp, g, team, self.pos[g], target_player=self.names[c])
        self.keeper_out[opp] = {"until": t + 5.0, "target": c}
        self.ctx["close_down"][opp] = {"t": t, "target": c}
        self.last_keeper_action[opp] = t

    def after_launch(self, c, team, t):
        if self.slot[c] == "GK":
            self.last_keeper_action[team] = t

    def keeper_wins_ball(self, t, fl, etype):
        """The keeper gets to a through ball or a loose ball first."""
        g = fl["interceptor"]
        keeper_team = int(self.team_of[g])
        self.emit(t, etype, keeper_team, g, fl["team"], fl["end"])
        self.last_keeper_action[keeper_team] = t
        self.give_ball(g, t, wait=self.rng.uniform(1.0, 3.0), trigger="back_pass")

    # ---------- playing the ball ----------

    def keeper_play(self, t):
        """The keeper chooses a team-mate and plays the ball: a goal kick, a throw after a save,
        a pass back to a defender..."""
        g = self.carrier
        team = int(self.team_of[g])
        opp = 1 - team
        trigger = self.keeper_trigger or "back_pass"
        me = self.f(team, self.pos[g])
        mates = self.outfield(team)
        opponents = self.outfield(opp)
        P = self.f(team, self.pos[mates])
        O = self.f(team, self.pos[opponents])
        gaps = np.linalg.norm(O - me, axis=1)
        close = int((gaps < 10.0).sum())                                 # opponents close to the keeper
        pressure = "low" if close == 0 else "medium" if close == 1 else "high"
        press_m = float(gaps.min())
        tac = self.tac[team]

        # 2-4 options: always the nearest team-mate (the safe one), then others, long ones favored by direct teams
        dist = np.linalg.norm(P - me, axis=1)
        order = [int(k) for k in np.argsort(dist)]
        chosen = [order[0]]
        pool = order[1:]
        for _ in range(min(self.rng.randint(1, 3), len(pool))):
            w = [1.0 + 3.0 * tac["directness"] * (dist[k] > 35) + 2.0 * (1 - tac["directness"]) * (dist[k] <= 32)
                 for k in pool]
            k = self.rng.choices(pool, weights=w)[0]
            chosen.append(k)
            pool.remove(k)
        long_kick = trigger == "goal_kick" and self.rng.random() < GOAL_KICK_LONG[0] + GOAL_KICK_LONG[1] * tac["directness"]
        if long_kick:                                                    # a direct goal kick: add the most advanced team-mates
            for k in sorted(range(len(mates)), key=lambda k: -P[k][0])[:2]:
                if k not in chosen:
                    chosen.append(k)
        blockers = [tuple(p) for p in O]
        facing = vision.facing_angle(tuple(me), (52.5, 34.0))
        options = []
        for k in chosen:
            px, py = float(P[k][0]), float(P[k][1])
            options.append({"player": self.names[mates[k]], "role": self.role[mates[k]], "x": round(px, 1),
                            "y": round(py, 1), "distance_m": round(float(dist[k]), 1),
                            "open_m": round(float(np.linalg.norm(O - P[k], axis=1).min()), 1),
                            "visible": bool(vision.is_visible(tuple(me), facing, (px, py), blockers=blockers))})
        if long_kick:                                                    # a keeper lining up a long kick picks his man out
            for o in options:
                o["visible"] = o["visible"] or o["x"] >= 55
        if not any(o["visible"] for o in options):                       # nothing in view: the nearest is always visible
            min(options, key=lambda o: o["distance_m"])["visible"] = True
        seen = [o for o in options if o["visible"]]
        values = [option_value(trigger, o, pressure, me[0]) for o in seen]
        best = seen[values.index(max(values))]
        far = [o for o in seen if o["x"] >= 55]
        if long_kick and far:
            best = max(far, key=lambda o: option_value(trigger, o, pressure, me[0]))
            target = best
        elif self.rng.random() < BEST_OPTION_RATE or len(seen) == 1:
            target = best
        else:
            target = self.rng.choice([o for o in seen if o is not best])
        j = mates[[self.names[m] for m in mates].index(target["player"])]

        d = target["distance_m"]
        method = pick_method(trigger, d)
        ptype = "long" if method == "kick" else "short"
        target_xy = np.array([target["x"], target["y"]])
        risk = self.cut_risk(me, target_xy, d / 22.0 if method == "kick" else d / 13.0, O, self.vmax[opponents])
        p = self.p_success(ptype, d, press_m, target["open_m"], risk, self.passing[g])
        fields = dict(kind="long" if method == "kick" else "short", trigger=trigger, method=method,
                      technique=pick_technique(trigger, method, d, self.rng), target_player=target["player"],
                      target_role=target["role"], target_x=target["x"], target_y=target["y"], distance_m=d,
                      direction=direction_of(target["x"] - me[0], target["y"] - me[1]), pressure=pressure,
                      opponents_close=close, options=options,
                      reason=pick_reason(trigger, method, pressure, target, me[1]), outcome=None,
                      x_gain_m=round(target["x"] - float(me[0]), 1), led_to_shot=False, shot_id=None)
        self.keeper_trigger = None
        self.launch(g, j, ptype, p, risk, press_m, t, etype="keeper_distribution", fields=fields)

    def finish_distribution(self, t, fl):
        """Record how a distribution ended (completed, intercepted, or an aerial duel)."""
        event, kick = fl["event"], fl["event"]["method"] == "kick"
        if fl["kind"] == "completed":
            event["outcome"] = "contested_won" if kick and self.rng.random() < 0.6 else "completed"
        elif fl["kind"] == "contested":
            event["outcome"] = "contested_lost" if kick and self.rng.random() < 0.6 else "intercepted"
        else:
            event["outcome"] = "intercepted"                           # intercepted, out of play, or offside: lost

    def mark_led_to_shot(self, events):
        """A completed distribution `led to a shot` if the same team shoots within 30 seconds
        without the other team touching the ball first."""
        for i, d in enumerate(events):
            if d["type"] != "keeper_distribution" or d["outcome"] not in ("completed", "contested_won"):
                continue
            for later in events[i + 1:]:
                if later["t"] - d["t"] > 30 or later["team"] != d["team"]:
                    break
                if later["type"] == "shot":
                    d["led_to_shot"], d["shot_id"] = True, later["id"]
                    break
