"""Last Line: the Streamlit app.

Replays the synthetic match through the goalkeeper's eyes: a live shot map
colored by saveability, insight cards for key moments, a workload meter and
danger indicator, and a full-time keeper report.

Run it:
    streamlit run app.py
"""
import math
import time

import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from insights import BOTH, DIST_VERDICT_ES, VERDICT_ES, get_insight_text, get_report_text, match_second, replay_to
from replay import load_match

# .env wins over old terminal values (only needed when the agents are called live)
load_dotenv(override=True)

st.set_page_config(page_title="Last Line", page_icon=":material/sports_soccer:", layout="wide")

# ---------- Settings ----------

TICK_SEC = 0.5                    # real seconds between screen updates while playing
SPEEDS = [30, 60, 120, 240, 600]  # match seconds per real second
DEFAULT_SPEED = 120               # 90 minutes in 45 seconds
WORKLOAD_MAX = 25                 # the workload meter is full at this many actions

# Pitch and goal sizes in meters (see the README for the coordinate frame)
GOAL_Y_MIN, GOAL_Y_MAX, GOAL_HEIGHT = 30.34, 37.66, 2.44

# Saveability colors: red = hard to save, gray = middle, blue = easy to save.
# Red and blue stay distinct for colorblind viewers; every marker also has an
# outline, a shape per outcome and a hover label, so color is never alone.
SAVEABILITY_SCALE = [[0, "#d03b3b"], [0.5, "#9a9890"], [1, "#1c5cab"]]
NO_SCORE_COLOR = "#c3c2b7"   # off target and blocked shots have no score
OUTLINE = "#52514e"
PITCH_LINE = "#9a9890"
SYMBOLS = {"goal": "star", "saved": "circle", "off_target": "x", "blocked": "square"}

# Words on screen, in English and Spanish
TEXT = {
    "en": {
        "goal": "Goal", "saved": "Saved", "off_target": "Off target", "blocked": "Blocked",
        "card_goal": "Goal conceded", "card_shot": "Save", "card_keeper_claim": "Cross claimed",
        "card_keeper_sweep": "Sweep", "card_keeper_distribution": "Distribution",
        "quality": "Quality", "decision": "decision", "pressure": "pressure",
        "led_to_shot": "led to a shot", "completion": "Distribution completed",
        "long_balls": "Long balls", "avg_decision": "Avg decision score",
        "attacks": "Attacks ending in a shot", "saveability": "Saveability", "workload": "Workload",
        "workload_help": "Shots faced + crosses claimed + sweeps",
        "danger": "Danger at this goal", "low": "Low", "medium": "Medium", "high": "High",
        "live": "Live", "report": "Full-time report", "shot_map": "Shots faced",
        "goal_mouth": "Where on-target shots crossed the line (shooter's view)",
        "moments": "Key moments", "no_moments": "No key moments yet. Press Play.",
        "key_factor": "Key factor", "goal_of": "goal",
        "report_wait": "The keeper's own report appears at full time. Numbers so far:",
        "report_missing": "The narrator's report is not available right now.",
        "on_target": "On target faced", "saves": "Saves", "conceded": "Goals conceded",
        "prevented": "Goals prevented", "prevented_help": "Saves minus the saves an average "
        "keeper would make from the same shots. Above 0 is better than average.",
        "expected": "Expected saves", "claims": "Crosses claimed", "sweeps": "Sweeps",
        "shots_faced": "Shots faced", "full_time": "Full time", "synthetic":
        "Synthetic match with fictional clubs and players. No real data.",
    },
    "es": {
        "goal": "Gol", "saved": "Parada", "off_target": "Fuera", "blocked": "Bloqueado",
        "card_goal": "Gol encajado", "card_shot": "Parada", "card_keeper_claim": "Centro atrapado",
        "card_keeper_sweep": "Salida", "card_keeper_distribution": "Distribución",
        "quality": "Calidad", "decision": "decisión", "pressure": "presión",
        "led_to_shot": "acabó en tiro", "completion": "Distribución completada",
        "long_balls": "Balones largos", "avg_decision": "Decisión media",
        "attacks": "Ataques que acabaron en tiro", "saveability": "Salvabilidad", "workload": "Carga de trabajo",
        "workload_help": "Tiros recibidos + centros atrapados + salidas",
        "danger": "Peligro en esta portería", "low": "Bajo", "medium": "Medio", "high": "Alto",
        "live": "En vivo", "report": "Informe final", "shot_map": "Tiros recibidos",
        "goal_mouth": "Dónde cruzaron la línea los tiros a puerta (vista del tirador)",
        "moments": "Momentos clave", "no_moments": "Aún no hay momentos clave. Pulsa Play.",
        "key_factor": "Factor clave", "goal_of": "portería",
        "report_wait": "El informe del portero aparece al final. Números hasta ahora:",
        "report_missing": "El informe del narrador no está disponible ahora.",
        "on_target": "Tiros a puerta", "saves": "Paradas", "conceded": "Goles encajados",
        "prevented": "Goles evitados", "prevented_help": "Paradas menos las que haría un "
        "portero medio con los mismos tiros. Más de 0 es mejor que la media.",
        "expected": "Paradas esperadas", "claims": "Centros atrapados", "sweeps": "Salidas",
        "shots_faced": "Tiros recibidos", "full_time": "Final", "synthetic":
        "Partido sintético con clubes y jugadores ficticios. Sin datos reales.",
    },
}


# ---------- Loading the match (once) ----------

@st.cache_data
def get_match():
    return load_match()


@st.cache_data
def keeper_names(events):
    """Each team's goalkeeper, found from the keeper's own actions."""
    names = {}
    for event in events:
        if event["type"] in ("keeper_save", "keeper_claim", "keeper_sweep", "keeper_distribution"):
            names[event["team"]] = event["player"]
    return names


match, events = get_match()
HOME, AWAY = match["home"], match["away"]
END_SEC = match_second(events[-1])
KEEPERS = keeper_names(events)

# The match position lives in session_state, so changing any sidebar option
# re-renders the page without restarting the match.
if "match_sec" not in st.session_state:
    st.session_state.match_sec = 0
    st.session_state.playing = False


# ---------- Sidebar controls ----------

st.sidebar.title("Last Line")
mode_label = st.sidebar.radio("Mode", ["Casual fan", "Analyst"], key="mode")
club = st.sidebar.selectbox("Favorite club (the keeper you follow)", [HOME, AWAY, BOTH], key="club",
                            format_func=lambda c: "Both keepers" if c == BOTH else c)
language_label = st.sidebar.radio("Language / Idioma", ["English", "Español"], key="language")
speed = st.sidebar.select_slider("Replay speed", SPEEDS, value=DEFAULT_SPEED, key="speed",
                                 format_func=lambda s: f"{s}x · full match in {round(END_SEC / s)} s")

play_col, pause_col, restart_col = st.sidebar.columns(3)
if play_col.button("Play", key="play", icon=":material/play_arrow:"):
    if st.session_state.match_sec >= END_SEC:
        st.session_state.match_sec = 0  # pressing Play at full time starts again
    st.session_state.playing = True
if pause_col.button("Pause", key="pause", icon=":material/pause:"):
    st.session_state.playing = False
if restart_col.button("Restart", key="restart", icon=":material/replay:"):
    st.session_state.match_sec = 0
    st.session_state.playing = True

mode = "casual" if mode_label == "Casual fan" else "analyst"
lang = "en" if language_label == "English" else "es"
t = TEXT[lang]
followed = [HOME, AWAY] if club == BOTH else [club]


# ---------- Small helpers ----------

def clock_text(seconds):
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def verdict_label(verdict):
    return VERDICT_ES[verdict] if lang == "es" else verdict


def verdict_badge(score, verdict):
    """A colored badge matching the shot map colors: red, gray or blue."""
    color = {"near-unstoppable": "red", "tough save": "gray", "should save": "blue"}[verdict]
    return f":{color}-badge[{t['saveability']} {score} · {verdict_label(verdict)}]"


def quality_badge(quality, verdict):
    """Distribution badge: blue excellent, gray safe, orange risky, red turnover."""
    color = {"excellent": "blue", "safe": "gray", "risky": "orange", "turnover": "red"}[verdict]
    label = DIST_VERDICT_ES[verdict] if lang == "es" else verdict
    return f":{color}-badge[{t['quality']} {quality} · {label}]"


def danger_badge(level):
    """Danger always shows an icon and a word, not just a color."""
    color, icon = {"low": ("green", "check_circle"), "medium": ("orange", "warning"),
                   "high": ("red", "error")}[level]
    return f":{color}-badge[:material/{icon}: {t[level]}]"


# ---------- Charts ----------

def add_line(fig, xs, ys):
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", hoverinfo="skip", showlegend=False,
                             line=dict(color=PITCH_LINE, width=1.5)))


def draw_half_pitch(fig):
    """Pitch lines for the attacking half. Plot x = pitch width (y),
    plot y = pitch length (x), so the goal is at the top."""
    def box(x0, x1, y0, y1):
        fig.add_shape(type="rect", x0=x0, x1=x1, y0=y0, y1=y1, layer="below",
                      line=dict(color=PITCH_LINE, width=1.5))
    box(0, 68, 52.5, 105)                       # half pitch
    box(13.84, 54.16, 88.5, 105)                # penalty box
    box(24.84, 43.16, 99.5, 105)                # six-yard box
    box(GOAL_Y_MIN, GOAL_Y_MAX, 105, 106.5)     # goal
    fig.add_shape(type="circle", x0=33.7, x1=34.3, y0=93.7, y1=94.3, layer="below",
                  fillcolor=PITCH_LINE, line=dict(width=0))  # penalty spot
    # Penalty arc (the part outside the box) and the top half of the center circle
    arc = [(34 + 9.15 * math.sin(a), 94 - 9.15 * math.cos(a))
           for a in [math.radians(d) for d in range(-90, 91, 3)]]
    arc = [(x, y) for x, y in arc if y < 88.5]
    add_line(fig, [x for x, _ in arc], [y for _, y in arc])
    circle = [(34 + 9.15 * math.cos(math.radians(d)), 52.5 + 9.15 * math.sin(math.radians(d)))
              for d in range(0, 181, 5)]
    add_line(fig, [x for x, _ in circle], [y for _, y in circle])


def hover_text(shot):
    event, insight = shot["event"], shot["insight"]
    text = (f"{clock_text(match_second(event))} · {event['player']} ({event['team']})<br>"
            f"{t[event['outcome']]} · {event['distance_m']} m · {event['speed_kmh']} km/h")
    if insight:
        text += f"<br>{t['saveability']} {insight['saveability']} · {verdict_label(insight['verdict'])}"
    return text


def add_shots(fig, shots, x_of, y_of, outcomes, show_scale):
    """One scatter trace per outcome, so each outcome has its own marker shape."""
    for outcome in outcomes:
        group = [s for s in shots if s["event"]["outcome"] == outcome]
        if not group:
            continue
        has_score = outcome in ("goal", "saved")
        fig.add_trace(go.Scatter(
            x=[x_of(s) for s in group], y=[y_of(s) for s in group],
            mode="markers", name=t[outcome],
            marker=dict(symbol=SYMBOLS[outcome], size=18 if outcome == "goal" else 12,
                        color=[s["insight"]["saveability"] for s in group] if has_score else NO_SCORE_COLOR,
                        coloraxis="coloraxis" if has_score else None,
                        line=dict(width=1.5, color=OUTLINE)),
            hovertext=[hover_text(s) for s in group], hoverinfo="text"))
    fig.update_layout(coloraxis=dict(
        colorscale=SAVEABILITY_SCALE, cmin=0, cmax=100, showscale=show_scale,
        colorbar=dict(title=t["saveability"], tickvals=[0, 35, 65, 100], len=0.8)))


def shot_map(shots):
    fig = go.Figure()
    draw_half_pitch(fig)
    add_shots(fig, shots, x_of=lambda s: s["event"]["y"], y_of=lambda s: s["event"]["x"],
              outcomes=SYMBOLS, show_scale=True)
    fig.update_xaxes(range=[69, -1], visible=False)  # reversed: the shooter's left is on the left
    fig.update_yaxes(range=[51, 107.5], visible=False, scaleanchor="x", scaleratio=1)
    fig.update_layout(height=470, margin=dict(l=0, r=0, t=10, b=0),
                      legend=dict(orientation="h", y=-0.02))
    return fig


def goal_mouth(shots):
    fig = go.Figure()
    # Posts, crossbar and goal line
    add_line(fig, [GOAL_Y_MIN, GOAL_Y_MIN, GOAL_Y_MAX, GOAL_Y_MAX], [0, GOAL_HEIGHT, GOAL_HEIGHT, 0])
    add_line(fig, [29.6, 38.4], [0, 0])
    on_target = [s for s in shots if s["insight"]]
    add_shots(fig, on_target, x_of=lambda s: s["event"]["end_y"], y_of=lambda s: s["event"]["end_z"],
              outcomes=["goal", "saved"], show_scale=False)
    fig.update_xaxes(range=[38.4, 29.6], visible=False)  # reversed, same view as the shot map
    fig.update_yaxes(range=[-0.15, 2.8], visible=False, scaleanchor="x", scaleratio=1)
    fig.update_layout(height=230, margin=dict(l=0, r=0, t=10, b=0), showlegend=False)
    return fig


# ---------- Page sections ----------

def keeper_panel(team, snapshot):
    """Workload meter and danger indicator for one goal."""
    s = snapshot[team]
    left, right = st.columns(2)
    left.metric(t["workload"], s["workload"], help=t["workload_help"])
    left.progress(min(s["workload"] / WORKLOAD_MAX, 1.0))
    right.markdown(f"**{t['danger']}**")
    right.markdown(danger_badge(s["danger"]))


def insight_card(moment):
    with st.container(border=True):
        title = t["card_" + moment["type"]]
        d = moment["distribution"]  # None unless this is a keeper distribution
        who = f"{moment['player']} → {d['target_player']}" if d else moment["player"]
        line = f"**{moment['clock']}** · **{title}** · {who}"
        if moment["saveability"] is not None:
            line += "  " + verdict_badge(moment["saveability"], moment["verdict"])
        if d:
            line += "  " + quality_badge(d["quality"], d["verdict"])
        st.markdown(line)
        if club == BOTH:
            st.caption(f"{moment['keeper']} · {moment['keeper_team']}")
        with st.spinner("Asking the agents..."):  # only shows on a slow cache miss
            st.write(get_insight_text(moment, mode, lang, club))
        if mode == "analyst" and d:
            # The facts behind the rating, in the order an analyst reads them
            details = (f"{d['method'].replace('_', ' ')} ({d['technique'].replace('_', ' ')}) · "
                       f"{d['target_role']} · {d['distance_m']} m · {d['pressure']} {t['pressure']} · "
                       f"{t['decision']} {d['decision_score']}")
            if d["led_to_shot"]:
                details += f" · {t['led_to_shot']}"
            st.caption(details)
        if mode == "analyst" and moment["key_factor"] and lang == "en":
            st.caption(f"{t['key_factor']}: {moment['key_factor']}")


def report_tab(state, finished):
    if not finished:
        st.info(t["report_wait"])
    report = state.keeper_report()
    for team in followed:
        r = report[team]
        st.subheader(f"{KEEPERS[team]} · {team}")
        cols = st.columns(4)
        cols[0].metric(t["shots_faced"], r["shots_faced"])
        cols[1].metric(t["on_target"], r["on_target"])
        cols[2].metric(t["saves"], r["saves"])
        cols[3].metric(t["conceded"], r["goals_conceded"])
        cols = st.columns(4)
        cols[0].metric(t["expected"], r["expected_saves"])
        cols[1].metric(t["prevented"], f"{r['goals_prevented']:+}", help=t["prevented_help"])
        cols[2].metric(t["claims"], r["claims"])
        cols[3].metric(t["sweeps"], r["sweeps"])
        cols = st.columns(4)
        cols[0].metric(t["completion"], f"{r['distribution_completion_pct']}%",
                       help=f"{r['completed']} / {r['distributions']}")
        cols[1].metric(t["long_balls"], f"{r['long_ball_pct']}%",
                       help=f"{r['long_completed']} / {r['long_attempts']}")
        cols[2].metric(t["avg_decision"], r["avg_decision_score"])
        cols[3].metric(t["attacks"], r["attacks_started"])
        if finished:
            with st.spinner("Asking the narrator..."):
                text = get_report_text(team, mode, lang)
            if text:
                st.write(text)
            else:
                st.caption(t["report_missing"])


# ---------- The page ----------

now = st.session_state.match_sec
finished = now >= END_SEC
state, shots, moments, score = replay_to(match, events, now)
snapshot = state.snapshot(now)

home_goals, away_goals = score.split("-")
st.markdown(f"## {HOME} {home_goals} – {away_goals} {AWAY}")
st.progress(min(now / END_SEC, 1.0),
            text=t["full_time"] if finished else clock_text(now))

live_tab, ft_tab = st.tabs([t["live"], t["report"]])

with live_tab:
    pitch_col, cards_col = st.columns([3, 2])
    with pitch_col:
        for team in followed:
            st.markdown(f"#### {KEEPERS[team]} · {t['goal_of']} {team}")
            keeper_panel(team, snapshot)
            faced = [s for s in shots if s["keeper_team"] == team]
            st.caption(t["shot_map"])
            st.plotly_chart(shot_map(faced), key=f"map_{team}", width="stretch",
                            config={"displayModeBar": False})
            st.caption(t["goal_mouth"])
            st.plotly_chart(goal_mouth(faced), key=f"goal_{team}", width="stretch",
                            config={"displayModeBar": False})
    with cards_col:
        st.markdown(f"#### {t['moments']}")
        shown = [m for m in moments if m["keeper_team"] in followed]
        with st.container(height=1100, border=False):
            if not shown:
                st.caption(t["no_moments"])
            for moment in reversed(shown):  # newest first
                insight_card(moment)

with ft_tab:
    report_tab(state, finished)

st.caption(t["synthetic"])


# ---------- Playback ----------
# While playing: wait one tick, move the match clock forward, and rerun the
# script. Any sidebar change interrupts the wait and reruns at the same position.
if st.session_state.playing:
    if finished:
        st.session_state.playing = False
    else:
        time.sleep(TICK_SEC)
        st.session_state.match_sec = min(END_SEC, now + speed * TICK_SEC)
        st.rerun()
