"""Perception: the match as the followed goalkeeper experiences it.

The keeper's field of view is the INPUT, not an overlay. PerceptionFilter is
the one gateway to the match for everything downstream (agents, pipeline,
insight text, and soon the app). It replays the match in time order and sorts
every event into one of two piles:

  perceived  PerceivedEvent objects: what the keeper knows. Each has a `sight`:
               "own"   the keeper's own action (save, claim, sweep, distribution)
               "seen"  inside the keeper's sightline when it happened (vision.py)
               "felt"  not seen, but impossible to miss: a shot that reaches
                       the keeper's goal, or any goal (the crowd, the restart)
  missed     the missed log: everything else, with why it was missed
             (beyond_radius, outside_fov, or blocked by a body). It is
             for the Reveal view only. It must never reach the agents
             (test_architecture.py checks this).

Distributions are filtered too: a passing option outside the keeper's
sightline is removed from the perceived event and counted in
`unseen_options`; the missed log keeps the full list.

The keeper's own picture of the match (`state`) is a scoring.MatchState fed
with perceived events only.
"""
import hashlib
import math
from bisect import bisect_right
from dataclasses import dataclass, field

import vision
from replay import is_key_moment, load_match
from scoring import MatchState

MATCH_PATH = "match_events.json"
KEEPER_OWN_TYPES = ("keeper_save", "keeper_claim", "keeper_sweep", "keeper_close_down",
                    "keeper_distribution")
BALL_MOVE_TYPES = ("pass", "through_ball", "cross", "box_entry")   # the ball travels to the next event
OWN_THIRD_X = 35.0       # a pass starting below this (in its team's attacking frame) is in its own third
PRESSURE_RADIUS_M = 6.0  # opponents this close to a pass count as pressure


def match_fingerprint(path=MATCH_PATH):
    """A short code that changes whenever the match file changes."""
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def match_info(path=MATCH_PATH):
    """The match metadata (teams, final score, pitch), without any events."""
    match, _ = load_match(path)
    return match


def second_of(event):
    return event["minute"] * 60 + event["second"]


def clock_of(event):
    """The clock a fan sees (45+2:10, second half from 45:00); older match files have only minute and second."""
    return event.get("clock") or f"{event['minute']:02d}:{event['second']:02d}"


def direction_of(dx, dy):
    """forward, lateral or backward, for a ball moving (dx, dy) in its team's attacking frame."""
    if dx < -2:
        return "backward"
    return "lateral" if abs(dy) > dx else "forward"


def keeper_team_of(event, match):
    """Which keeper a key moment belongs to. Claims, sweeps and distributions
    are made by the keeper's own team; shots and goals come from the other team."""
    if event["type"] in ("keeper_claim", "keeper_sweep", "keeper_close_down", "keeper_distribution"):
        return event["team"]
    return match["away"] if event["team"] == match["home"] else match["home"]


@dataclass
class PerceivedEvent:
    """One event as the followed keeper perceives it."""
    event: dict            # the event; for distributions, only the options the keeper could see
    sight: str             # "own", "seen" or "felt"
    followed_team: str     # whose keeper is perceiving
    position: tuple        # where it happened, keeper frame (own goal at x = 0, y = 34)
    keeper_pos: tuple      # where the keeper stood
    facing: float          # degrees the keeper was facing just before it (0 = up the pitch)
    distance_m: float      # keeper to event
    unseen_before: int     # events missed since the previous perceived event
    key_moment: bool       # a key moment for THIS keeper: a save or goal at their goal,
                           # or their claim, sweep or notable distribution
    insight: dict = field(default_factory=dict)  # scoring insight, from the perceived picture

    @property
    def second(self):
        return second_of(self.event)


@dataclass
class MissedEvent:
    """An entry in the missed log: something the keeper did not perceive."""
    event: dict
    reason: str            # "beyond_radius", "outside_fov", "blocked" or "unseen_option"
    keeper_pos: tuple
    facing: float
    distance_m: float


class PerceptionFilter:
    """Replays the match through one keeper's eyes.

    f = PerceptionFilter("Harbor United")
    for pe in f.advance(upto_sec=600):   # perceived events up to 10:00
        ...
    f.unseen_count()                     # how many events the keeper missed so far
    f.state.keeper_report()              # the keeper's own picture of the numbers
    """

    def __init__(self, followed_team, path=MATCH_PATH,
                 fov_deg=vision.DEFAULT_FOV_DEG, radius_m=vision.DEFAULT_RADIUS_M):
        self.match, events = load_match(path)
        if followed_team not in (self.match["home"], self.match["away"]):
            raise ValueError(f"{followed_team} is not playing in this match")
        self.followed_team = followed_team
        self.fov_deg, self.radius_m = fov_deg, radius_m
        self._events = events
        self._timeline = vision.build_timeline(events, followed_team)
        self._seconds = [second_of(e) for e in events]   # for finding "the event at second t"
        self._index = {}                  # event id -> ("perceived", PerceivedEvent) or ("missed", MissedEvent)
        self._assist_shot = {e["assist_id"]: e["id"] for e in events if e["type"] == "shot"}
        self._keeper_name = None
        self._next = 0                    # index of the next event to replay
        self.state = MatchState(self.match["home"], self.match["away"])
        self.perceived = []               # PerceivedEvent, in time order
        self.missed = []                  # the missed log (Reveal view only)
        self.score = "0-0"                # goals are always felt, so the score is always known

    # ---------- deciding what the keeper perceives ----------

    def _sight(self, event, entry):
        """'own', 'seen' or 'felt', or None when the keeper missed it."""
        if event["type"] in KEEPER_OWN_TYPES and event["team"] == self.followed_team:
            return "own"
        if vision.was_seen(entry, self.fov_deg, self.radius_m):
            return "seen"
        at_my_goal = event["type"] == "shot" and event["team"] != self.followed_team
        if event["type"] == "goal" or (at_my_goal and event["outcome"] in ("goal", "saved")):
            return "felt"
        return None

    def _missed_reason(self, entry):
        if entry["distance_m"] > self.radius_m:
            return "beyond_radius"
        if entry["off_axis"] > self.fov_deg / 2:
            return "outside_fov"
        return "blocked"  # in range and in the cone, but a body stood in the sightline

    def _filter_options(self, event, entry):
        """Keep only the passing options inside the keeper's sightline. The
        keeper scans up the pitch from where they stand (see generate_match.py)."""
        seen = [o for o in event["options"] if o.get("visible", True)]
        for o in event["options"]:
            if not o.get("visible", True):
                self.missed.append(MissedEvent(dict(o, type="option", of_event=event["id"]),
                                               "unseen_option", entry["keeper"],
                                               entry["facing_before"], 0.0))
        return dict(event, options=seen, unseen_options=len(event["options"]) - len(seen))

    # ---------- replaying ----------

    def advance(self, upto_sec=None):
        """Replay events up to `upto_sec` (or to the end), continuing from where
        the last call stopped. Yields each new PerceivedEvent."""
        unseen = 0
        while self._next < len(self._events):
            event = self._events[self._next]
            if upto_sec is not None and second_of(event) > upto_sec:
                break
            entry = self._timeline[self._next]
            self._next += 1
            sight = self._sight(event, entry)
            if sight is None:
                self.missed.append(MissedEvent(event, self._missed_reason(entry), entry["keeper"],
                                               entry["facing_before"], entry["distance_m"]))
                self._index[event["id"]] = ("missed", self.missed[-1])
                unseen += 1
                continue
            if event["type"] == "keeper_distribution":
                event = self._filter_options(event, entry)
            if event["type"] == "goal":
                self.score = event["score"]
            pe = PerceivedEvent(event=event, sight=sight, followed_team=self.followed_team,
                                position=entry["pos"], keeper_pos=entry["keeper"],
                                facing=entry["facing_before"], distance_m=entry["distance_m"],
                                unseen_before=unseen,
                                key_moment=(is_key_moment(event) and
                                            keeper_team_of(event, self.match) == self.followed_team),
                                insight=self.state.update(event))
            unseen = 0
            self.perceived.append(pe)
            self._index[event["id"]] = ("perceived", pe)
            yield pe

    def advance_all(self, upto_sec=None):
        """Same as advance(), but runs it through and returns the new events as a list."""
        return list(self.advance(upto_sec))

    def unseen_count(self, since_sec=None, until_sec=None):
        """How many events the keeper missed (unseen options not counted),
        optionally only between two match seconds."""
        return sum(1 for m in self.missed if m.reason != "unseen_option"
                   and (since_sec is None or second_of(m.event) >= since_sec)
                   and (until_sec is None or second_of(m.event) <= until_sec))

    # ---------- what the screen needs ----------

    def keeper_name(self):
        """The followed keeper's name."""
        if self._keeper_name is None:
            named = self.match.get("keepers", {}).get(self.followed_team)    # the match file may say so
            self._keeper_name = named or next(e["player"] for e in self._events
                                              if e["team"] == self.followed_team and e["type"].startswith("keeper_"))
        return self._keeper_name

    def state_at(self, upto_sec):
        """The keeper's surroundings at a match second: where they stand, where
        the ball is (a keeper always tracks the ball, seen or not), and the
        direction they face. Positions are in the keeper frame."""
        i = bisect_right(self._seconds, upto_sec) - 1
        keeper = self._timeline[i]["keeper"] if i >= 0 else vision.DEFAULT_KEEPER
        ball = self._timeline[i]["ball"] if i >= 0 else (vision.PITCH_LENGTH / 2, vision.PITCH_WIDTH / 2)
        return {"keeper": keeper, "ball": ball, "facing": vision.facing_angle(keeper, ball)}

    def recent(self, n, upto_sec, include_missed=False, upto_id=None):
        """The last `n` events up to a match second (and, if given, up to an
        event id), oldest first. Each is a dict with `event`, `sight` ("own",
        "seen", "felt", or "missed" when include_missed is on), `position`
        (keeper frame), `distance_m` and `reason` (why it was missed, else
        None). Missed events are only included for the Reveal view."""
        def in_range(event):
            return second_of(event) <= upto_sec and (upto_id is None or event["id"] <= upto_id)
        rows = [{"event": pe.event, "sight": pe.sight, "position": pe.position,
                 "distance_m": pe.distance_m, "reason": None}
                for pe in self.perceived if in_range(pe.event)][-n:]
        if include_missed:
            rows += [{"event": m.event, "sight": "missed", "position": self._timeline[m.event["id"]]["pos"],
                      "distance_m": m.distance_m, "reason": m.reason}
                     for m in self.missed
                     if m.reason != "unseen_option" and in_range(m.event)][-n:]
            rows = sorted(rows, key=lambda r: r["event"]["id"])[-n:]
        return rows

    # ---------- picking one event to inspect ----------

    def lookup(self, event_id, reveal=False):
        """One event the user may select, or None. An event is selectable when it
        has happened and the keeper perceived it; with `reveal` on (the Reveal
        view only), missed events are selectable too. Returns a dict with
        `event`, `sight`, `reason`, `position`, `distance_m`, `keeper_pos`,
        `facing`, `unseen_before`, `insight` and `key_moment`."""
        found = self._index.get(event_id)
        if found is None:
            return None  # it has not happened yet
        kind, item = found
        if kind == "perceived":
            return {"event": item.event, "sight": item.sight, "reason": None, "position": item.position,
                    "distance_m": item.distance_m, "keeper_pos": item.keeper_pos, "facing": item.facing,
                    "unseen_before": item.unseen_before, "insight": item.insight,
                    "key_moment": item.key_moment}
        if not reveal:
            return None  # missed, and not in Reveal: the keeper never perceived it
        return {"event": item.event, "sight": "missed", "reason": item.reason,
                "position": self._timeline[event_id]["pos"], "distance_m": item.distance_m,
                "keeper_pos": item.keeper_pos, "facing": item.facing, "unseen_before": 0,
                "insight": {}, "key_moment": False}

    def can_select(self, event_id, upto_sec, reveal=False):
        """May this event be picked at this moment? It must have happened, and the
        keeper must have perceived it (Reveal: any event)."""
        row = self.lookup(event_id, reveal)
        return row is not None and second_of(row["event"]) <= upto_sec

    def selectable_ids(self, upto_sec, reveal=False):
        """The ids of every event the user may select up to a match second, oldest first."""
        ids = [pe.event["id"] for pe in self.perceived if pe.second <= upto_sec]
        if reveal:
            ids += [m.event["id"] for m in self.missed
                    if m.reason != "unseen_option" and second_of(m.event) <= upto_sec]
        return sorted(ids)

    def snapshot(self, event_id):
        """The keeper's surroundings at one event: where they stood, which way they
        were facing just BEFORE it (toward where the ball had been), and the ball."""
        entry = self._timeline[event_id]
        return {"keeper": entry["keeper"], "ball": entry["ball"], "facing": entry["facing_before"]}

    def window_summary(self, event_id, window_sec=30):
        """How much the keeper saw and missed in the `window_sec` seconds before an
        event: counts, plus the missed events themselves (for the Reveal view)."""
        sec = second_of(self._events[event_id])
        in_window = lambda e: sec - window_sec <= second_of(e) <= sec and e["id"] < event_id
        missed = [m for m in self.missed if m.reason != "unseen_option" and in_window(m.event)]
        return {"seen": sum(1 for pe in self.perceived if in_window(pe.event)),
                "missed": len(missed), "missed_events": missed}

    def _relevant_keeper(self, event):
        """The keeper this event matters to most. Key-moment types belong to the
        keeper they happen to; for the ball moving or a tackle it is whoever
        defends the nearer goal."""
        home, away = self.match["home"], self.match["away"]
        other = lambda team: away if team == home else home
        if event["type"] in BALL_MOVE_TYPES + ("tackle", "possession_change"):
            attacker = event["team"] if event["type"] in BALL_MOVE_TYPES else other(event["team"])
            return other(attacker) if event["x"] >= vision.PITCH_LENGTH / 2 else attacker
        return keeper_team_of(event, self.match)

    def _text_event_id(self, event):
        """The id the explanation text is stored under: a scored shot is explained
        together with its goal, a save together with its shot."""
        if event["type"] == "shot" and event["outcome"] == "goal":
            goal = next((e for e in self._events[event["id"] + 1:event["id"] + 4]
                         if e["type"] == "goal" and e["related_to"] == event["id"]), None)
            return goal["id"] if goal else event["id"]
        if event["type"] == "keeper_save":
            return event["related_to"]
        return event["id"]

    def _known(self, event, reveal, upto_sec):
        """May this event be used as a fact? Yes if it has happened by `upto_sec`
        and (in Reveal) it exists, or (in Keeper's eyes) the keeper perceived it."""
        if upto_sec is not None and second_of(event) > upto_sec:
            return False
        if reveal:
            return True
        found = self._index.get(event["id"])
        return found is not None and found[0] == "perceived"

    def _ball_move(self, event, reveal, upto_sec):
        """Facts about a ball-moving event, worked out from the NEXT event (the
        data has no pass destination, so the ball's next position is it). Anything
        that depends on an event the keeper did not perceive is left as None."""
        own = event["team"]
        nxt = self._events[event["id"] + 1] if event["id"] + 1 < len(self._events) else None
        info = {"distance_m": None, "forward_m": None, "direction": None, "outcome": None,
                "leads_to_shot": None, "own_third": event["x"] < OWN_THIRD_X, "pressure": None}
        if nxt is not None and self._known(nxt, reveal, upto_sec) and not (
                nxt["type"] == "keeper_distribution" and nxt["team"] != own):
            dx, dy = nxt["x"] - event["x"], nxt["y"] - event["y"]
            info.update(distance_m=round(math.hypot(dx, dy), 1), forward_m=round(dx, 1),
                        direction=direction_of(dx, dy))
            if nxt["team"] == own:
                info["outcome"] = "shot" if nxt["type"] == "shot" else "completed"
            elif nxt["type"] in ("tackle", "possession_change"):
                info["outcome"] = "lost"
            elif nxt["type"] in ("keeper_claim", "keeper_sweep", "keeper_save"):
                info["outcome"] = "keeper"
        shot_id = self._assist_shot.get(event["id"])
        if shot_id is not None and self._known(self._events[shot_id], reveal, upto_sec):
            info["leads_to_shot"] = True
        elif shot_id is None:
            info["leads_to_shot"] = False
        if "traffic" in event:   # only events in the attacking third carry the players around them
            near = sum(1 for b in event["traffic"] if b["team"] != own
                       and math.hypot(b["x"] - event["x"], b["y"] - event["y"]) <= PRESSURE_RADIUS_M)
            info["pressure"] = "low" if near == 0 else "medium" if near == 1 else "high"
        return info

    def facts(self, event_id, reveal=False, upto_sec=None):
        """Everything known about one event, for the inspector and the agents, or
        None if it is not selectable (see lookup). With `reveal` off, nothing
        the keeper did not perceive is included; `upto_sec` hides what has not
        happened yet. The missed log is never part of it."""
        row = self.lookup(event_id, reveal)
        if row is None:
            return None
        event = row["event"]
        shot_ref = None
        if event["type"] in ("goal", "keeper_save"):   # explained together with their shot
            shot = self.lookup(event["related_to"], True)
            if shot is not None:
                shot_ref = {"event": shot["event"], "insight": shot["insight"]}
        facts = {
            "id": event_id, "clock": clock_of(event), "second": second_of(event),
            "type": event["type"], "team": event["team"], "player": event["player"],
            "receiver": event.get("receiver"), "sight": row["sight"], "reason": row["reason"],
            "position": row["position"], "distance_m": round(row["distance_m"], 1),
            "keeper_off_line_m": round(row["keeper_pos"][0], 1), "keeper_name": self.keeper_name(),
            "keeper_team": self.followed_team, "relevant_keeper": self._relevant_keeper(event),
            "text_event_id": self._text_event_id(event), "unseen_before": row["unseen_before"],
            "key_moment": row["key_moment"], "insight": row["insight"], "event": event,
            "shot_ref": shot_ref,
            "ball_move": (self._ball_move(event, reveal, upto_sec)
                          if event["type"] in BALL_MOVE_TYPES else None),
        }
        return facts

    def goal_seconds(self):
        """(match second, team) of every goal. Goals are always felt, so every
        keeper knows them all."""
        return [(pe.second, pe.event["team"]) for pe in self.perceived if pe.event["type"] == "goal"]

    def score_at(self, second):
        """The score at a match second, from the goals this keeper felt."""
        score = "0-0"
        for pe in self.perceived:
            if pe.second > second:
                break
            if pe.event["type"] == "goal":
                score = pe.event["score"]
        return score

    def find_perceived(self, event_id):
        """The perceived event with this id, or None if it was missed or is still ahead."""
        return next((pe for pe in self.perceived if pe.event["id"] == event_id), None)

    def reveal(self):
        """Every event replayed so far, perceived or missed, in time order, each
        with its sight ("own", "seen", "felt" or "missed"). FOR THE REVEAL VIEW
        ONLY: it contains the missed log, so it must never reach the agents."""
        rows = [(pe.event["id"], pe.sight, self._events[pe.event["id"]]) for pe in self.perceived]
        rows += [(m.event["id"], "missed", m.event) for m in self.missed if m.reason != "unseen_option"]
        return [(sight, event) for _, sight, event in sorted(rows, key=lambda r: r[0])]
