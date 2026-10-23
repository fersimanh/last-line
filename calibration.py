"""Calibration targets for the match engine, each with a source label.

Two kinds of target:
  verified     published Premier League 2025/26 figures (first 11 matchweeks). The
               simulated 30-match average must be within 15 percent of the figure.
  approximate  general football knowledge, UNVERIFIED. Stated as ranges. The average
               must be within 25 percent of the range (below its low end or above its
               high end by no more than 25 percent). `in_range` also says whether it
               sits inside the stated range itself.

`stage` is the engine stage that can first measure a target. Until then the report
prints "n/a" instead of failing it.

Interpretations (my assumptions, not part of the published figures):
  - "about 713 completed passes per match" is read as both teams combined.
  - a LONG pass is one of 32 m or more.
  - passes are counted as attempts for the shares (long, final third).
"""
VERIFIED_SOURCE = "Premier League 2025/26, first 11 matchweeks"
APPROX_SOURCE = "general football knowledge, UNVERIFIED"

TARGETS = [
    # key, label, kind, value or (low, high), unit, stage, note
    dict(key="completed_passes", label="Completed passes per match (both teams)", kind="verified",
         value=713, unit="", stage=1, note="read as both teams combined"),
    dict(key="long_pass_share", label="Long passes, share of passes", kind="verified",
         value=11.5, unit="%", stage=1, note="long = 32 m or more (assumed)"),
    dict(key="final_third_share", label="Passes ending in the final third", kind="verified",
         value=34.0, unit="%", stage=1, note="final third = x of 70 or more in the attacking frame"),
    dict(key="goal_kick_opp_half", label="Goal kicks ending in the opposition half", kind="verified",
         value=48.0, unit="%", stage=2, note=""),
    dict(key="header_goal_share", label="Goals that are headers", kind="verified",
         value=21.0, unit="%", stage=2, note=""),
    dict(key="second_half_added", label="Second-half added time", kind="verified",
         value=408.0, unit=" s", stage=2, note="6 min 48 s"),

    dict(key="pass_completion", label="Pass completion", kind="approximate", value=(80.0, 85.0), unit="%", stage=1),
    dict(key="goals", label="Goals per match", kind="approximate", value=(2.7, 2.9), unit="", stage=2),
    dict(key="shots", label="Shots per match (both teams)", kind="approximate", value=(24.0, 27.0), unit="", stage=2),
    dict(key="shots_on_target", label="Shots on target per match", kind="approximate", value=(8.0, 9.0), unit="", stage=2),
    dict(key="corners", label="Corners per match", kind="approximate", value=(10.0, 11.0), unit="", stage=2),
    dict(key="fouls", label="Fouls per match", kind="approximate", value=(20.0, 24.0), unit="", stage=2),
    dict(key="yellow_cards", label="Yellow cards per match", kind="approximate", value=(4.0, 5.0), unit="", stage=2),
    dict(key="red_cards", label="Red cards per match", kind="approximate", value=(0.10, 0.15), unit="", stage=2),
    dict(key="offsides", label="Offsides per match", kind="approximate", value=(3.0, 4.0), unit="", stage=2),
    dict(key="crosses_attempted", label="Crosses attempted per match", kind="approximate", value=(30.0, 40.0), unit="", stage=1),
    dict(key="cross_completion", label="Cross completion", kind="approximate", value=(25.0, 30.0), unit="%", stage=1),
    dict(key="throw_ins", label="Throw-ins per match", kind="approximate", value=(40.0, 55.0), unit="", stage=2),
    dict(key="possession_min_share", label="Possession of the team with less of the ball", kind="approximate",
         value=(40.0, 50.0), unit="%", stage=1, note="possession between 40-60 and 60-40"),
]

PASS_TYPES = ("pass", "cross", "through_ball")


def metrics_for(result):
    """The measurable numbers for one simulated match: {key: value}. Keys that the
    engine cannot measure yet are simply missing."""
    events = result["events"]
    passes = [e for e in events if e["type"] in PASS_TYPES]
    done = [e for e in passes if e["success"]]
    crosses = [e for e in events if e["type"] == "cross"]
    count = lambda t: sum(1 for e in events if e["type"] == t)
    m = {
        "completed_passes": len(done),
        "pass_completion": 100 * len(done) / max(1, len(passes)),
        "long_pass_share": 100 * sum(1 for e in passes if e["length_m"] >= 32) / max(1, len(passes)),
        "final_third_share": 100 * sum(1 for e in passes if e["end_x"] >= 70) / max(1, len(passes)),
        "crosses_attempted": len(crosses),
        "cross_completion": 100 * sum(1 for e in crosses if e["success"]) / max(1, len(crosses)),
        "possession_min_share": min(result["match"]["possession_pct"].values()),
    }
    # Later stages add these events; until then they stay unmeasured
    later = {"goals": count("goal"), "shots": count("shot"), "corners": count("corner"),
             "fouls": count("foul"), "red_cards": sum(1 for e in events if e["type"] == "card" and e.get("card") == "red"),
             "yellow_cards": sum(1 for e in events if e["type"] == "card" and e.get("card") == "yellow"),
             "offsides": count("offside"), "throw_ins": count("throw_in"),
             "shots_on_target": sum(1 for e in events if e["type"] == "shot" and e.get("outcome") in ("goal", "saved"))}
    if any(e["type"] in ("shot", "throw_in", "corner", "foul") for e in events):
        m.update(later)
        # verified targets that need a little more work to measure
        kicks = [e for e in events if e["type"] == "keeper_distribution" and e["trigger"] == "goal_kick"]
        if kicks:
            m["goal_kick_opp_half"] = 100 * sum(1 for e in kicks if e["target_x"] >= 52.5) / len(kicks)
        shots = {e["id"]: e for e in events if e["type"] == "shot"}
        goals = [shots[e["related_to"]] for e in events if e["type"] == "goal" and e["related_to"] in shots]
        if goals:
            m["header_goal_share"] = 100 * sum(1 for g in goals if g["body_part"] == "head") / len(goals)
        m["second_half_added"] = result["match"]["added_time_s"]["second_half"]
    return m


def evaluate(means, stage):
    """Compare average metrics with the targets. Returns rows of dicts with a
    `verdict` of PASS, FAIL, or n/a (a later stage)."""
    rows = []
    for t in TARGETS:
        value = means.get(t["key"])
        row = dict(t, measured=value)
        if t["stage"] > stage or value is None:
            row.update(verdict=f"n/a (stage {t['stage']})", in_range=None)
        elif t["kind"] == "verified":
            row.update(verdict="PASS" if abs(value - t["value"]) <= 0.15 * t["value"] else "FAIL", in_range=None)
        else:
            low, high = t["value"]
            ok = low * 0.75 <= value <= high * 1.25
            row.update(verdict="PASS" if ok else "FAIL", in_range=low <= value <= high)
        rows.append(row)
    return rows
