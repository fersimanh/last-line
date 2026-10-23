"""Tracking loader: where all 22 players and the ball were, at any second.

The engine saves a tracking file (see sim_engine.py): every 0.5 seconds, the
position of every player and the ball, in ABSOLUTE pitch coordinates (meters,
x 0-105 along the pitch, y 0-68 across). The home team attacks toward +x in the
first half; the sides swap at half time.

    tracking = Tracking("sim_tracking.npz")
    now = tracking.positions_at(1234.5)             # interpolated; {"players", "ball", "half"}
    mine = tracking.to_team_frame(now["players"], "Harbor United", now["half"])

Frames. A team's frame has that team attacking toward x = 105 with its own goal at
x = 0. The EVENT frame of a possession is the frame of the team attacking, and the
KEEPER frame of a followed keeper is the frame of the keeper's team, so one
function converts to both.
"""
import numpy as np

PITCH_L, PITCH_W = 105.0, 68.0
GAP_SECONDS = 1.0   # across a bigger hole in the samples (half time) positions are not blended


class Tracking:
    def __init__(self, path="tracking.npz"):
        z = np.load(path, allow_pickle=False)
        self.times = z["times"].astype(float)                 # seconds, one per sample
        self.players = z["players"].astype(float) / 100.0      # (samples, 22, 2) meters
        self.ball = z["ball"].astype(float) / 100.0            # (samples, 2) meters
        self.half = z["half"].astype(int)                      # 1 or 2, one per sample
        self.names = [str(n) for n in z["names"]]              # 22 player names
        self.teams = [str(n) for n in z["teams"]]              # the team of each of the 22
        self.roles = [str(n) for n in z["roles"]]
        self.slots = [str(n) for n in z["slots"]]
        self.home, self.away = str(z["home"]), str(z["away"])
        self.hz = float(z["hz"])
        # Substitutions: `who[k, slot]` is the roster entry standing in that slot at sample k.
        # Roster entries 0-21 are the starters; the rest are the benches.
        self.who = z["who"].astype(int) if "who" in z.files else np.tile(np.arange(22), (len(self.times), 1))
        self.roster_names = [str(n) for n in z["roster_names"]] if "roster_names" in z.files else list(self.names)
        self.roster_teams = [str(n) for n in z["roster_teams"]] if "roster_teams" in z.files else list(self.teams)

    # ---------- who is who ----------

    def indices(self, team):
        """The 11 player indices of a team."""
        return [i for i, t in enumerate(self.teams) if t == team]

    def index_of(self, name):
        """The slot (0-21) a player stands in. A substitute takes over the slot of the player he replaced."""
        if name in self.names:
            slot = self.names.index(name)
            if self.roster_names[slot] == name:
                return slot
        entry = self.roster_names.index(name)
        return int(np.argwhere(self.who == entry)[0][1])

    def names_at(self, seconds):
        """The 22 names on the pitch at a time (a substitute replaces the player he came on for)."""
        k = int(np.clip(np.searchsorted(self.times, seconds, side="right") - 1, 0, len(self.times) - 1))
        return [self.roster_names[w] for w in self.who[k]]

    def on_pitch(self, seconds):
        """Boolean per slot: False for a player who has been sent off (he is parked off the pitch)."""
        return self.positions_at(seconds)["players"][:, 1] >= 0.0

    # ---------- where everyone is ----------

    def positions_at(self, seconds):
        """Everyone's position at a time, interpolated between the 0.5 s samples.
        Returns {"players": (22, 2), "ball": (2,), "half": 1 or 2}."""
        seconds = float(np.clip(seconds, self.times[0], self.times[-1]))
        k = int(np.searchsorted(self.times, seconds, side="right")) - 1
        k = min(max(k, 0), len(self.times) - 2)
        t0, t1 = self.times[k], self.times[k + 1]
        same_half = self.half[k] == self.half[k + 1]
        w = 0.0 if (not same_half or t1 - t0 > GAP_SECONDS or t1 == t0) else (seconds - t0) / (t1 - t0)
        return {"players": self.players[k] * (1 - w) + self.players[k + 1] * w,
                "ball": self.ball[k] * (1 - w) + self.ball[k + 1] * w,
                "half": int(self.half[k])}

    # ---------- frames ----------

    def attack_dir(self, team, half):
        """+1 if the team attacks toward x = 105 (absolute) in this half, else -1."""
        first = 1 if team == self.home else -1
        return first if half == 1 else -first

    def to_team_frame(self, points, team, half):
        """Absolute points -> the team's attacking frame (own goal at x = 0).
        The same call converts back, because flipping twice does nothing."""
        pts = np.asarray(points, dtype=float)
        if self.attack_dir(team, half) == 1:
            return pts
        return np.stack([PITCH_L - pts[..., 0], PITCH_W - pts[..., 1]], axis=-1)

    def half_at(self, seconds):
        return self.positions_at(seconds)["half"]

    def to_event_frame(self, points, attacking_team, seconds):
        """Absolute points -> the frame an event by `attacking_team` is recorded in."""
        return self.to_team_frame(points, attacking_team, self.half_at(seconds))

    def to_keeper_frame(self, points, followed_team, seconds):
        """Absolute points -> the followed keeper's frame (own goal at x = 0, y = 34).
        This is the followed team's own frame, i.e. the same as the event frame
        of that team."""
        return self.to_team_frame(points, followed_team, self.half_at(seconds))

    def players_in_frame(self, seconds, team):
        """All 22 players at a time, in a team's frame: (22, 2)."""
        now = self.positions_at(seconds)
        return self.to_team_frame(now["players"], team, now["half"])
