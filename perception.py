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
from dataclasses import dataclass, field

import vision
from replay import is_key_moment, load_match
from scoring import MatchState

MATCH_PATH = "match_events.json"
KEEPER_OWN_TYPES = ("keeper_save", "keeper_claim", "keeper_sweep", "keeper_close_down",
                    "keeper_distribution")


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
