"""Position-based match engine.

22 players and a ball move on a pitch in half-second steps. The ball carrier
chooses what to do from the real positions of everyone around, and the events
are read off what happened. Every 0.5 s the positions of all 22 players and the
ball are recorded: that is the tracking file.

The engine is one class built from four parts, each in its own file:
    sim_engine.py   this file: movement, the possession loop, passes, the clock
    sim_shots.py    shots, saves, goals, rebounds, and the fight for crosses and corners
    sim_keeper.py   the goalkeeper in possession: goal kicks, back passes, distribution
    sim_stops.py    stoppages: throw-ins, corners, fouls, cards, free kicks, offsides,
                    penalties, substitutions, half time and added time

Run it:
    python3 sim_engine.py --seed 1          # writes sim_events.json and sim_tracking.npz

Coordinates inside the engine are ABSOLUTE (x 0-105, y 0-68). self.f(team, ...)
turns them into a team's frame (that team attacking toward x = 105) and back.
Events are written the way the rest of the app expects: a possession in the
attacking team's frame, and defending events (tackle, possession_change, saves,
claims...) in the attacker's frame, i.e. the other team's frame than their
`team` field implies.
"""
import argparse
import json
import math
import random
import time

import numpy as np

import formations as F
from sim_keeper import KeeperMixin
from sim_shots import ShotsMixin
from sim_stops import StopsMixin

PITCH_L, PITCH_W = F.PITCH_L, F.PITCH_W
TICK = 0.5                 # seconds between steps (and tracking samples): 2 Hz
HALF_SEC = 2700.0          # 45 minutes, before added time
LONG_PASS_M = 32.0         # a pass of this length or more is "long"
BOX_X, BOX_Y0, BOX_Y1 = 88.5, 13.84, 54.16   # the penalty area, in the attacking frame
FINAL_THIRD_X = 70.0
A_MAX = 5.0                # m/s^2: how fast a player can change velocity
PARK = np.array([52.5, -2.5])   # where a sent-off player stands (off the pitch)

# ---- tuning knobs (see report_calibration.py) ----
HOLD_MIN, HOLD_MAX = 0.8, 2.5      # seconds a carrier takes before acting
RECEIVE_HOLD = (0.8, 2.1)          # seconds a receiver takes before acting on the ball
TEMPERATURE = 0.35                 # lower = the carrier picks the best option more often
TACKLE_RATE = 0.30                 # dispossession chance per second when an opponent is close
PASS_SPEED = {"short": 13.0, "back": 12.0, "switch": 20.0, "long": 22.0, "through": 15.0, "cross": 17.0}
# How a carrier weighs a pass: progress, safety, an open receiver, field position, and length
W_PROGRESS, W_PROGRESS_DIRECT = 0.70, 0.45
W_SAFE, W_OPEN, W_ZONE, W_DIST = 2.0, 0.5, 0.75, 0.8
# How much a carrier likes each kind of pass beyond its score: (base, per unit of directness)
LONG_BIAS, LONG_BIAS_PRESS = (0.2, 1.6), 0.6
THROUGH_BIAS = (-0.3, 0.6)
CROSS_BIAS, CROSS_BIAS_WIDE = (-0.8, 2.7), 0.0
BACK_BIAS, BACK_BIAS_PRESS = -2.2, 1.4
KEEPER_BACK_BIAS = -3.0            # passing back to the keeper, before pressure
FAIL_SCALE = 0.8                   # scales every technique error (1.0 = as written in p_success)
LONG_FAIL, CROSS_FAIL = 0.30, 0.90  # base failure chances of a long ball and a cross
RISK_BASE, RISK_RANGE = 0.09, 0.22  # a reachable defender cuts a pass out: 9% up to 31% by time to spare
CROSS_NOT_OUT = 0.6                # of failed crosses, how many stay in play (cleared or claimed)
LOOSE_BALL_SHARE = 0.35
MARK_PULL = 0.55                   # how far a defender leaves his spot to stand goal-side of a nearby attacker
REACH_MARGIN = 0.35                # seconds a defender needs to react and get going before he can reach a ball
CROSS_BASE = 0.30                  # (kept for reference) a cross's base chance
FINAL_THIRD_PENALTY, BOX_PENALTY = 0.0, 0.04
PUSH_ATTACK, PUSH_DEFEND = (-6.0, 9.0), (-10.0, 14.0)   # how far a shape moves (base, per unit of line height)
OFFSIDE_ERR = 5.0                  # how far past the line a mistimed run goes
OFFSIDE_AVOID = 0.97               # chance a carrier sees that a team-mate is offside and passes elsewhere


def clip(v, lo, hi):
    return max(lo, min(hi, v))


class Engine(StopsMixin, ShotsMixin, KeeperMixin):
    def __init__(self, seed):
        self.seed = seed
        self.rng = random.Random(seed)
        self.teams = F.build_teams(self.rng)
        starters = [p for t in self.teams for p in t["players"]]
        self.names = [p["name"] for p in starters]
        self.slot = [p["slot"] for p in starters]
        self.role = [p["role"] for p in starters]
        self.anchor = np.array([p["anchor"] for p in starters], dtype=float)
        pick = lambda key: np.array([p[key] for p in starters], dtype=float)
        self.vmax, self.passing, self.tackling = pick("pace"), pick("passing"), pick("tackling")
        self.control, self.shooting = pick("control"), pick("shooting")
        self.team_of = np.array([0] * 11 + [1] * 11)
        self.team_idx = [np.arange(0, 11), np.arange(11, 22)]
        self.tac = [t["tactics"] for t in self.teams]
        # the roster: the 22 starters, then each team's bench (a substitution swaps a name into a slot)
        self.roster_names = list(self.names) + self.teams[0]["bench"] + self.teams[1]["bench"]
        self.roster_team = [0] * 11 + [1] * 11 + [0] * len(self.teams[0]["bench"]) + [1] * len(self.teams[1]["bench"])
        self.roster_role = list(self.role) + ["bench"] * (len(self.roster_names) - 22)
        self.who = np.arange(22)                # which roster entry stands in each slot right now
        self.bench_used = [0, 0]
        self.dir = [1, -1]                      # which way each team attacks (absolute x), first half
        self.half = 1
        self.half_start, self.half_end = 0.0, None
        self.finished = False
        self.pos = np.zeros((22, 2))
        self.vel = np.zeros((22, 2))
        self.active = np.ones(22, dtype=bool)   # False once a player is sent off
        self.ball = np.array([PITCH_L / 2, PITCH_W / 2])
        self.carrier, self.poss = -1, 0         # who has the ball, and which team has possession
        self.flight = None                      # a ball in the air
        self.dead = None                        # the ball is out of play, waiting for a restart
        self.carry = None                       # a dribble in progress
        self.next_decision = 0.0
        self.runs = {}                          # player index -> (target in team frame, expires at)
        self.in_box = [False, False]
        self.score = [0, 0]
        self.events = []
        self.keys = 0                           # emission counter: a stable name for each event during play
        self.rec_players, self.rec_ball, self.rec_half, self.rec_times, self.rec_who = [], [], [], [], []
        self.poss_time = [0.0, 0.0]
        self.dead_time = 0.0
        self.init_shots()
        self.init_keeper()
        self.init_stops()

    # ---------- small helpers ----------

    def f(self, team, pts):
        """Absolute points -> the team's attacking frame (the same call converts back)."""
        pts = np.asarray(pts, dtype=float)
        if self.dir[team] == 1:
            return pts
        return np.stack([PITCH_L - pts[..., 0], PITCH_W - pts[..., 1]], axis=-1)

    def gk(self, team):
        return int(self.team_idx[team][0])

    def outfield(self, team):
        """A team's outfield players still on the pitch."""
        return [int(i) for i in self.team_idx[team][1:] if self.active[i]]

    def other(self, team):
        return 1 - team

    # ---------- events ----------

    def emit(self, t, etype, team, actor, frame_team, xy_abs, traffic=None, **fields):
        """Record one event. `frame_team` decides the frame x, y are written in."""
        xy = self.f(frame_team, xy_abs)
        event = {"t": round(t, 2), "minute": int(t // 60), "second": int(t % 60), "half": self.half,
                 "team": self.teams[team]["name"], "player": self.names[actor], "type": etype,
                 "x": round(float(xy[0]), 1), "y": round(float(xy[1]), 1), "_k": self.keys}
        self.keys += 1
        event.update(fields)
        if traffic or (traffic is None and event["x"] >= FINAL_THIRD_X):   # the players around, for line of sight
            event["traffic"] = self.traffic(actor, frame_team, xy_abs)
        self.events.append(event)
        self.note_event(event, team, t)                 # sim_shots: remember what could set up a shot
        return event

    def traffic(self, actor, frame_team, xy_abs, radius=18.0):
        near = (np.linalg.norm(self.pos - xy_abs, axis=1) <= radius) & self.active
        near[actor] = False
        bodies = []
        for i in np.nonzero(near)[0]:
            x, y = self.f(frame_team, self.pos[i])
            bodies.append({"team": self.teams[self.team_of[i]]["name"],
                           "role": "attacker" if self.team_of[i] == frame_team else "defender",
                           "x": round(float(x), 1), "y": round(float(y), 1)})
        return bodies

    # ---------- giving the ball to somebody ----------

    def give_ball(self, player, t, wait=None, trigger=None):
        """`player` has the ball and will act after a short pause."""
        team = int(self.team_of[player])
        self.carrier, self.poss = player, team
        self.flight = self.carry = None
        self.ball = self.pos[player].copy()
        self.next_decision = t + (wait if wait is not None else self.rng.uniform(*RECEIVE_HOLD))
        if player == self.gk(team):
            self.keeper_trigger = trigger or "back_pass"
            self.keeper_since = t

    # ---------- what each player is trying to do ----------

    def targets(self, t):
        tgt = np.zeros((22, 2))
        urgency = np.full(22, 0.55)
        for team in (0, 1):
            idx = self.team_idx[team]
            tac = self.tac[team]
            b = self.f(team, self.ball)
            has_ball = (self.dead["team"] == team) if self.dead else (self.poss == team)
            spots = self.anchor[idx].copy()
            spots[:, 1] = 34 + (spots[:, 1] - 34) * (0.55 + 0.6 * tac["width"])
            wingers = np.array([self.role[i] == "W" for i in idx])
            if has_ball:                                                    # wingers hug the touchline in attack
                spots[wingers, 1] = 34 + (spots[wingers, 1] - 34) * 1.18
            outfield = np.array([self.slot[i] != "GK" for i in idx])
            # the whole shape moves up when the team has the ball, and drops back when it does not
            spots[outfield, 0] += (PUSH_ATTACK[0] + PUSH_ATTACK[1] * tac["line_height"]) if has_ball else (
                PUSH_DEFEND[0] + PUSH_DEFEND[1] * tac["line_height"])
            spots[outfield, 0] += 0.28 * (b[0] - spots[outfield, 0])     # compactness: drawn toward the ball
            spots[outfield, 1] += 0.30 * (b[1] - spots[outfield, 1])
            spots[~outfield, 0] = 3 + 0.04 * b[0]                          # the keeper follows the ball a little
            spots[~outfield, 1] = clip(34 + 0.18 * (b[1] - 34), 28, 40)
            local_urgency = np.full(11, 0.55)
            others = [i for i in self.team_idx[1 - team][1:] if self.active[i]]
            if not has_ball and others:                                     # marking: stand goal-side of a nearby attacker
                attackers = self.f(team, self.pos[others])
                for k in np.nonzero(outfield)[0]:
                    gaps = np.linalg.norm(attackers - spots[k], axis=1)
                    near = int(gaps.argmin())
                    if gaps[near] < 14.0:
                        spots[k] = spots[k] + MARK_PULL * (attackers[near] - spots[k]) - np.array([1.5, 0.0])
            if not has_ball and not self.dead:                              # pressing
                outs = np.array([i for i in idx[outfield] if self.active[i]])
                order = np.argsort(np.linalg.norm(self.pos[outs] - self.ball, axis=1))
                for rank, k in enumerate(order[:1 + int(round(2 * tac["press"]))]):
                    slot_k = int(outs[k]) - int(idx[0])
                    spots[slot_k] = b if rank == 0 else b + np.array([-3.0, 0.0])
                    local_urgency[slot_k] = 1.0 if rank == 0 else 0.85
            for i, (run_target, expires) in self.runs.items():             # attackers' runs into space
                if self.team_of[i] == team and t < expires and self.active[i]:
                    spots[int(i) - int(idx[0])] = run_target
                    local_urgency[int(i) - int(idx[0])] = 1.0
            if has_ball and others:                                         # attackers hold the offside line, mostly
                line = float(self.f(team, self.pos[others])[:, 0].max())
                running = {int(i) - int(idx[0]) for i, (_, ex) in self.runs.items() if self.team_of[i] == team and t < ex}
                for k in np.nonzero(outfield)[0]:
                    if int(k) in running:                                    # a timed run into the box is not held back
                        continue
                    late_run = (int(idx[k]) + int(t // 4)) % 6 == 0          # now and then a runner mistimes it
                    spots[k, 0] = min(spots[k, 0], line + (OFFSIDE_ERR if late_run else 1.2))
            tgt[idx] = self.f(team, spots)
            urgency[idx] = local_urgency
        self.keeper_targets(tgt, urgency, t)                  # sim_keeper: rush out to close down
        c = self.carrier
        if c >= 0 and self.carry:
            tgt[c], urgency[c] = self.carry["target"], 0.75
        elif c >= 0:
            drift = 3.0 if self.f(int(self.team_of[c]), self.pos[c])[0] < 92.0 else 0.0      # a carrier does not walk into the net
            tgt[c] = self.pos[c] + np.array([float(self.dir[self.team_of[c]]) * drift, 0.0])
            urgency[c] = 0.4
        if self.flight:
            fl = self.flight
            if fl["receiver"] is not None:
                tgt[fl["receiver"]], urgency[fl["receiver"]] = fl["end"], 1.0
            if fl["interceptor"] is not None:
                tgt[fl["interceptor"]], urgency[fl["interceptor"]] = fl["end"], 1.0
        if self.dead:
            self.setpiece_targets(tgt, urgency, t)             # sim_stops: walls, box occupancy, takers
        tgt[:, 0] = np.clip(tgt[:, 0], 1, PITCH_L - 1)
        tgt[:, 1] = np.clip(tgt[:, 1], 1, PITCH_W - 1)
        tgt[~self.active], urgency[~self.active] = PARK, 0.45     # sent-off players head for the tunnel
        return tgt, urgency

    def move(self, tgt, urgency):
        """Steer every player toward their target, limited by max speed and acceleration."""
        d = tgt - self.pos
        dist = np.linalg.norm(d, axis=1) + 1e-9
        speed = np.minimum(self.vmax * urgency, dist / 0.9)        # ease off when close
        desired = d / dist[:, None] * speed[:, None]
        dv = desired - self.vel
        mag = np.linalg.norm(dv, axis=1) + 1e-9
        dv *= np.minimum(1.0, A_MAX * TICK / mag)[:, None]
        self.vel += dv
        self.pos += self.vel * TICK
        diff = self.pos[:, None, :] - self.pos[None, :, :]          # a little repulsion: players do not stack
        gap = np.linalg.norm(diff, axis=-1) + np.eye(22) * 10 + 1e-6
        push = diff / gap[..., None] * np.clip(2.2 - gap, 0, None)[..., None] * 0.25
        self.pos += push.sum(axis=1)
        on = self.active                                            # a sent-off player walks off and stays off the pitch
        self.pos[on, 0] = np.clip(self.pos[on, 0], 0.3, PITCH_L - 0.3)
        self.pos[on, 1] = np.clip(self.pos[on, 1], 0.3, PITCH_W - 0.3)
        gone = ~on
        self.pos[gone, 1] = np.maximum(self.pos[gone, 1], PARK[1])
        self.vel[gone & (self.pos[:, 1] <= PARK[1] + 0.01)] = 0

    # ---------- deciding what to do with the ball ----------

    def p_success(self, ptype, d, press_m, open_m, risk, skill):
        """Chance a pass finds its target: 1 minus technique errors minus the risk that a
        defender who can reach the ball cuts it out (see cut_risk)."""
        fail = {"short": 0.015 + 0.0030 * d, "back": 0.010 + 0.0025 * d,
                "switch": 0.12 + 0.0040 * (d - 30), "long": LONG_FAIL + 0.0060 * (d - LONG_PASS_M),
                "through": 0.40, "cross": CROSS_FAIL}[ptype]
        fail *= clip(1.6 - 0.9 * skill, 0.75, 1.3)                      # better passers err less
        fail += 0.06 if press_m < 2.0 else (0.03 if press_m < 4.0 else 0.0)   # the passer is closed down
        fail += 0.05 if open_m < 2.0 else (-0.02 if open_m > 6.0 else 0.0)    # the receiver is marked or free
        return clip(1 - fail * FAIL_SCALE - risk * (0.4 if ptype == "cross" else 1.0), 0.05, 0.985)   # a cross is lofted over most defenders

    def cut_risk(self, start, aim, flight_time, opp_xy, opp_vmax):
        """How likely a defender is to cut a pass out: zero if nobody can reach any point
        of its path before the ball, otherwise from 9 to 31 percent by how much time he has to spare."""
        fractions = np.array([0.2, 0.35, 0.5, 0.65, 0.8, 0.9])
        points = start + fractions[:, None] * (aim - start)
        gap = np.linalg.norm(opp_xy[None, :, :] - points[:, None, :], axis=2)
        slack = (fractions * flight_time)[:, None] - (REACH_MARGIN + gap / (0.9 * opp_vmax)[None, :])
        best = float(slack.max())
        return 0.0 if best < 0 else RISK_BASE + RISK_RANGE * min(best / 1.2, 1.0)

    def final_third_penalty(self, x_receiver):
        """Defences are compact near their own goal, so passes there fail more often."""
        return FINAL_THIRD_PENALTY if x_receiver > 70 else 0.0

    def decide(self, t):
        """The carrier looks at the real positions and picks a pass, a dribble or a shot."""
        c = self.carrier
        team = int(self.team_of[c])
        tac = self.tac[team]
        me = self.f(team, self.pos[c])
        mates = [j for j in self.team_idx[team] if j != c and self.slot[j] != "GK" and self.active[j]]
        opp_players = [j for j in self.team_idx[1 - team] if self.active[j]]
        P = self.f(team, self.pos[mates])
        O = self.f(team, self.pos[opp_players])                      # includes the keeper (first)
        press_m = float(np.linalg.norm(O - me, axis=1).min())
        press = clip(1 - press_m / 6.0, 0, 1)
        vec = P - me
        d = np.linalg.norm(vec, axis=1) + 1e-9
        opp_out = [j for j in opp_players if self.slot[j] != "GK"]
        opp_xy, opp_vmax = O[1:], self.vmax[opp_out]
        open_m = np.linalg.norm(O[None, :, :] - P[:, None, :], axis=-1).min(1)
        opp_line = float(np.sort(O[1:, 0])[-2])            # the second-last defender: roughly the offside line
        last_defender = float(O[1:, 0].max())              # the true offside line (the keeper is behind it)
        wide = abs(me[1] - 34) > 15 and me[0] > 66
        crowd = clip((int((np.linalg.norm(O - me, axis=1) < 10).sum()) - 1) / 3.0, 0, 1)

        options = []
        for k, j in enumerate(mates):
            pk, fwd = P[k], float(vec[k, 0])
            box_target = pk[0] > 80 and abs(pk[1] - 34) < 17
            if wide and box_target and fwd > 5:
                ptype = "cross"
            elif fwd > 12 and pk[0] >= opp_line + 1 and open_m[k] > 3.0:
                ptype = "through"
            elif fwd < -3:
                ptype = "back"
            elif abs(vec[k, 1]) >= 30 and d[k] >= 30:
                ptype = "switch"
            elif d[k] >= LONG_PASS_M:
                ptype = "long"
            else:
                ptype = "short"
            flight_time = float(d[k]) / PASS_SPEED[ptype]
            risk = self.cut_risk(me, pk, flight_time, opp_xy, opp_vmax)
            p = self.p_success(ptype, float(d[k]), press_m, float(open_m[k]), risk, self.passing[c])
            if ptype != "cross":   # a cross is already priced in (its own low base chance)
                p -= self.final_third_penalty(pk[0]) + (BOX_PENALTY if pk[0] > 88 else 0.0)
            progress = clip(fwd / 20.0, -0.7, 1.0)
            zone = min(pk[0], 88.0) / 88.0
            score = ((W_PROGRESS + W_PROGRESS_DIRECT * tac["directness"]) * progress + W_SAFE * p
                     + W_OPEN * min(open_m[k] / 8, 1.0) + W_ZONE * zone - W_DIST * d[k] / 30.0)
            if pk[0] > 96.0:                                                 # nobody wants to receive on the goal line
                score -= 0.8 * (pk[0] - 96.0)
            score += {"long": LONG_BIAS[0] + LONG_BIAS[1] * tac["directness"] + LONG_BIAS_PRESS * press,
                      "switch": -0.2 + 0.5 * crowd,
                      "through": THROUGH_BIAS[0] + THROUGH_BIAS[1] * tac["directness"],
                      "cross": CROSS_BIAS[0] + CROSS_BIAS[1] * tac["crossing"] + (CROSS_BIAS_WIDE if wide else 0.0),
                      "back": BACK_BIAS + BACK_BIAS_PRESS * press + (0.4 if me[0] > 78 else 0.0),
                      "short": 0.0}[ptype]
            if pk[0] > last_defender + 0.3 and pk[0] > PITCH_L / 2 and ptype != "cross":   # offside: usually seen and avoided
                if self.rng.random() < OFFSIDE_AVOID:
                    continue
            score += self.rng.gauss(0, 0.25)
            options.append((score, "pass", j, ptype, p, float(d[k]), risk))
        gk = self.gk(team)                                              # the keeper as a back-pass option
        if me[0] < 48 and press > 0.15 and self.active[gk]:
            kp = self.f(team, self.pos[gk])
            dk = float(np.linalg.norm(kp - me))
            risk = self.cut_risk(me, kp, dk / PASS_SPEED["back"], opp_xy, opp_vmax)
            p = self.p_success("back", dk, press_m, 8.0, risk, self.passing[c])
            options.append((KEEPER_BACK_BIAS + 2.4 * press + W_SAFE * p + self.rng.gauss(0, 0.25),
                            "pass", gk, "back", p, dk, risk))
        ahead = O[(O[:, 0] > me[0]) & (np.abs(O[:, 1] - me[1]) < 8)]
        space = float(np.linalg.norm(ahead - me, axis=1).min()) if len(ahead) else 20.0
        score_dribble = -0.2 + 0.9 * clip(space / 10, 0, 1) + 0.5 * (self.vmax[c] - 7.0) / 1.5 - 0.8 * press
        options.append((score_dribble + self.rng.gauss(0, 0.25), "dribble", None, None, None, None, None))
        shot = self.shot_option(c, team, me, press_m, t)                # sim_shots: a shot, if it is on
        if shot is not None:
            options.append((shot, "shot", None, None, None, None, None))

        top = max(o[0] for o in options)
        weights = [math.exp((o[0] - top) / TEMPERATURE) for o in options]
        choice = self.rng.choices(options, weights=weights)[0]
        if choice[1] == "shot":
            self.take_shot(c, t, press_m)
            return
        destination = me if choice[1] == "dribble" else self.f(team, self.pos[choice[2]])
        self.set_runs(c, team, destination, t)    # attackers move for where the ball is going
        self.maybe_close_down(c, team, me, t)     # sim_keeper: the keeper may rush out at a lone attacker
        if choice[1] == "dribble":
            self.start_dribble(c, team, me, t)
        else:
            _, _, j, ptype, p, dist, risk = choice
            self.launch(c, j, ptype, p, risk, press_m, t)
        self.next_decision = t + self.rng.uniform(HOLD_MIN, HOLD_MAX) * (1 - 0.35 * press)

    def set_runs(self, c, team, me, t):
        """Attackers sprint into space ahead of the ball. When the ball is out wide in
        the attacking half they flood the box, which is what makes crosses possible."""
        self.runs = {i: r for i, r in self.runs.items() if self.team_of[i] != team}
        if me[0] < 40:
            return
        wide_ball = abs(me[1] - 34) > 15 and me[0] > 62
        side = 1 if me[1] > 34 else -1
        for i in self.team_idx[team]:
            if i == c or not self.active[i]:
                continue
            mate = self.f(team, self.pos[i])
            if wide_ball and self.role[i] == "ST":
                target = [self.rng.uniform(90, 97), 34 + self.rng.uniform(-9, 9)]
            elif wide_ball and self.role[i] == "W" and (mate[1] - 34) * side < 0:   # the far-side winger: far post
                target = [self.rng.uniform(88, 94), 34 - side * self.rng.uniform(4, 9)]
            elif wide_ball and self.role[i] == "CM" and self.rng.random() < 0.5:    # midfielders: the edge of the box
                target = [self.rng.uniform(80, 86), 34 + self.rng.uniform(-10, 10)]
            elif self.role[i] in ("ST", "W") and self.rng.random() < 0.35:
                target = [min(98.0, max(me[0] + self.rng.uniform(8, 18), mate[0])),
                          clip(mate[1] + self.rng.uniform(-9, 9), 5, 63)]
            else:
                continue
            self.runs[i] = (np.array(target), t + 3.5)

    def start_dribble(self, c, team, me, t):
        duration = self.rng.uniform(1.5, 3.2)
        speed = min(self.vmax[c] * 0.72, 6.2)
        step = np.array([1.0, (34 - me[1]) * 0.02])
        end = me + step / np.linalg.norm(step) * speed * duration
        end[0] = min(end[0], 94.0)
        self.carry = {"until": t + duration, "target": self.f(team, end)}
        self.emit(t, "dribble", team, c, team, self.pos[c], end_x=round(float(end[0]), 1),
                  end_y=round(float(end[1]), 1), length_m=round(float(np.linalg.norm(end - me)), 1))
        self.next_decision = t + duration

    # ---------- passes ----------

    def launch(self, c, j, ptype, p, risk, press_m, t, etype=None, fields=None, resolve=None, aim=None):
        """The carrier `c` plays the ball toward team-mate `j`. `etype`/`fields` let a restart
        (throw-in, keeper distribution...) record itself instead of a plain pass; `resolve` is what
        happens when the ball lands (default: see fly)."""
        team = int(self.team_of[c])
        start = self.pos[c].copy()
        if aim is None:
            v_team = self.vel[j] * self.dir[team]                          # velocity as seen in the team frame
            guess = np.linalg.norm(self.pos[j] - start) / PASS_SPEED[ptype]
            aim_team = self.f(team, self.pos[j]) + v_team * min(guess, 1.5) * 0.6   # lead the receiver
            aim = self.f(team, aim_team)
        aim = np.array([clip(aim[0], 0.5, PITCH_L - 0.5), clip(aim[1], 0.5, PITCH_W - 0.5)])
        aim_team = self.f(team, aim)
        length = float(np.linalg.norm(aim - start))
        if resolve is None and ptype == "cross" and etype is None:
            resolve = self.resolve_cross
        success = self.rng.random() < p
        offside = self.is_offside(team, c, j, start, ptype) if etype is None and j is not None else False
        if offside:
            success = False
        kind = {"cross": "cross", "through": "through_ball"}.get(ptype, "pass")
        base = dict(receiver=self.names[j] if j is not None else None, success=bool(success), pass_type=ptype,
                    end_x=round(float(aim_team[0]), 1), end_y=round(float(aim_team[1]), 1),
                    length_m=round(length, 1), pressure_m=round(press_m, 1))
        if fields:
            base.update(fields)
        event = self.emit(t, etype or kind, team, c, team, start, **base)
        end, interceptor, loose_wait, fkind = aim, None, 0.0, "completed"
        if offside:
            fkind = "offside"
        elif not success:
            speed = PASS_SPEED[ptype]
            took_it = self.rng.random() < risk / max(1e-9, 1 - p)       # share of failures that are interceptions
            best = self.lane_defender(start, aim, 1 - team, speed) if took_it else None
            if best is not None:
                fkind = "intercepted"
                interceptor, end = best
            else:                                                        # a mistake: a loose ball, or overhit
                found = self.contest_winner(aim, 1 - team)
                if found is not None and found[1] <= 5.0 and self.rng.random() < LOOSE_BALL_SHARE:
                    fkind, interceptor, loose_wait = "contested", found[0], found[1]   # he runs onto the loose ball
                elif ptype == "cross" and self.rng.random() < CROSS_NOT_OUT:   # a cross usually ends in the box, not over the line
                    fkind = "contested"
                else:
                    fkind, end = "out", self.exit_point(start, aim)
        duration = max(0.5, float(np.linalg.norm(end - start)) / PASS_SPEED[ptype], loose_wait)   # a loose ball waits for him
        self.flight = {"start": start, "end": end, "t0": t, "t1": t + duration, "kind": fkind, "passer": c,
                       "receiver": j, "interceptor": interceptor, "team": team, "waited": 0.0, "ptype": ptype,
                       "event": event, "resolve": resolve, "success": bool(success), "last_team": team}
        self.carrier = -1
        self.carry = None
        self.after_launch(c, team, t)           # sim_keeper: note that the keeper has played the ball

    def exit_point(self, start, aim):
        """Where a missed pass leaves the pitch: along its line, through the nearest boundary."""
        direction = aim - start
        direction = direction / (np.linalg.norm(direction) + 1e-9)
        best = 1e9
        for axis, limit in ((0, 0.0), (0, PITCH_L), (1, 0.0), (1, PITCH_W)):
            if abs(direction[axis]) > 1e-9:
                s = (limit - start[axis]) / direction[axis]
                if s > 0:
                    best = min(best, s)
        return start + direction * min(best, 60.0)

    def lane_defender(self, start, aim, opp, speed):
        """The first opponent who can get to the ball along its path before it passes,
        and where he meets it. None if nobody can."""
        seg = aim - start
        flight_time = float(np.linalg.norm(seg)) / speed
        for s in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):          # walk along the pass
            point = start + s * seg
            reachable = []
            for i in self.team_idx[opp]:
                if self.slot[i] == "GK" or not self.active[i]:
                    continue
                reach = REACH_MARGIN + float(np.linalg.norm(self.pos[i] - point)) / (self.vmax[i] * 0.9)
                if reach <= s * flight_time:
                    reachable.append((reach, i))
            if reachable:
                return min(reachable)[1], point
        return None

    def contest_winner(self, aim, opp):
        """The opponent who can get to the end of a missed pass soonest, and how long he needs."""
        best = None
        for i in self.team_idx[opp]:
            if self.slot[i] == "GK" and not self.in_own_box(opp, aim):
                continue
            if not self.active[i]:
                continue
            reach = REACH_MARGIN + float(np.linalg.norm(self.pos[i] - aim)) / (self.vmax[i] * 0.9)
            if best is None or reach < best[0]:
                best = (reach, i)
        return None if best is None else (best[1], best[0])

    def in_own_box(self, team, point_abs):
        """Is this point inside `team`'s own penalty area?"""
        x, y = self.f(1 - team, point_abs)                 # in the attackers' frame the box is at x >= 88.5
        return x >= BOX_X and BOX_Y0 <= y <= BOX_Y1

    def fly(self, t):
        fl = self.flight
        frac = clip((t - fl["t0"]) / (fl["t1"] - fl["t0"]), 0.0, 1.0)
        self.ball = fl["start"] + frac * (fl["end"] - fl["start"]) if not fl["waited"] else fl["end"].copy()
        if t < fl["t1"]:
            return
        winner = fl["interceptor"]
        if winner is not None and fl["waited"] < 3.0 and np.linalg.norm(self.pos[winner] - fl["end"]) > 2.0:
            fl["t1"] = t + TICK          # he is not at the ball yet: it stays loose until he gets there
            fl["waited"] += TICK
            self.ball = fl["end"].copy()
            return
        self.flight = None
        self.land(t, fl)

    def land(self, t, fl):
        """The ball arrives. What happens depends on how the pass was resolved."""
        team, kind = fl["team"], fl["kind"]
        if fl["resolve"] is not None:                      # a restart or a cross decides this itself
            fl["resolve"](t, fl)
        elif kind == "completed":
            self.give_ball(fl["receiver"], t, trigger="back_pass")
        elif kind == "offside":
            self.call_offside(t, fl)
        elif kind == "intercepted":
            if self.slot[fl["interceptor"]] == "GK":
                self.keeper_wins_ball(t, fl, "keeper_sweep")
            else:
                self.won_ball(fl["interceptor"], t, "possession_change", loser=team, reason="interception")
        elif kind == "contested":
            winner = fl["interceptor"]
            if self.slot[winner] == "GK":
                self.keeper_wins_ball(t, fl, "keeper_sweep")
            else:
                self.won_ball(winner, t, "tackle" if self.rng.random() < 0.5 else "possession_change",
                              loser=team, reason="contested")
        else:
            self.ball_out(t, team, fl["end"])
        if fl["event"] is not None and fl["event"].get("type") == "keeper_distribution":
            self.finish_distribution(t, fl)               # sim_keeper: fill in how the distribution ended

    def won_ball(self, winner, t, etype, loser, reason):
        """A defender takes the ball. Defending events are recorded in the attacker's frame."""
        team = int(self.team_of[winner])
        self.emit(t, etype, team, winner, loser, self.ball, reason=reason)
        self.carrier, self.poss = winner, team
        self.carry = None
        self.runs = {}
        self.in_box = [False, False]
        self.ball = self.pos[winner].copy()
        self.next_decision = t + self.rng.uniform(0.8, 1.6)
        if winner == self.gk(team):
            self.keeper_trigger, self.keeper_since = "back_pass", t

    def check_tackle(self, t):
        c = self.carrier
        team = int(self.team_of[c])
        opponents = [i for i in self.team_idx[1 - team] if self.active[i]]
        gaps = np.linalg.norm(self.pos[opponents] - self.pos[c], axis=1)
        k = int(gaps.argmin())
        if gaps[k] < 1.8:
            i = int(opponents[k])
            if self.slot[i] == "GK":
                return
            roll = self.rng.random()
            tackle = TACKLE_RATE * TICK * self.tackling[i] / (0.35 + self.control[c])
            if roll < tackle:
                self.won_ball(i, t, "tackle", loser=team, reason="tackle")
            elif roll < tackle + self.foul_chance(i, c, t):          # sim_stops: a late or mistimed challenge
                self.commit_foul(t, i, c)

    def update_box(self, t):
        if self.dead or self.carrier < 0:
            return
        team = int(self.team_of[self.carrier])
        b = self.f(team, self.pos[self.carrier])
        inside = b[0] >= BOX_X and BOX_Y0 <= b[1] <= BOX_Y1
        if inside and not self.in_box[team] and self.slot[self.carrier] != "GK":
            self.emit(t, "box_entry", team, self.carrier, team, self.pos[self.carrier])
        self.in_box[team] = inside

    # ---------- kickoff ----------

    def kickoff(self, team, t):
        """Everyone back to their formation spots (a jump, used at the start of a half);
        `team` kicks off from the center."""
        for tm in (0, 1):
            idx = self.team_idx[tm]
            spots = self.anchor[idx].copy()
            spots[:, 0] = np.minimum(spots[:, 0], 52.0 if tm == team else 42.5)
            self.pos[idx] = self.f(tm, spots)
        self.pos[~self.active] = PARK
        self.vel[:] = 0
        self.place_kicker(team, t, jump=True)

    def place_kicker(self, team, t, jump=False):
        kickers = [i for i in self.team_idx[team] if self.role[i] == "ST" and self.active[i]] or self.outfield(team)
        kicker = min(kickers, key=lambda i: np.linalg.norm(self.pos[i] - [PITCH_L / 2, PITCH_W / 2]))
        self.pos[kicker] = [PITCH_L / 2, PITCH_W / 2]
        self.vel[kicker] = 0
        self.ball = self.pos[kicker].copy()
        self.carrier, self.poss = kicker, team
        self.flight = self.carry = self.dead = None
        self.runs = {}
        self.in_box = [False, False]
        self.next_decision = t + 1.5

    # ---------- one step, and the whole match ----------

    def step(self, t):
        if self.dead:
            self.fetch_ball()                                 # sim_stops: the ball is brought back to the restart spot
            if t >= self.dead["until"]:
                self.restart(t)                               # sim_stops: take the throw-in, corner, free kick...
            self.dead_time += TICK
        elif self.flight:
            self.fly(t)
        elif self.carrier >= 0:
            self.ball = self.pos[self.carrier].copy()
            self.check_tackle(t)
            if self.carrier >= 0:
                if self.carry and t >= self.carry["until"]:
                    self.carry = None
                if t >= self.next_decision and not self.carry:
                    if self.slot[self.carrier] == "GK":
                        self.keeper_play(t)                   # sim_keeper: the keeper plays the ball
                    else:
                        self.decide(t)
        if not self.dead:
            self.poss_time[self.poss] += TICK
            self.maybe_injury(t)                              # sim_stops
        tgt, urgency = self.targets(t)
        self.move(tgt, urgency)
        if not self.dead and not self.flight and self.carrier >= 0:
            self.ball = self.pos[self.carrier].copy()
        self.update_box(t)

    def run(self):
        t = 0.0
        self.kickoff(0, t)
        while True:
            self.check_half(t)                                # sim_stops: added time, half time, full time
            if self.finished:
                break
            self.step(t)
            self.rec_players.append(self.pos.copy())
            self.rec_ball.append(self.ball.copy())
            self.rec_half.append(self.half)
            self.rec_times.append(t)
            self.rec_who.append(self.who.copy())
            t += TICK
        return self.finish()

    def finish(self):
        self.add_off_ball_runs()                              # sim_stops: sprints into the box before shots
        events = sorted(self.events, key=lambda e: e["t"])    # a stable sort keeps the order within a second
        ids = {e["_k"]: i for i, e in enumerate(events)}
        for i, e in enumerate(events):
            e["id"] = i
            for ref in ("related_to", "assist_id", "shot_id", "run_for"):  # emission keys -> final ids
                if e.get(ref) is not None:
                    e[ref] = ids[e[ref]]
        for e in events:
            e.pop("_k", None)
        self.mark_led_to_shot(events)                         # sim_keeper: did a distribution start an attack?
        home, away = self.teams[0]["name"], self.teams[1]["name"]
        live = len(self.rec_times) * TICK - self.dead_time
        total = max(1e-9, sum(self.poss_time))
        match = {"match_id": f"SIM-{self.seed:03d}", "home": home, "away": away, "seed": self.seed,
                 "engine": "position-based, stage 2",
                 "final_score": {home: self.score[0], away: self.score[1]},
                 "pitch": {"length_m": 105, "width_m": 68, "goal_width_m": 7.32, "goal_height_m": 2.44},
                 "formations": {t["name"]: t["formation"] for t in self.teams},
                 "keepers": {t["name"]: t["players"][0]["name"] for t in self.teams},
                 "tactics": {t["name"]: t["tactics"] for t in self.teams},
                 "possession_pct": {home: round(100 * self.poss_time[0] / total, 1),
                                    away: round(100 * self.poss_time[1] / total, 1)},
                 "added_time_s": {"first_half": round(self.added.get(1, 0.0)), "second_half": round(self.added.get(2, 0.0))},
                 "live_minutes": round(live / 60, 1), "tracking": "sim_tracking.npz",
                 "coordinate_note": ("Most events are in the attacking team's frame: attacking toward x=105, "
                                     "goal centered at y=34. Defending events (tackle, possession_change, saves, "
                                     "claims) are in the attacker's frame. keeper_distribution events are in the "
                                     "distributing team's own frame. Tracking is in absolute pitch coordinates.")}
        tracking = {
            "times": np.array(self.rec_times, dtype=np.float32),
            "players": np.round(np.array(self.rec_players) * 100).astype(np.int16),
            "ball": np.round(np.array(self.rec_ball) * 100).astype(np.int16),
            "half": np.array(self.rec_half, dtype=np.uint8),
            "who": np.array(self.rec_who, dtype=np.int8),
            "names": np.array(self.names), "slots": np.array(self.slot), "roles": np.array(self.role),
            "teams": np.array([self.teams[i]["name"] for i in self.team_of]),
            "roster_names": np.array(self.roster_names),
            "roster_teams": np.array([self.teams[i]["name"] for i in self.roster_team]),
            "home": np.array(home), "away": np.array(away), "hz": np.array(1 / TICK),
        }
        return {"match": match, "events": events, "tracking": tracking}


def simulate(seed):
    """Play one match. Returns {"match", "events", "tracking"}. The same seed gives the same match."""
    return Engine(seed).run()


def save(result, events_path="sim_events.json", tracking_path="sim_tracking.npz"):
    with open(events_path, "w") as f:
        json.dump({"match": result["match"], "events": result["events"]}, f, indent=1)
    np.savez_compressed(tracking_path, **result["tracking"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    started = time.time()
    result = simulate(args.seed)
    save(result)
    kinds = {}
    for e in result["events"]:
        kinds[e["type"]] = kinds.get(e["type"], 0) + 1
    print(f"seed {args.seed}: {len(result['events'])} events in {time.time() - started:.1f} s", kinds)
    print("score:", result["match"]["final_score"], "| possession %:", result["match"]["possession_pct"],
          "| live minutes:", result["match"]["live_minutes"], "| added time:", result["match"]["added_time_s"])
