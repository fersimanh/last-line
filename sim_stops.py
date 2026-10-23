"""Stoppages and set pieces: throw-ins, goal kicks, corners, fouls, cards, free kicks,
offsides, penalties, goals, substitutions, injuries, half time and added time.

One part of the engine (see sim_engine.py). Every dead ball is a `stoppage` event with a
reason and a duration; the players then WALK to their set-piece positions in the tracking
(a wall for a free kick, the box filling up for a corner) before the restart.
"""
import math

import numpy as np

import formations as F
from matchclock import display_clock

PITCH_L, PITCH_W = F.PITCH_L, F.PITCH_W
HALF_SEC = 2700.0
BOX_X, BOX_Y0, BOX_Y1 = 88.5, 13.84, 54.16
PARK = np.array([52.5, -2.5])

# ---- tuning knobs ----
DUR = {"throw_in": (7, 15), "goal_kick": (13, 28), "corner": (20, 38), "free_kick": (17, 36), "offside": (9, 18),
       "penalty": (60, 85), "goal": (36, 56), "injury": (40, 110), "substitution": (28, 48), "pause": (10, 20)}
PENALTY_CALL = 0.22              # of fouls inside the box, how many are given as penalties
FOUL_RATE = 0.050                 # chance per second of a foul when a defender challenges the ball carrier
YELLOW_P, RED_P = 0.22, 0.0006   # per foul: a yellow card, a straight red
OFFSIDE_CALL = 0.50              # of passes to a player in an offside position, how many are flagged
INJURY_RATE = 0.00035            # per second of live play
ADDED_FACTOR, ADDED_NOISE = 0.95, (-20.0, 40.0)   # added time = factor * countable stoppage time + noise (seconds)
FREE_KICK_SHOT_P = 0.70          # of free kicks within range, how many are shot at goal
LOST_COUNTED = {"goal": 45.0, "penalty": 60.0, "card": 25.0, "substitution": 30.0, "goal_kick": 4.0, "foul": 3.0}


def clip(v, lo, hi):
    return max(lo, min(hi, v))


class StopsMixin:
    def init_stops(self):
        self.lost = {1: 0.0, 2: 0.0}            # seconds of countable stoppage time in each half
        self.added = {}                          # added time given in each half
        self.subbed = set()                      # slots where a substitute has already come on
        self.yellows = {}                        # slot -> yellow cards
        self.sub_plan = [self.plan_subs(0), self.plan_subs(1)]

    # ---------- planning substitutions ----------

    def plan_subs(self, team):
        """Three to five changes, in up to three windows during the second half."""
        n = self.rng.choice([3, 4, 5, 5])
        windows = [self.rng.uniform(780, 1250), self.rng.uniform(1500, 1900), self.rng.uniform(2050, 2450)]
        counts = [0, 0, 0]
        for _ in range(n):
            counts[self.rng.choice([0, 1, 1, 2, 2])] += 1
        return [[w, c] for w, c in zip(windows, counts) if c]

    def try_substitute(self, t, dead):
        """At a stoppage, make any substitutions that are due."""
        if self.half != 2:
            return
        for team in (0, 1):
            due = [w for w in self.sub_plan[team] if t - self.half_start >= w[0]]
            for window in due:
                self.sub_plan[team].remove(window)
                for _ in range(window[1]):
                    self.substitute(team, t)
                extra = 22.0 + 6.0 * window[1]
                dead["until"] += extra
                self.lost[self.half] += LOST_COUNTED["substitution"] + 6.0 * window[1]

    def substitute(self, team, t):
        if self.bench_used[team] >= len(self.teams[team]["bench"]):
            return
        free = [i for i in self.outfield(team) if i not in self.subbed] or self.outfield(team)
        out = self.rng.choice(free)                                   # a substitute is not taken off again
        self.subbed.add(out)
        roster = 22 + (len(self.teams[0]["bench"]) if team == 1 else 0) + self.bench_used[team]
        name_on = self.roster_names[roster]
        self.bench_used[team] += 1
        old_name = self.names[out]
        base = F.ROLE_ATTRIBUTES[self.role[out]]
        self.names[out] = name_on                                     # the new player takes the slot
        self.who[out] = roster
        self.vmax[out] = base["pace"] + self.rng.gauss(0.15, 0.25)    # fresh legs
        self.passing[out] = base["passing"] + self.rng.gauss(0, 0.03)
        self.tackling[out] = base["tackling"] + self.rng.gauss(0, 0.03)
        self.shooting[out] = base["shooting"] + self.rng.gauss(0, 0.03)
        self.control[out] = base["control"] + self.rng.gauss(0, 0.03)
        self.roster_role[roster] = self.role[out]
        self.emit(t, "substitution", team, out, team, self.pos[out], player_on=name_on,
                  player_off=old_name)
        self.names[out] = name_on

    # ---------- the ball goes out ----------

    def ball_out(self, t, last_team, point_abs):
        """The ball has left the pitch at `point_abs`; `last_team` touched it last."""
        x, y = float(point_abs[0]), float(point_abs[1])
        edge_x, edge_y = min(x, PITCH_L - x), min(y, PITCH_W - y)
        if edge_y < edge_x:                                          # over a sideline: throw-in
            team = 1 - last_team
            spot = np.array([clip(x, 1.0, PITCH_L - 1.0), 0.0 if y < PITCH_W / 2 else PITCH_W])
            taker = min(self.outfield(team), key=lambda i: np.linalg.norm(self.pos[i] - spot))
            self.go_dead(t, "throw_in", team, spot, taker, self.rng.uniform(*DUR["throw_in"]), "throw_in")
            return
        defender = 0 if (x < PITCH_L / 2) == (self.dir[0] == 1) else 1   # whose goal line this is
        if last_team == defender:                                    # put out by the defence: a corner
            team = 1 - defender
            flag = np.array([0.0 if x < PITCH_L / 2 else PITCH_L, 0.0 if y < PITCH_W / 2 else PITCH_W])
            outs = [i for i in self.outfield(team) if self.role[i] in ("W", "CM", "FB")] or self.outfield(team)
            taker = min(outs, key=lambda i: np.linalg.norm(self.pos[i] - flag))
            self.go_dead(t, "corner", team, flag, taker, self.rng.uniform(*DUR["corner"]), "corner",
                         plan=lambda d: self.plan_corner(d))
        else:                                                        # put out by the attack: a goal kick
            spot = self.f(defender, np.array([5.5, 34.0]))
            self.go_dead(t, "goal_kick", defender, spot, self.gk(defender), self.rng.uniform(*DUR["goal_kick"]),
                         "goal_kick", lost=LOST_COUNTED["goal_kick"], plan=lambda d: self.plan_goal_kick(d))

    def go_dead(self, t, kind, team, spot, taker, duration, reason, lost=0.0, plan=None, **extra):
        """Play stops. A `stoppage` event records why and for how long; the restart happens later."""
        spot = np.array([clip(spot[0], 0.0, PITCH_L), clip(spot[1], 0.0, PITCH_W)])
        self.dead = {"kind": kind, "until": t + duration, "spot": spot, "team": team, "taker": taker, "targets": {}}
        self.dead.update(extra)
        self.flight = self.carry = None
        self.carrier, self.poss = -1, team
        self.runs = {}                                           # the ball stays where it went out; someone fetches it
        self.in_box = [False, False]
        self.lost[self.half] += lost
        actor = taker if taker is not None else self.gk(team)
        self.emit(t, "stoppage", team, actor, team, spot, reason=reason, duration_s=round(duration, 1))
        if plan is not None:
            plan(self.dead)
        self.try_substitute(t, self.dead)
        self.dead["duration"] = self.dead["until"] - t

    def setpiece_targets(self, tgt, urgency, t):
        d = self.dead
        if d["taker"] is not None and d["kind"] not in ("kickoff",):
            tgt[d["taker"]], urgency[d["taker"]] = d["spot"], 1.0
        for i, (point, u) in d["targets"].items():
            tgt[i], urgency[i] = point, u

    # ---------- planning where everyone stands ----------

    def plan_corner(self, d):
        att, dfd = d["team"], 1 - d["team"]
        taker = d["taker"]
        others = [i for i in self.outfield(att) if i != taker]
        priority = {"ST": 0, "CB": 1, "W": 2, "CM": 3, "DM": 4, "FB": 5}
        others.sort(key=lambda i: priority[self.role[i]])
        slots = [(93, 31), (95, 37), (97, 34), (91, 26), (92, 42), (99, 30)]
        for i, s in zip(others[:6], slots):
            d["targets"][i] = (self.f(att, np.array([s[0] + self.rng.uniform(-1, 1), s[1] + self.rng.uniform(-1.5, 1.5)])), 0.8)
        for k, i in enumerate(others[6:]):
            d["targets"][i] = (self.f(att, np.array([80.0, 20.0 + 12.0 * k])), 0.6)
        defenders = self.outfield(dfd)
        defenders.sort(key=lambda i: priority[self.role[i]] if self.role[i] != "ST" else 6)
        dslots = [(96, 30), (96, 38), (98, 34), (93, 28), (93, 40), (100, 32), (100, 36)]
        box = defenders[:7]
        for i, s in zip(box, dslots):
            d["targets"][i] = (self.f(att, np.array([s[0] + self.rng.uniform(-1, 1), s[1] + self.rng.uniform(-1.5, 1.5)])), 0.8)
        for k, i in enumerate(defenders[7:]):
            d["targets"][i] = (self.f(att, np.array([82.0, 22.0 + 12.0 * k])), 0.6)
        d["targets"][self.gk(dfd)] = (self.f(att, np.array([101.5, 33.0])), 0.8)
        d["targets"][self.gk(att)] = (self.f(att, np.array([30.0, 34.0])), 0.5)   # the keeper stays at his end

    def plan_goal_kick(self, d):
        """The kicking team spreads out and pushes its forwards to the halfway line; the other team squeezes up."""
        team, other = d["team"], 1 - d["team"]
        reach = 50.0 + 12.0 * self.tac[team]["directness"]            # how far up the forwards stand
        for i in self.outfield(team):
            ax, ay = self.anchor[i]
            x = {"CB": 17.0, "FB": 22.0, "DM": 38.0, "CM": 45.0, "W": reach + 4.0, "ST": reach + 8.0}[self.role[i]]
            d["targets"][i] = (self.f(team, np.array([x, 34 + (ay - 34) * 1.05])), 0.7)
        for i in self.outfield(other):
            ax, ay = self.anchor[i]
            x = {"CB": 52.0, "FB": 50.0, "DM": 58.0, "CM": 66.0, "W": 74.0, "ST": 80.0}[self.role[i]]
            d["targets"][i] = (self.f(team, np.array([x, 34 - (ay - 34) * 0.9])), 0.7)   # x, y in the kicker's frame

    def plan_free_kick(self, d):
        att, dfd = d["team"], 1 - d["team"]
        spot_t = self.f(att, d["spot"])
        goal = np.array([105.0, 34.0])
        to_goal = goal - spot_t
        dist = float(np.linalg.norm(to_goal))
        unit = to_goal / (dist + 1e-9)
        perp = np.array([-unit[1], unit[0]])
        if d["fk_kind"] == "direct":
            n = 4 if dist < 22 else (3 if dist < 28 else 2)
            center = spot_t + unit * 9.15
            offset = self.rng.uniform(-0.8, 0.8)                    # the wall is rarely dead on the line
            ordered = sorted(self.outfield(dfd), key=lambda i: np.linalg.norm(self.f(att, self.pos[i]) - center))
            wall = ordered[:n]
            for k, i in enumerate(wall):
                point = center + perp * (offset + (k - (n - 1) / 2) * 0.8)
                d["targets"][i] = (self.f(att, point), 1.0)
            d["wall"] = wall
            near_post = 30.34 if spot_t[1] < 34 else 37.66
            d["targets"][self.gk(dfd)] = (self.f(att, np.array([104.0, near_post + (1.2 if spot_t[1] < 34 else -1.2)])), 0.8)
            others = [i for i in self.outfield(att) if i != d["taker"]]
            for k, i in enumerate(others[:3]):                       # team-mates wait on the edge for a rebound
                d["targets"][i] = (self.f(att, np.array([86.0 + k, 28.0 + 6.0 * k])), 0.7)
        elif d["fk_kind"] == "cross":
            self.plan_corner({"team": att, "taker": d["taker"], "targets": d["targets"]})

    def plan_penalty(self, d):
        att, dfd = d["team"], 1 - d["team"]
        d["targets"][self.gk(dfd)] = (self.f(att, np.array([104.4, 34.0])), 0.8)
        for k, i in enumerate([i for i in self.outfield(att) if i != d["taker"]]):
            d["targets"][i] = (self.f(att, np.array([80.0 + (k % 3), 18.0 + 3.2 * k])), 0.6)
        for k, i in enumerate(self.outfield(dfd)):
            d["targets"][i] = (self.f(att, np.array([81.5 + (k % 3), 17.0 + 3.4 * k])), 0.6)

    def plan_kickoff(self, d):
        team = d["team"]
        for tm in (0, 1):
            for i in self.players_of(tm):
                spots = self.anchor[i].copy()
                spots[0] = min(spots[0], 52.0 if tm == team else 42.5)
                d["targets"][i] = (self.f(tm, spots), 0.7)
        kickers = [i for i in self.team_idx[team] if self.role[i] == "ST" and self.active[i]] or self.outfield(team)
        d["taker"] = kickers[0]
        d["targets"][kickers[0]] = (np.array([PITCH_L / 2, PITCH_W / 2]), 0.8)

    def players_of(self, team):
        return [int(i) for i in self.team_idx[team] if self.active[i]]

    # ---------- the restart ----------

    def restart(self, t):
        d = self.dead
        self.dead = None
        self.ball = d["spot"].copy()
        getattr(self, "do_" + d["kind"])(t, d)

    def fetch_ball(self):
        """While play is stopped, the ball is carried back to the spot of the restart (about 13 m/s)."""
        gap = self.dead["spot"] - self.ball
        dist = float(np.linalg.norm(gap))
        if dist > 1e-9:
            self.ball = self.ball + gap / dist * min(dist, 13.0 * 0.5)

    def move_taker_to_spot(self, d):
        taker = d["taker"]
        self.step_to(taker, d["spot"], limit=3.0)                  # he has had many seconds to walk here
        self.vel[taker] = 0
        self.ball = d["spot"].copy()

    def simple_pass(self, c, t, etype, fields, max_dist=30.0):
        """A plain restart pass (throw-in, free kick): the taker picks a team-mate in range."""
        team = int(self.team_of[c])
        me = self.f(team, self.pos[c])
        mates = [j for j in self.outfield(team) if j != c]
        opponents = self.outfield(1 - team)
        O = self.f(team, self.pos[opponents])
        press_m = float(np.linalg.norm(O - me, axis=1).min())
        best, best_score = None, -1e9
        for j in mates:
            pj = self.f(team, self.pos[j])
            dj = float(np.linalg.norm(pj - me))
            if dj > max_dist or dj < 3.0:
                continue
            open_m = float(np.linalg.norm(O - pj, axis=1).min())
            risk = self.cut_risk(me, pj, dj / 13.0, O, self.vmax[opponents])
            p = self.p_success("short", dj, press_m, open_m, risk, self.passing[c])
            score = 2.0 * p + 0.4 * min(open_m / 8, 1.0) + 0.02 * (pj[0] - me[0]) + self.rng.gauss(0, 0.2)
            if score > best_score:
                best, best_score, best_args = j, score, (p, risk)
        if best is None:
            best = min(mates, key=lambda j: np.linalg.norm(self.pos[j] - self.pos[c]))
            dj = float(np.linalg.norm(self.pos[best] - self.pos[c]))
            risk = 0.0
            best_args = (self.p_success("short", dj, press_m, 6.0, risk, self.passing[c]), risk)
        self.launch(c, best, "short", best_args[0], best_args[1], press_m, t, etype=etype, fields=fields)

    def do_throw_in(self, t, d):
        self.move_taker_to_spot(d)
        self.carrier, self.poss = d["taker"], d["team"]
        self.simple_pass(d["taker"], t, "throw_in", {"pass_type": "throw_in"}, max_dist=26.0)

    def do_goal_kick(self, t, d):
        gk = d["taker"]
        self.move_taker_to_spot(d)
        self.give_ball(gk, t, wait=0.0, trigger="goal_kick")
        self.keeper_play(t)

    def do_pause(self, t, d):
        team = d["team"]
        taker = min(self.outfield(team), key=lambda i: np.linalg.norm(self.pos[i] - d["spot"]))
        self.step_to(taker, d["spot"], limit=3.0)
        self.give_ball(taker, t, wait=self.rng.uniform(0.4, 1.0))

    def do_kickoff(self, t, d):
        self.place_kicker(d["team"], t)

    def do_corner(self, t, d):
        att, dfd = d["team"], 1 - d["team"]
        taker = d["taker"]
        self.move_taker_to_spot(d)
        self.carrier, self.poss = taker, att
        spot_t = self.f(att, d["spot"])
        delivery = self.rng.choices(["inswinger", "outswinger", "short"], weights=[0.45, 0.45, 0.10])[0]
        zone = self.rng.choice(["near_post", "penalty_spot", "far_post"])
        zone_xy = {"near_post": (98.0, 38.5), "penalty_spot": (94.0, 34.0), "far_post": (97.0, 25.0)}[zone]
        side = 1.0 if spot_t[1] > 34 else -1.0
        landing = np.array([zone_xy[0], 34.0 + side * (zone_xy[1] - 34.0)])
        kp = self.f(att, self.pos[self.gk(dfd)])
        kdist = float(np.linalg.norm(kp - landing))
        weights = ([0.5, 0.2, 0.08, 0.22] if kdist <= 7 else [0.25, 0.15, 0.10, 0.5] if kdist <= 10 else [0.05, 0.03, 0.12, 0.8])
        decision = self.rng.choices(["claim", "punch", "miss", "stay"], weights=weights)[0]
        in_box = lambda team, i: (lambda p: p[0] >= BOX_X and BOX_Y0 <= p[1] <= BOX_Y1)(self.f(att, self.pos[i]))
        event = self.emit(t, "corner", att, taker, att, d["spot"], delivery=delivery, target_zone=zone,
                          attackers_in_box=sum(1 for i in self.outfield(att) if i != taker and in_box(att, i)),
                          defenders_in_box=sum(1 for i in self.outfield(dfd) if in_box(att, i)),
                          keeper_x=round(float(kp[0]), 1), keeper_y=round(float(kp[1]), 1),
                          keeper_decision=decision, outcome=None)
        if delivery == "short":
            event["outcome"] = "short_routine"
            self.simple_pass(taker, t, None, {}, max_dist=18.0)
        else:
            self.deliver_box(t, taker, event, "corner", decision)

    def do_free_kick(self, t, d):
        att, dfd = d["team"], 1 - d["team"]
        taker = d["taker"]
        self.move_taker_to_spot(d)
        self.carrier, self.poss = taker, att
        spot_t = self.f(att, d["spot"])
        kp = self.f(att, self.pos[self.gk(dfd)])
        kind = d["fk_kind"]
        fields = dict(kind=kind, outcome=None, keeper_x=round(float(kp[0]), 1), keeper_y=round(float(kp[1]), 1))
        if kind == "direct":
            wall = d.get("wall", [])
            unit = (np.array([105.0, 34.0]) - spot_t)
            unit = unit / (np.linalg.norm(unit) + 1e-9)
            if wall:
                centroid = np.mean([self.f(att, self.pos[i]) for i in wall], axis=0)
                rel = centroid - spot_t
                fields["wall_size"] = len(wall)
                fields["wall_distance_m"] = round(float(rel @ unit), 1)
                fields["wall_offset_m"] = round(float(abs(rel[0] * unit[1] - rel[1] * unit[0])), 1)
            near_post = 30.34 if spot_t[1] < 34 else 37.66
            fields["keeper_post_offset_m"] = round(float(abs(kp[1] - near_post)), 1)
        else:
            fields["target_zone"] = self.rng.choice(["near_post", "penalty_spot", "far_post"])
        event = self.emit(t, "free_kick", att, taker, att, d["spot"], **fields)
        if kind == "direct":
            self.take_shot(taker, t, 6.0, {"situation": "free_kick", "wall": d.get("wall", []),
                                           "start": d["spot"].copy(), "on_shot": lambda e: event.update(outcome=e["outcome"])})
        elif kind == "cross":
            self.deliver_box(t, taker, event, "free_kick", "stay" if self.rng.random() < 0.5 else "claim")
        else:
            event["outcome"] = "short"
            self.simple_pass(taker, t, None, {}, max_dist=28.0)

    def do_penalty(self, t, d):
        att, dfd = d["team"], 1 - d["team"]
        taker = d["taker"]
        self.move_taker_to_spot(d)
        self.carrier, self.poss = taker, att
        spot_t = self.f(att, d["spot"])
        event = self.emit(t, "penalty", att, taker, att, d["spot"],
                          keeper_dive=self.rng.choice(["left", "right", "stays"]), outcome=None)
        self.take_shot(taker, t, 4.0, {"situation": "penalty", "start": d["spot"].copy(),
                                       "on_shot": lambda e: event.update(outcome=e["outcome"])})

    # ---------- fouls, cards, offsides ----------

    def foul_chance(self, defender, carrier, t):
        return FOUL_RATE * 0.5 * (1.5 - self.tackling[defender])

    def commit_foul(self, t, fouler, victim):
        att, dfd = int(self.team_of[victim]), int(self.team_of[fouler])
        spot = self.pos[victim].copy()
        in_box = self.in_own_box(dfd, spot)
        if in_box and self.rng.random() > PENALTY_CALL:               # most challenges in the box are waved away
            return
        self.emit(t, "foul", dfd, fouler, att, spot, fouled=self.names[victim], in_box=bool(in_box))
        self.lost[self.half] += LOST_COUNTED["foul"]
        self.maybe_card(t, fouler, att, spot)
        if in_box:
            mark = self.f(att, np.array([94.0, 34.0]))
            shooters = sorted(self.outfield(att), key=lambda i: -self.shooting[i])
            taker = shooters[0]
            self.go_dead(t, "penalty", att, mark, taker, self.rng.uniform(*DUR["penalty"]), "penalty",
                         lost=LOST_COUNTED["penalty"], plan=lambda dd: self.plan_penalty(dd))
            return
        me = self.f(att, spot)
        dist = math.hypot(105.0 - me[0], 34.0 - me[1])
        if me[0] >= 66 and abs(me[1] - 34) <= 22 and dist <= 34:
            kind = "direct" if self.rng.random() < FREE_KICK_SHOT_P else "cross"
        elif me[0] >= 58:
            kind = "cross"
        else:
            kind = "short"
        pool = [i for i in self.outfield(att) if self.role[i] in ("CM", "W", "DM", "FB", "ST")] or self.outfield(att)
        taker = max(pool, key=lambda i: (self.shooting[i] if kind == "direct" else self.passing[i]) - 0.01 * np.linalg.norm(self.pos[i] - spot))
        self.go_dead(t, "free_kick", att, spot, taker, self.rng.uniform(*DUR["free_kick"]), "free_kick",
                     plan=lambda dd: self.plan_free_kick(dd), fk_kind=kind)

    def maybe_card(self, t, fouler, att, spot):
        dfd = int(self.team_of[fouler])
        if self.slot[fouler] == "GK":
            return
        roll = self.rng.random()
        if self.yellows.get(fouler) and self.rng.random() > 0.12:      # a booked player is more careful
            return
        card = reason = None
        if roll < RED_P:
            card, reason = "red", "serious_foul_play"
        elif roll < RED_P + YELLOW_P:
            self.yellows[fouler] = self.yellows.get(fouler, 0) + 1
            if self.yellows[fouler] >= 2:
                card, reason = "red", "second_yellow"
            else:
                card, reason = "yellow", "foul"
        if card is None:
            return
        self.emit(t, "card", dfd, fouler, att, spot, card=card, reason=reason)
        self.lost[self.half] += LOST_COUNTED["card"]
        if card == "red":
            self.active[fouler] = False                              # he walks off (see move in sim_engine)
            self.runs.pop(fouler, None)

    def is_offside(self, team, c, j, start, ptype):
        """Is the receiver in an offside position when the pass is played? Only some are flagged."""
        if ptype not in ("through", "long", "cross", "short") or j is None or self.slot[j] == "GK":
            return False
        recv, passer = self.f(team, self.pos[j]), self.f(team, start)
        defenders = self.outfield(1 - team)
        if not defenders or recv[0] <= PITCH_L / 2 or recv[0] <= passer[0] + 1.0:
            return False
        line = max(self.f(team, self.pos[i])[0] for i in defenders)
        call = OFFSIDE_CALL * (0.1 if ptype == "cross" else 1.0)         # box runners time their runs onto crosses
        return bool(recv[0] > line + 0.3 and self.rng.random() < call)

    def call_offside(self, t, fl):
        att, dfd = fl["team"], 1 - fl["team"]
        j = fl["receiver"]
        spot = self.pos[j].copy()
        self.emit(t, "offside", att, j, att, spot)
        taker = min(self.outfield(dfd), key=lambda i: np.linalg.norm(self.pos[i] - spot))
        self.go_dead(t, "free_kick", dfd, spot, taker, self.rng.uniform(*DUR["offside"]), "offside", fk_kind="short")

    # ---------- goals, injuries ----------

    def goal_scored(self, t, team, shooter, shot_event):
        self.score[team] += 1
        xy = self.f(team, np.array([shot_event["x"], shot_event["y"]]))
        self.emit(t, "goal", team, shooter, team, xy, related_to=shot_event["_k"],
                  score="-".join(str(s) for s in self.score))
        conceding = 1 - team
        self.go_dead(t, "kickoff", conceding, np.array([PITCH_L / 2, PITCH_W / 2]), None,
                     self.rng.uniform(*DUR["goal"]), "goal", lost=LOST_COUNTED["goal"],
                     plan=lambda d: self.plan_kickoff(d))

    def maybe_injury(self, t):
        if self.carrier >= 0 and self.rng.random() < INJURY_RATE * 0.5:
            team = self.poss
            duration = self.rng.uniform(*DUR["injury"])
            outs = self.outfield(team)
            self.go_dead(t, "pause", team, self.pos[self.carrier].copy(), min(outs, key=lambda i: np.linalg.norm(self.pos[i] - self.ball)),
                         duration, "injury", lost=duration * 0.9)

    # ---------- half time, full time, added time ----------

    def compute_added(self, half):
        a = ADDED_FACTOR * self.lost[half] + self.rng.uniform(*ADDED_NOISE)
        return max(40.0, a)

    def check_half(self, t):
        if self.half_end is None and t >= self.half_start + HALF_SEC:
            added = self.compute_added(self.half)
            self.added[self.half] = added
            self.half_end = self.half_start + HALF_SEC + added
        if self.half_end is not None and t >= self.half_end and (self.dead or t >= self.half_end + 20.0):
            if self.half == 1:
                self.half, self.half_start, self.half_end = 2, t, None
                self.half2_start = t
                self.dir = [-1, 1]                                    # sides swap
                self.kickoff(1, t)
                self.emit(t, "stoppage", 1, self.carrier, 1, np.array([PITCH_L / 2, PITCH_W / 2]),
                          reason="half_time", duration_s=900.0)
            else:
                self.finished = True

    # ---------- runs off the ball, read from the tracking ----------

    def add_off_ball_runs(self):
        """For every shot, the attackers who sprinted into the final third in the seconds before it
        get an `off_ball_run` event. They are read from the tracking, not made up."""
        if not self.rec_players:
            return
        P = np.array(self.rec_players)
        shots = [e for e in self.events if e["type"] == "shot"]
        names = {tm["name"]: i for i, tm in enumerate(self.teams)}
        for shot in shots:
            team = names[shot["team"]]
            half = shot["half"]
            direction = self.dir_for(team, half)
            k1 = min(len(P) - 1, int(shot["t"] / 0.5))
            k0 = max(0, k1 - 16)                                      # the 8 seconds before the shot
            found = 0
            for i in self.team_idx[team][1:]:
                if self.names_at(i, k1) == shot["player"]:
                    continue
                path = P[k0:k1 + 1, i]
                if len(path) < 3 or path[0, 1] < 0:
                    continue
                speeds = np.linalg.norm(np.diff(path, axis=0), axis=1) / 0.5
                a, b = self.longest_sprint(speeds)
                if b - a < 3:
                    continue
                start, end = path[a], path[b + 1 if b + 1 < len(path) else b]
                length = float(np.linalg.norm(end - start))
                st = self.to_frame(direction, start)
                en = self.to_frame(direction, end)
                if length < 9.0 or en[0] < 70.0 or en[0] - st[0] < 4.0:
                    continue
                t_run = (k0 + a) * 0.5
                event = {"t": round(t_run, 2), "minute": int(t_run // 60), "second": int(t_run % 60), "half": half,
                         "clock": display_clock(t_run, self.half2_start if half == 2 else 1e9),
                         "team": shot["team"], "player": self.names_at(i, k0 + a), "type": "off_ball_run",
                         "x": round(float(st[0]), 1), "y": round(float(st[1]), 1), "end_x": round(float(en[0]), 1),
                         "end_y": round(float(en[1]), 1), "length_m": round(length, 1),
                         "speed_ms": round(float(speeds[a:b + 1].mean()), 1), "run_for": shot["_k"], "_k": self.keys}
                self.keys += 1
                self.events.append(event)
                found += 1
                if found >= 2:
                    break

    @staticmethod
    def longest_sprint(speeds, threshold=5.5):
        """The longest run of consecutive steps at sprinting speed: (first step, last step)."""
        best, start = (0, -1), None
        for k, s in enumerate(list(speeds) + [0.0]):
            if s >= threshold and start is None:
                start = k
            elif s < threshold and start is not None:
                if k - 1 - start > best[1] - best[0]:
                    best = (start, k - 1)
                start = None
        return best

    def dir_for(self, team, half):
        first = 1 if team == 0 else -1
        return first if half == 1 else -first

    @staticmethod
    def to_frame(direction, point):
        return np.array(point, dtype=float) if direction == 1 else np.array([PITCH_L - point[0], PITCH_W - point[1]])

    def names_at(self, slot, k):
        return self.roster_names[int(self.rec_who[k][slot])] if k < len(self.rec_who) else self.names[slot]
