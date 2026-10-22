"""Insight text for the Last Line app, with a JSON cache.

The app asks for text with get_insight_text(moment, mode, language, club).
The answer comes from insight_cache.json when it is there (instant), from the
Foundry agents on a cache miss (slow, then cached), or from a plain fallback
line built from the saveability score if the agents are unavailable.

Fill the cache before a demo, so the app never waits on the agents:
    python3 insights.py --warm

This file also has replay_to(), which rebuilds the match state up to any
match second. The app calls it on every screen update.
"""
import argparse
import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone

from replay import clock, is_key_moment, load_match, stream
from scoring import MatchState

CACHE_PATH = "insight_cache.json"
# Set LAST_LINE_LIVE_AGENTS=0 to never call the agents (cache or fallback only)
LIVE_AGENTS = os.getenv("LAST_LINE_LIVE_AGENTS", "1") == "1"

BOTH = "Both"                     # the "follow both keepers" club option
MODES = ["casual", "analyst"]
LANGUAGES = ["en", "es"]

VERDICT_ES = {"should save": "debió pararlo", "tough save": "parada difícil",
              "near-unstoppable": "casi imparable"}
DIST_VERDICT_ES = {"excellent": "excelente", "safe": "segura", "risky": "arriesgada",
                   "turnover": "pérdida"}
KEEPER_OWN_EVENTS = ("keeper_claim", "keeper_sweep", "keeper_distribution")


# ---------- Replaying the match ----------

def match_second(event):
    return event["minute"] * 60 + event["second"]


def keeper_team(event, state):
    """Which keeper a moment belongs to. Claims, sweeps and distributions are
    made by the keeper's own team; shots and goals come from the other team."""
    if event["type"] in KEEPER_OWN_EVENTS:
        return event["team"]
    return state.other(event["team"])


def replay_to(match, events, upto_sec):
    """Replay every event up to `upto_sec` match seconds.
    Returns (state, shots, moments, score):
      state   - a scoring.MatchState with workload, danger and keeper stats
      shots   - every shot so far, each {"event", "insight", "keeper_team"}
      moments - every key moment so far (see make_moment), oldest first
      score   - "home-away", e.g. "1-2"
    """
    state = MatchState(match["home"], match["away"])
    visible = [e for e in events if match_second(e) <= upto_sec]
    shots, moments, insights, score = [], [], {}, "0-0"

    for event, insight, _ in stream(visible, state, speed=0):
        insights[event["id"]] = insight  # empty dict for quiet events
        if event["type"] == "shot":
            shots.append({"event": event, "insight": insight,
                          "keeper_team": keeper_team(event, state)})
        if event["type"] == "goal":
            score = event["score"]
        if is_key_moment(event):
            moments.append(make_moment(event, events, state, insights, score))
    return state, shots, moments, score


def make_moment(event, events, state, insights, score):
    """A key moment as a plain dict. A goal takes its numbers and its clock
    from the shot that caused it, so a 67:04 'goal' shows as 67:03."""
    insight = insights.get(event["id"], {})
    timed = event
    if event["type"] == "goal":
        insight = insights.get(event["related_to"], {})
        timed = next(e for e in events if e["id"] == event["related_to"])
    distribution = None
    if event["type"] == "keeper_distribution":
        distribution = {k: event[k] for k in (
            "trigger", "method", "technique", "target_player", "target_role", "distance_m",
            "direction", "pressure", "reason", "outcome", "x_gain_m", "led_to_shot")}
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
        "keeper_team": keeper_team(event, state),
        "saveability": insight.get("saveability"),
        "verdict": insight.get("verdict"),
        "key_factor": insight.get("key_factor"),
        "distribution": distribution,          # None unless type is keeper_distribution
        "score": score,
    }


# ---------- The cache file ----------

_cache = {}
_cache_mtime = None


def match_fingerprint(path="match_events.json"):
    """A short code that changes whenever the match file changes. Cached texts
    are keyed by event id, so texts made for an older match must not be used."""
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


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
        if cache.get("_match") != match_fingerprint():
            cache = {"_match": match_fingerprint()}  # wrong or no match: start empty
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


def moment_key(event_id, mode, club, language):
    return f"{event_id}|{mode}|{club}|{language}"


def report_key(team, mode, language):
    return f"full_time|{team}|{mode}|{language}"


def viewer_for(mode, club, language):
    """The viewer dict the pipeline expects. 'key_club' keeps the app's club
    choice (including "Both") so the warm-up knows which cache key to use."""
    return {"name": f"{mode}_{language}_{club}", "mode": mode, "language": language,
            "club": "none, a neutral fan following both keepers" if club == BOTH else club,
            "key_club": club}


# ---------- Text for one moment ----------

def fallback_text(moment, language):
    """Plain line used when there is no agent text: saveability score and verdict."""
    spanish = language == "es"
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


def get_insight_text(moment, mode, language, club):
    """Text for one key moment. mode: "casual" or "analyst"; language: "en"
    or "es"; club: a club name or BOTH. Cache first, then the agents, then
    the fallback line."""
    key = moment_key(moment["event_id"], mode, club, language)
    cached = load_cache().get(key)
    if cached:
        return cached["text"]
    if LIVE_AGENTS:
        text = generate_moment_text(moment, viewer_for(mode, club, language))
        if text:
            save_to_cache(key, text)
            return text
    return fallback_text(moment, language)


def generate_moment_text(moment, viewer):
    """Run the agents for one moment and one viewer. Returns None on failure."""
    async def go():
        from pipeline import run  # imported here so the app starts without the agents
        async for item in run(only=moment["clock"], viewers=[viewer]):
            if item.get("event_id") == moment["event_id"]:
                version = item["versions"][0]
                return None if version["fallback"] else version["text"]
    try:
        return asyncio.run(go())
    except Exception:
        return None


# ---------- Text for the full-time keeper report ----------

def get_report_text(team, mode, language):
    """The Narrator's full-time report for `team`'s keeper, adapted for the
    viewer. Returns None if it is not cached and the agents are unavailable."""
    key = report_key(team, mode, language)
    cached = load_cache().get(key)
    if cached:
        return cached["text"]
    if LIVE_AGENTS:
        text = generate_report_text(team, viewer_for(mode, team, language))
        if text:
            save_to_cache(key, text)
            return text
    return None


async def report_texts(viewers):
    """Full-time report for each viewer (each hears their own club's keeper).
    Returns a list of texts, with None where the agents failed."""
    from agents import make_client, make_narrator, make_personalizer
    from pipeline import LiveMatch, keeper_report
    match, events = load_match()
    live = LiveMatch(match)
    for event in events:  # replay the whole match to get the final numbers
        live.event = event
        live.state.update(event)
        if event["type"] == "goal":
            live.score = event["score"]
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

async def warm():
    """Run the whole match through the agents once, for every mode, club
    (both clubs plus Both) and language, and store every text in the cache."""
    from pipeline import run
    match, _ = load_match()
    clubs = [match["home"], match["away"], BOTH]
    viewers = [viewer_for(m, c, lang) for m in MODES for c in clubs for lang in LANGUAGES]

    async for item in run(viewers=viewers):
        stored = 0
        for version in item["versions"]:
            v = version["viewer"]
            if version["fallback"]:
                continue
            if item["kind"] == "moment":
                key = moment_key(item["event_id"], v["mode"], v["key_club"], v["language"])
            elif item["kind"] == "full_time" and v["key_club"] == version["keeper_team"]:
                key = report_key(v["key_club"], v["mode"], v["language"])
            else:
                continue  # halftime reports are not shown in the app yet
            save_to_cache(key, version["text"])
            stored += 1
        label = item.get("clock", item["kind"])
        print(f"{label}: cached {stored} texts, {len(item['errors'])} errors", flush=True)

    # Agents sometimes fail for a moment (timeouts, rate limits): try those again
    await fill_missing()


async def fill_missing():
    """Generate only the texts the app needs that are not in the cache yet."""
    from pipeline import run
    match, events = load_match()
    _, _, moments, _ = replay_to(match, events, match_second(events[-1]))
    cache = load_cache()

    # Each moment is shown to fans of its keeper's club and to "Both" viewers
    for moment in moments:
        viewers = [viewer_for(m, c, lang) for c in (moment["keeper_team"], BOTH)
                   for m in MODES for lang in LANGUAGES
                   if moment_key(moment["event_id"], m, c, lang) not in cache]
        if not viewers:
            continue
        stored = 0
        async for item in run(only=moment["clock"], viewers=viewers):
            if item.get("event_id") != moment["event_id"]:
                continue
            for version in item["versions"]:
                v = version["viewer"]
                if not version["fallback"]:
                    save_to_cache(moment_key(item["event_id"], v["mode"], v["key_club"],
                                             v["language"]), version["text"])
                    stored += 1
        print(f"{moment['clock']}: filled {stored} of {len(viewers)} missing texts", flush=True)

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--warm", action="store_true", help="fill the whole cache using the agents")
    parser.add_argument("--missing", action="store_true", help="fill only texts not cached yet")
    args = parser.parse_args()
    if args.warm:
        asyncio.run(warm())
    elif args.missing:
        asyncio.run(fill_missing())
    else:
        parser.print_help()
