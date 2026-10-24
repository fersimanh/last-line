"""Insight text for the Last Line app, with a JSON cache.

The app asks for text with get_insight_text(moment, mode, language, club).
The answer comes from insight_cache.json when it is there (instant), from the
Foundry agents on a cache miss (slow, then cached), or from a plain fallback
line built from the saveability score if the agents are unavailable.

Fill the cache before a demo, so the app never waits on the agents:
    python3 insights.py --warm

This file also has replay_to(), which rebuilds the match state up to any
match second. The app calls it on every screen update. Everything here reads
the match through perception.PerceptionFilter, never the raw file: key
moments are the keepers' perceived key moments, and the full event list the
Reveal view needs comes from PerceptionFilter.reveal().

Views: "eyes" cards are written in the second person ("You're 4 m off your
line..."). The Reveal view reuses the same texts. Texts are cached per moment,
mode, club, language and view.
"""
import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timezone

import inspector
from inspector import DIST_VERDICT_ES, VERDICT_ES, second_person_text  # noqa: F401 (the app imports these from here)
from perception import PerceptionFilter, match_fingerprint, match_info
from replay import clock
from scoring import MatchState
from vision import DEFAULT_FOV_DEG, DEFAULT_RADIUS_M

CACHE_PATH = "insight_cache.json"
# Bump this when the agents' input changes, so older cached texts are dropped
TEXT_VERSION = "perception-2"
# Set LAST_LINE_LIVE_AGENTS=0 to never call the agents (cache or fallback only)
LIVE_AGENTS = os.getenv("LAST_LINE_LIVE_AGENTS", "1") == "1"

BOTH = "Both"                     # the "follow both keepers" club option
VIEWS = ("eyes",)                 # views with their own cached text (Reveal reuses "eyes")
STYLE_OF_VIEW = {"eyes": "second_person", "broadcast": "first_person"}
MODES = ["casual", "analyst"]
LANGUAGES = ["en", "es"]

KEEPER_OWN_EVENTS = ("keeper_claim", "keeper_sweep", "keeper_close_down", "keeper_distribution")


# ---------- Replaying the match ----------

def match_second(event):
    return event["minute"] * 60 + event["second"]


def keeper_team(event, state):
    """Which keeper a moment belongs to. Claims, sweeps and distributions are
    made by the keeper's own team; shots and goals come from the other team."""
    if event["type"] in KEEPER_OWN_EVENTS:
        return event["team"]
    return state.other(event["team"])


_filters = {}  # (match fingerprint, team, fov, sight range) -> a PerceptionFilter replayed to full time


def filter_for(team, fov_deg=DEFAULT_FOV_DEG, radius_m=DEFAULT_RADIUS_M):
    """One keeper's PerceptionFilter at a field of view and a sight range, replayed to
    full time once and reused. The app's sliders ask for other angles and ranges."""
    key = (match_fingerprint(), team, int(fov_deg), int(radius_m))
    if key not in _filters:
        f = PerceptionFilter(team, fov_deg=fov_deg, radius_m=radius_m)
        f.advance_all()
        _filters[key] = f
    return _filters[key]


def keeper_eyes(team):
    """The keeper's PerceptionFilter at the default sightline. Cached texts and
    key moments always use this one."""
    return filter_for(team, DEFAULT_FOV_DEG)


def perceived_state(team, fov_deg, upto_sec, radius_m=DEFAULT_RADIUS_M):
    """The keeper's own picture of the match at a second: a MatchState fed with
    only what they perceived (workload, danger and numbers as they know them)."""
    f = filter_for(team, fov_deg, radius_m)
    state = MatchState(f.match["home"], f.match["away"])
    for pe in f.perceived:
        if pe.second > upto_sec:
            break
        state.update(pe.event)
    return state


def match_end_second():
    match = match_info()
    return max(match_second(event) for _, event in keeper_eyes(match["home"]).reveal())


def replay_to(match, events, upto_sec):
    """The match up to `upto_sec` match seconds, read through PerceptionFilter.
    (`events` is no longer used; it stays so callers keep working.)
    Returns (state, shots, moments, score):
      state   - a scoring.MatchState with workload, danger and keeper stats for
                the Broadcast view (built from reveal(): the official numbers)
      shots   - every shot so far, each {"event", "insight", "keeper_team"}
      moments - every key moment so far, from each keeper's PERCEIVED events
                (see make_moment), oldest first
      score   - "home-away", e.g. "1-2"
    """
    filters = [keeper_eyes(match["home"]), keeper_eyes(match["away"])]

    # The Broadcast view's official picture: every event, from reveal()
    state = MatchState(match["home"], match["away"])
    shots, score = [], "0-0"
    for _, event in filters[0].reveal():
        if match_second(event) > upto_sec:
            break
        insight = state.update(event)
        if event["type"] == "shot":
            shots.append({"event": event, "insight": insight,
                          "keeper_team": keeper_team(event, state)})
        if event["type"] == "goal":
            score = event["score"]

    # Key moments: what each keeper perceived
    perceived = sorted((pe for f in filters for pe in f.perceived
                        if pe.key_moment and pe.second <= upto_sec),
                       key=lambda pe: (pe.second, pe.event["id"]))
    moments = [make_moment(pe, filters) for pe in perceived]
    return state, shots, moments, score


def make_moment(pe, filters):
    """A key moment (a PerceivedEvent) as a plain dict. A goal takes its
    numbers and its clock from the shot that caused it, so a 67:04 'goal'
    shows as 67:03."""
    event, insight, timed = pe.event, pe.insight, pe.event
    keeper_filter = next(f for f in filters if f.followed_team == pe.followed_team)
    if event["type"] == "goal":
        shot = keeper_filter.find_perceived(event["related_to"])
        insight, timed = shot.insight, shot.event
    distribution = None
    if event["type"] == "keeper_distribution":
        distribution = {k: event[k] for k in (
            "trigger", "method", "technique", "target_player", "target_role", "distance_m",
            "direction", "pressure", "reason", "outcome", "x_gain_m", "led_to_shot")}
        distribution["unseen_options"] = event.get("unseen_options", 0)
        distribution["options_seen"] = len(event["options"])
        distribution.update({k: insight[k] for k in (
            "difficulty", "decision_score", "quality", "verdict", "best_option")})
        insight = dict(insight, verdict=None)  # "verdict" below is the shot verdict only
    return {
        "event_id": event["id"],
        "clock": clock(timed),
        "second": match_second(timed),
        "type": event["type"],                 # shot (saved), goal, keeper_claim, keeper_sweep
        "team": event["team"],
        "player": event["player"],
        "keeper": insight.get("keeper", event["player"]),
        "keeper_team": pe.followed_team,
        "sight": pe.sight,                     # own, seen or felt
        "saveability": insight.get("saveability"),
        "verdict": insight.get("verdict"),
        "key_factor": insight.get("key_factor"),
        "situation": insight.get("situation"),  # shots and goals only, e.g. "rebound"
        "shot": ({k: timed.get(k) for k in ("distance_m", "speed_kmh", "body_part")}
                 if timed["type"] == "shot" else None),
        "keeper_off_line_m": round(pe.keeper_pos[0], 1),   # how far the keeper stood from their line
        "event_distance_m": round(pe.distance_m, 1),       # keeper to the event
        "unseen_before": pe.unseen_before,                 # events missed just before this one
        "distribution": distribution,          # None unless type is keeper_distribution
        "score": keeper_filter.score_at(pe.second),
    }


# ---------- The cache file ----------

_cache = {}
_cache_mtime = None


def cache_fingerprint():
    """Cached texts are keyed by event id, so texts made for another match, or
    by an older version of the agents' input, must not be used. This code
    changes when either changes."""
    return f"{match_fingerprint()}-{TEXT_VERSION}"


def load_cache():
    """Read the cache file, but only again if it changed on disk. A cache made
    for a different match is ignored (and replaced on the next save)."""
    global _cache, _cache_mtime
    try:
        mtime = os.path.getmtime(CACHE_PATH)
    except OSError:
        mtime = None  # no file yet
    if mtime != _cache_mtime or not _cache:
        cache = {}
        if mtime is not None:
            with open(CACHE_PATH) as f:
                cache = json.load(f)
        if cache.get("_match") != cache_fingerprint():
            cache = {"_match": cache_fingerprint()}  # wrong or no match: start empty
        _cache, _cache_mtime = cache, mtime
    return _cache


def save_to_cache(key, text):
    cache = load_cache()
    cache[key] = {"text": text,
                  "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    # Write to a temporary file first, then swap, so a crash never leaves half a file
    with open(CACHE_PATH + ".tmp", "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(CACHE_PATH + ".tmp", CACHE_PATH)


def moment_key(event_id, mode, club, language, view="eyes"):
    return f"{event_id}|{mode}|{club}|{language}|{view}"


def report_key(team, mode, language):
    return f"full_time|{team}|{mode}|{language}"


def viewer_for(mode, club, language):
    """The viewer dict the pipeline expects. 'key_club' keeps the app's club
    choice (including "Both") so the warm-up knows which cache key to use."""
    return {"name": f"{mode}_{language}_{club}", "mode": mode, "language": language,
            "club": "none, a neutral fan following both keepers" if club == BOTH else club,
            "key_club": club}


# ---------- Text for one moment ----------

def fallback_text(moment, language, view="eyes"):
    """Plain line used when there is no agent text, built from the scoring fields."""
    spanish = language == "es"
    if view == "eyes":
        return second_person_text(moment, spanish)
    if moment["saveability"] is not None:
        if spanish:
            return f"Salvabilidad {moment['saveability']}/100: {VERDICT_ES[moment['verdict']]}."
        return (f"Saveability {moment['saveability']}/100: {moment['verdict']} "
                f"({moment['key_factor']}).")
    if moment["distribution"]:
        d = moment["distribution"]
        if spanish:
            return (f"{moment['player']} a {d['target_player']} ({d['target_role']}): "
                    f"calidad {d['quality']}/100, {DIST_VERDICT_ES[d['verdict']]}.")
        return (f"{moment['player']} {d['method'].replace('_', ' ')} to {d['target_role']} "
                f"{d['target_player']}: quality {d['quality']}/100, {d['verdict']} "
                f"({moment['key_factor']}).")
    if moment["type"] == "keeper_claim":
        return f"{moment['player']} {'atrapa el centro' if spanish else 'claims the cross'}."
    return f"{moment['player']} {'sale a despejar' if spanish else 'sweeps up the danger'}."


_failed = {}               # cache key -> when the agents last failed for it (see may_ask)
RETRY_AFTER_SEC = 600      # after a failure, do not ask the agents for the same text again for this long


def may_ask(key):
    """Should the app ask the agents for this text now? Not if they failed for it recently:
    without this, every click or setting change would wait for the same slow failure again."""
    return (LIVE_AGENTS and agents_configured()
            and time.time() - _failed.get(key, -1e9) > RETRY_AFTER_SEC)


def agents_configured():
    """Are the agents set up at all? Without PROJECT_ENDPOINT (a deployed copy with no key, say)
    the app never tries them: it shows the cache, or the quick text. Read each time, because
    the app loads .env after this module is imported."""
    return bool(os.getenv("PROJECT_ENDPOINT"))


def note_failure(key):
    _failed[key] = time.time()


def get_insight_text(moment, mode, language, club, view="eyes", live=True):
    """Text for one key moment. mode: "casual" or "analyst"; language: "en"
    or "es"; club: a club name or BOTH; view: "eyes" (second person) or
    "broadcast" (first person). Cache first, then the agents, then the
    fallback line. `live=False` never calls the agents (the app uses it while the
    match plays: a slow call would freeze the replay)."""
    key = moment_key(moment["event_id"], mode, club, language, view)
    cached = load_cache().get(key)
    if cached:
        return cached["text"]
    if live and may_ask(key):
        text = generate_moment_text(moment, viewer_for(mode, club, language), view)
        if text:
            save_to_cache(key, text)
            return text
        note_failure(key)
    return fallback_text(moment, language, view)


def generate_moment_text(moment, viewer, view="eyes"):
    """Run the agents for one moment and one viewer. Returns None on failure."""
    async def go():
        from pipeline import run  # imported here so the app starts without the agents
        async for item in run(only=moment["clock"], viewers=[viewer],
                              style=STYLE_OF_VIEW[view]):
            if item.get("event_id") == moment["event_id"]:
                version = item["versions"][0]
                return None if version["fallback"] else version["text"]
    try:
        return asyncio.run(go())
    except Exception:
        return None


# ---------- Text for any event the user clicks (the inspector) ----------

def ai_info(team, event_id):
    """Is this event one the agents explain for this keeper, and under which id
    is its text cached? Key moments are; so are the notable passes (see
    inspector.notable_reason) for the keeper they matter to. Decided from the full
    data at the default sightline, the one the cached texts were written for."""
    f = keeper_eyes(team)
    facts = f.facts(event_id, reveal=True)
    if facts is None:
        return None
    text_id = facts["text_event_id"]
    text_facts = facts if text_id == event_id else f.facts(text_id, reveal=True)
    why = inspector.notable_reason(text_facts)
    eligible = why is not None and (why == "key_moment" or text_facts["relevant_keeper"] == team)
    return {"eligible": eligible, "text_event_id": text_id, "why": why}


def get_event_text(team, facts, mode, language, club, view="eyes"):
    """The text for one clicked event, and where it came from: "ai" (cached or
    freshly generated by the agents) or "quick" (the instant template). Every
    event has a template; key moments and notable passes also have agent text."""
    template = inspector.template_text(facts, language)
    info = ai_info(team, facts["id"])
    if not info or not info["eligible"]:
        return template, "quick"
    key = moment_key(info["text_event_id"], mode, club, language, view)
    cached = load_cache().get(key)
    if cached:
        return cached["text"], "ai"
    if may_ask(key):
        text = generate_event_text(team, info["text_event_id"], viewer_for(mode, club, language), view)
        if text:
            save_to_cache(key, text)
            return text, "ai"
        note_failure(key)
    return template, "quick"


def generate_event_text(team, event_id, viewer, view="eyes"):
    """Run the agents for one event as seen through one keeper's eyes. Returns
    None on failure (no network, no sign-in, a timeout)."""
    async def go():
        from pipeline import run  # imported here so the app starts without the agents
        async for item in run(viewers=[viewer], style=STYLE_OF_VIEW[view], event_ids={event_id: team}):
            if item.get("event_id") == event_id:
                version = item["versions"][0]
                return None if version["fallback"] else version["text"]
    try:
        return asyncio.run(go())
    except Exception:
        return None


def notable_events():
    """Every event that gets an agent explanation but is not already a key moment:
    the notable passes and keeper passes, as {event_id, team, why, clock}, one
    keeper each (the one the event matters to). Decided from the full data."""
    found = []
    match = match_info()
    for team in (match["home"], match["away"]):
        f = keeper_eyes(team)
        for pe in f.perceived:
            facts = f.facts(pe.event["id"], reveal=True)
            why = inspector.notable_reason(facts)
            if why and why != "key_moment" and facts["relevant_keeper"] == team:
                found.append({"event_id": pe.event["id"], "team": team, "why": why, "clock": facts["clock"]})
    return sorted(found, key=lambda x: x["event_id"])


def viewers_for_team(team):
    """The viewers a team's texts are cached for: its fans and "Both", in each mode and language."""
    return [viewer_for(m, c, lang) for c in (team, BOTH) for m in MODES for lang in LANGUAGES]


def missing_viewers(event_id, team, view="eyes"):
    cache = load_cache()
    return [v for v in viewers_for_team(team)
            if moment_key(event_id, v["mode"], v["key_club"], v["language"], view) not in cache]


# ---------- Text for the full-time keeper report ----------

def get_report_text(team, mode, language):
    """The Narrator's full-time report for `team`'s keeper, adapted for the
    viewer. Returns None if it is not cached and the agents are unavailable."""
    key = report_key(team, mode, language)
    cached = load_cache().get(key)
    if cached:
        return cached["text"]
    if may_ask(key):
        text = generate_report_text(team, viewer_for(mode, team, language))
        if text:
            save_to_cache(key, text)
            return text
        note_failure(key)
    return None


async def report_texts(viewers):
    """Full-time report for each viewer (each hears their own club's keeper).
    Returns a list of texts, with None where the agents failed."""
    from agents import make_client, make_narrator, make_personalizer
    from pipeline import LiveMatch, keeper_report
    live = LiveMatch(match_info())
    live.replay_to_end()  # each keeper's perceived numbers at full time
    client = make_client()
    agents = (None, make_narrator(client), make_personalizer(client))  # no Analyst needed
    report = await keeper_report(live, agents, viewers, "full_time")
    return [None if v["fallback"] else v["text"] for v in report["versions"]]


def generate_report_text(team, viewer):
    try:
        return asyncio.run(report_texts([viewer]))[0]
    except Exception:
        return None


# ---------- Filling the cache ahead of a demo ----------

async def warm(views=VIEWS):
    """Run the whole match through the agents once per view, for every mode,
    club (both clubs plus Both) and language, and store every text."""
    from pipeline import run
    match = match_info()
    clubs = [match["home"], match["away"], BOTH]
    viewers = [viewer_for(m, c, lang) for m in MODES for c in clubs for lang in LANGUAGES]

    for view in views:
        async for item in run(viewers=viewers, style=STYLE_OF_VIEW[view]):
            stored = 0
            for version in item["versions"]:
                v = version["viewer"]
                if version["fallback"]:
                    continue
                if item["kind"] == "moment":
                    key = moment_key(item["event_id"], v["mode"], v["key_club"], v["language"], view)
                elif item["kind"] == "full_time" and v["key_club"] == version["keeper_team"]:
                    key = report_key(v["key_club"], v["mode"], v["language"])
                else:
                    continue  # halftime reports are not shown in the app yet
                save_to_cache(key, version["text"])
                stored += 1
            label = item.get("clock", item["kind"])
            print(f"[{view}] {label}: cached {stored} texts, {len(item['errors'])} errors", flush=True)

    # Agents sometimes fail for a moment (timeouts, rate limits): try those again
    await fill_missing(views)


async def fill_missing(views=VIEWS):
    """Generate only the texts the app needs that are not in the cache yet."""
    from pipeline import run
    match = match_info()
    _, _, moments, _ = replay_to(match, None, match_end_second())
    cache = load_cache()

    # Each moment is shown to fans of its keeper's club and to "Both" viewers
    for view in views:
        for moment in moments:
            viewers = [viewer_for(m, c, lang) for c in (moment["keeper_team"], BOTH)
                       for m in MODES for lang in LANGUAGES
                       if moment_key(moment["event_id"], m, c, lang, view) not in cache]
            if not viewers:
                continue
            stored = 0
            async for item in run(only=moment["clock"], viewers=viewers,
                                  style=STYLE_OF_VIEW[view]):
                if item.get("event_id") != moment["event_id"]:
                    continue
                for version in item["versions"]:
                    v = version["viewer"]
                    if not version["fallback"]:
                        save_to_cache(moment_key(item["event_id"], v["mode"], v["key_club"],
                                                 v["language"], view), version["text"])
                        stored += 1
            print(f"[{view}] {moment['clock']}: filled {stored} of {len(viewers)} missing texts",
                  flush=True)

    # The full-time report, for fans of each club
    viewers = [viewer_for(m, team, lang) for team in (match["home"], match["away"])
               for m in MODES for lang in LANGUAGES
               if report_key(team, m, lang) not in cache]
    if viewers:
        texts = await report_texts(viewers)
        for v, text in zip(viewers, texts):
            if text:
                save_to_cache(report_key(v["key_club"], v["mode"], v["language"]), text)
        print(f"full time: filled {sum(1 for x in texts if x)} of {len(viewers)} missing texts")


def plan_requests(views=VIEWS):
    """Count the agent requests still needed to fill the cache, without making any.
    Each event costs 1 Analyst + 1 Narrator request, plus 1 Personalizer request
    per viewer still missing. Returns {part: {"events": n, "requests": n}}."""
    cache = load_cache()
    match = match_info()
    plan = {part: {"events": 0, "requests": 0} for part in ("key moments", "notable passes", "reports")}

    def add(part, missing):
        if missing:
            plan[part]["events"] += 1
            plan[part]["requests"] += 2 + missing

    _, _, moments, _ = replay_to(match, None, match_end_second())
    for view in views:
        for moment in moments:
            add("key moments", sum(
                1 for c in (moment["keeper_team"], BOTH) for m in MODES for lang in LANGUAGES
                if moment_key(moment["event_id"], m, c, lang, view) not in cache))
        for item in notable_events():
            add("notable passes", len(missing_viewers(item["event_id"], item["team"], view)))
    for team in (match["home"], match["away"]):  # one Narrator request per team, one Personalizer per viewer
        missing = sum(1 for m in MODES for lang in LANGUAGES if report_key(team, m, lang) not in cache)
        if missing:
            plan["reports"]["events"] += 1
            plan["reports"]["requests"] += 1 + missing
    return plan


async def fill_notable(views=VIEWS):
    """Generate the agent texts for the notable passes and keeper passes that are
    not cached yet. Safe to stop and run again: events with all their texts
    cached are skipped. One replay per keeper, so it does not repeat the match
    for every event."""
    from pipeline import run
    for view in views:
        for team in (match_info()["home"], match_info()["away"]):
            todo = {}
            for item in notable_events():
                if item["team"] == team and missing_viewers(item["event_id"], team, view):
                    todo[item["event_id"]] = team
            if not todo:
                continue
            # one run per set of missing viewers keeps the requests down; most events share the same set
            groups = {}
            for event_id in todo:
                key = tuple(v["name"] for v in missing_viewers(event_id, team, view))
                groups.setdefault(key, []).append(event_id)
            for names, ids in groups.items():
                viewers = [v for v in viewers_for_team(team) if v["name"] in names]
                async for item in run(viewers=viewers, style=STYLE_OF_VIEW[view],
                                      event_ids={i: team for i in ids}):
                    stored = 0
                    for version in item["versions"]:
                        v = version["viewer"]
                        if not version["fallback"]:
                            save_to_cache(moment_key(item["event_id"], v["mode"], v["key_club"],
                                                     v["language"], view), version["text"])
                            stored += 1
                    print(f"[{view}] {item['clock']} ({team}): cached {stored} texts, "
                          f"{len(item['errors'])} errors", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--warm", action="store_true", help="fill the whole cache using the agents")
    parser.add_argument("--missing", action="store_true", help="fill only texts not cached yet")
    parser.add_argument("--view", choices=["eyes", "broadcast", "both"], default="eyes",
                        help="which view's texts to generate (default: eyes)")
    args = parser.parse_args()
    chosen = ("eyes", "broadcast") if args.view == "both" else (args.view,)
    if args.warm:
        asyncio.run(warm(chosen))
    elif args.missing:
        asyncio.run(fill_missing(chosen))
    else:
        parser.print_help()
