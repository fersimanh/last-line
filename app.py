"""Last Line: the Streamlit app.

Two views of the same match, both read through the keeper's perception layer
(perception.PerceptionFilter) and never from the raw match file:

  Keeper's eyes (default)  a 2D pitch from the followed goal line to just past
                           halfway, with the keeper's modeled sightline (a
                           translucent cone facing the ball). Everything outside
                           the cone is dimmed. Cards are written to the keeper
                           in the second person.
  Reveal                   what the keeper did NOT perceive: the missed events,
                           the official shot map and goal mouth, official stats.

The look comes from theme.py (one set of design tokens for the CSS and charts).

Run it:
    streamlit run app.py
"""
import html
import math
import time
from functools import partial

import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

import inspector
from matchclock import display_clock, minute_label
import selection
import theme
import vision
from insights import (BOTH, DIST_VERDICT_ES, VERDICT_ES, filter_for, get_event_text,
                      get_insight_text, get_report_text, keeper_eyes, match_end_second,
                      match_second, perceived_state, replay_to)
from perception import match_fingerprint, match_info

# .env wins over old terminal values (only needed when the agents are called live)
load_dotenv(override=True)

st.set_page_config(page_title="Last Line", page_icon=":material/sports_soccer:", layout="wide",
                   initial_sidebar_state="expanded")

# ---------- Settings ----------

TICK_SEC = 0.5                    # real seconds between screen updates while playing
SPEEDS = [30, 60, 120, 240, 600]  # match seconds per real second
DEFAULT_SPEED = 120               # 90 minutes in 45 seconds
MAX_STEP_SEC = 2.0                # a sleeping browser tab must not make the match jump
WORKLOAD_MAX = 25                 # the workload meter is full at this many actions
RECENT_EVENTS = 8                 # events kept in the fading trail
UNSEEN_WINDOW_SEC = 30            # "missed in the last N seconds"
PLOT_TOP = 107.0                  # the pitch is drawn whole: the keeper's goal line to the far goal
PITCH_HEIGHT = 820                # pixels: the whole pitch is long, so the plot is tall


EYES, REVEAL = "Keeper's eyes", "Reveal"   # values of the View control

# Pitch and goal sizes in meters (see the README for the coordinate frames)
GOAL_Y_MIN, GOAL_Y_MAX, GOAL_HEIGHT = 30.34, 37.66, 2.44

# Marker shape per outcome (the shot map) and per sight (the Keeper's eyes pitch).
# Shape, outline and hover label carry the meaning too, so color is never alone.
SYMBOLS = {"goal": "star", "saved": "circle", "off_target": "x", "blocked": "square"}
SIGHT_SYMBOLS = {"seen": "circle", "own": "square", "felt": "diamond", "goal": "star",
                 "missed": "circle-open"}
REASON_KEY = {"beyond_radius": "beyond_radius", "outside_fov": "outside_fov", "blocked": "blocked_by"}

# Words on screen, in English and Spanish
TEXT = {
    "en": {
        "eyebrow": "Goalkeeper-lens match intelligence",
        "tagline": "Every shot, explained from the goalkeeper's eyes.",
        "tab_live": "Live", "tab_report": "Full-time report",
        "goal": "Goal", "saved": "Saved", "off_target": "Off target", "blocked": "Blocked",
        "card_goal": "Goal conceded", "card_keeper_claim": "Cross claimed",
        "card_keeper_sweep": "Sweep", "card_keeper_distribution": "Distribution",
        "tag_shot": "Shot", "tag_goal": "Goal", "tag_keeper_claim": "Claim",
        "tag_keeper_sweep": "Sweep", "tag_keeper_distribution": "Distribution",
        "sight_own": "Your action", "sight_seen": "Seen clearly", "sight_felt": "Late sight",
        "saveability": "Saveability", "quality": "Quality", "numbers": "Show the numbers",
        "n_saveability": "Saveability", "n_verdict": "Verdict", "n_key_factor": "Key factor",
        "n_situation": "Situation", "n_shot": "Shot", "n_off_line": "You stood off your line",
        "n_distance": "Distance to the event", "n_sight": "Sight",
        "n_missed_before": "Events missed just before", "n_method": "Method",
        "n_target": "Target", "n_pressure": "Pressure", "n_decision": "Decision score",
        "n_difficulty": "Difficulty", "n_options": "Options in view",
        "n_unseen_options": "Options out of sight",
        "workload": "Workload", "workload_help": "Shots faced + crosses claimed + sweeps + close-downs",
        "danger": "Danger at this goal", "low": "Low", "medium": "Medium", "high": "High",
        "unseen_30": "Missed in the last 30 s", "unseen_total": "Missed so far",
        "keeper": "Keeper", "ball": "Ball", "sightline": "Modeled sightline",
        "legend_seen": "Seen", "legend_own": "Your action", "legend_felt": "Felt, not seen",
        "legend_goal": "Goal", "legend_missed": "Missed",
        "show_on_pitch": "Show on pitch", "showing_on_pitch": "Showing this moment on the pitch",
        "pitch_focus": "The pitch shows the selected moment at {clock}. Press Back to live to return to the match.",
        "full_pitch": "Show the full pitch (no dimming)",
        "full_pitch_help": "Turns off the dimming outside the keeper's cone. The cone is still drawn.",
        "players_mine": "Your team", "players_theirs": "Opponents", "players_hidden": "Out of sight",
        "ball_far": "Ball {d} m away",
        "pitch_help": "The cone is the keeper's modeled sightline: the data has no real eyeline. "
                      "Everything outside it is dimmed. Dots are the players the keeper can see, "
                      "from the tracking: a player behind another body is hidden.",
        "pitch_help_reveal": " Hollow dots are players the keeper cannot see.",
        "keeper_pick": "Keeper", "moments": "Key moments",
        "no_moments": "No key moments yet. Press Play.",
        "reveal_title": "What the keeper missed",
        "reveal_help": "Events outside the keeper's perception. The explanations never saw these.",
        "beyond_radius": "Too far away", "outside_fov": "Outside the cone", "blocked_by": "Blocked by a player",
        "options_out": "Passing options out of sight", "nothing_missed": "Nothing missed yet.",
        "shot_map": "Shots faced (official)",
        "goal_mouth": "Where on-target shots crossed the line (shooter's view)",
        "official": "Official numbers",
        "report_wait": "The keeper's own report appears at full time. Numbers so far, as the keeper knows them:",
        "report_missing": "The narrator's report is not available right now.",
        "on_target": "On target faced", "saves": "Saves", "conceded": "Goals conceded",
        "prevented": "Goals prevented", "prevented_help": "Saves minus the saves an average "
        "keeper would make from the same shots. Above 0 is better than average.",
        "expected": "Expected saves", "claims": "Crosses claimed", "sweeps": "Sweeps",
        "shots_faced": "Shots faced", "full_time": "Full time",
        "completion": "Distribution completed", "long_balls": "Long balls",
        "avg_decision": "Avg decision score", "attacks": "Attacks ending in a shot",
        "synthetic": "Synthetic match with fictional clubs and players. No real data.",
        "m": "m", "asking_agents": "Asking the agents...", "asking_narrator": "Asking the narrator...",
        "tab_moments": "Key moments", "tab_events": "Events", "filter_all": "All", "filter_shots": "Shots",
        "filter_passes": "Passes", "filter_keeper": "Keeper", "filter_other": "Other",
        "col_clock": "Clock", "col_event": "Event", "col_player": "Player", "col_team": "Team",
        "col_sight": "Sight", "no_events": "No events match this filter yet.",
        "scrub": "Minute", "prev_moment": "Previous moment", "next_moment": "Next moment",
        "back_to_live": "Back to live", "ai_insight": "AI insight", "quick_insight": "Quick insight",
        "inspect_hint": "Click a marker on the pitch, or a row under Events, to inspect it. The match pauses.",
        "not_perceived": "The selected event is not something this keeper perceived. "
                         "Switch to Reveal to inspect it, or pick another event.",
        "window_line": "In the {s} seconds before: you saw {seen} events and missed {missed}.",
        "missed_list": "What you missed", "show_snapshot": "The moment",
        "ev": {"pass": "Pass", "cross": "Cross", "through_ball": "Through ball", "box_entry": "Box entry",
               "shot": "Shot", "goal": "Goal", "keeper_save": "Save", "keeper_claim": "Claim",
               "keeper_sweep": "Sweep", "keeper_close_down": "Close-down",
               "keeper_distribution": "Distribution", "tackle": "Tackle",
               "possession_change": "Possession change"},
        "sit": {"open_play": "Open play", "cutback": "Cutback", "header_from_cross": "Header from a cross",
                "one_on_one": "One on one", "two_on_one": "Two on one", "rebound": "Rebound",
                "second_ball": "Second ball", "corner": "Corner", "free_kick": "Free kick", "penalty": "Penalty"},
    },
    "es": {
        "eyebrow": "Inteligencia de partido desde el portero",
        "tagline": "Cada disparo, explicado desde los ojos del portero.",
        "tab_live": "En vivo", "tab_report": "Informe final",
        "goal": "Gol", "saved": "Parada", "off_target": "Fuera", "blocked": "Bloqueado",
        "card_goal": "Gol encajado", "card_keeper_claim": "Centro atrapado",
        "card_keeper_sweep": "Salida", "card_keeper_distribution": "Distribución",
        "tag_shot": "Disparo", "tag_goal": "Gol", "tag_keeper_claim": "Centro",
        "tag_keeper_sweep": "Salida", "tag_keeper_distribution": "Distribución",
        "sight_own": "Tu acción", "sight_seen": "Visto con claridad", "sight_felt": "Visto tarde",
        "saveability": "Salvabilidad", "quality": "Calidad", "numbers": "Ver los números",
        "n_saveability": "Salvabilidad", "n_verdict": "Veredicto", "n_key_factor": "Factor clave",
        "n_situation": "Situación", "n_shot": "Disparo", "n_off_line": "Estabas fuera de tu línea",
        "n_distance": "Distancia a la jugada", "n_sight": "Visión",
        "n_missed_before": "Jugadas no vistas justo antes", "n_method": "Método",
        "n_target": "Destino", "n_pressure": "Presión", "n_decision": "Puntuación de decisión",
        "n_difficulty": "Dificultad", "n_options": "Opciones a la vista",
        "n_unseen_options": "Opciones fuera de vista",
        "workload": "Carga de trabajo", "workload_help": "Tiros recibidos + centros atrapados + salidas + achiques",
        "danger": "Peligro en esta portería", "low": "Bajo", "medium": "Medio", "high": "Alto",
        "unseen_30": "No vistas en los últimos 30 s", "unseen_total": "No vistas hasta ahora",
        "keeper": "Portero", "ball": "Balón", "sightline": "Línea de visión modelada",
        "legend_seen": "Visto", "legend_own": "Tu acción", "legend_felt": "Sentido, no visto",
        "legend_goal": "Gol", "legend_missed": "No visto",
        "show_on_pitch": "Ver en el campo", "showing_on_pitch": "Mostrando este momento en el campo",
        "pitch_focus": "El campo muestra el momento elegido ({clock}). Pulsa Volver al directo para regresar al partido.",
        "full_pitch": "Mostrar todo el campo (sin atenuar)",
        "full_pitch_help": "Quita el oscurecido fuera del cono del portero. El cono se sigue dibujando.",
        "players_mine": "Tu equipo", "players_theirs": "Rivales", "players_hidden": "Fuera de vista",
        "ball_far": "Balón a {d} m",
        "pitch_help": "El cono es la línea de visión modelada del portero: los datos no tienen una "
                      "mirada real. Todo lo que queda fuera está atenuado. Los puntos son los jugadores "
                      "que el portero ve, según el tracking: un jugador tapado por otro no se ve.",
        "pitch_help_reveal": " Los puntos huecos son jugadores que el portero no ve.",
        "keeper_pick": "Portero", "moments": "Momentos clave",
        "no_moments": "Aún no hay momentos clave. Pulsa Play.",
        "reveal_title": "Lo que el portero no vio",
        "reveal_help": "Jugadas fuera de la percepción del portero. Las explicaciones nunca las vieron.",
        "beyond_radius": "Demasiado lejos", "outside_fov": "Fuera del cono", "blocked_by": "Tapado por un jugador",
        "options_out": "Opciones de pase fuera de vista", "nothing_missed": "Aún no se ha perdido nada.",
        "shot_map": "Tiros recibidos (oficial)",
        "goal_mouth": "Dónde cruzaron la línea los tiros a puerta (vista del tirador)",
        "official": "Números oficiales",
        "report_wait": "El informe del portero aparece al final. Números hasta ahora, como los conoce el portero:",
        "report_missing": "El informe del narrador no está disponible ahora.",
        "on_target": "Tiros a puerta", "saves": "Paradas", "conceded": "Goles encajados",
        "prevented": "Goles evitados", "prevented_help": "Paradas menos las que haría un "
        "portero medio con los mismos tiros. Más de 0 es mejor que la media.",
        "expected": "Paradas esperadas", "claims": "Centros atrapados", "sweeps": "Salidas",
        "shots_faced": "Tiros recibidos", "full_time": "Final",
        "completion": "Distribución completada", "long_balls": "Balones largos",
        "avg_decision": "Decisión media", "attacks": "Ataques que acabaron en tiro",
        "synthetic": "Partido sintético con clubes y jugadores ficticios. Sin datos reales.",
        "m": "m", "asking_agents": "Consultando a los agentes...", "asking_narrator": "Consultando al narrador...",
        "tab_moments": "Momentos clave", "tab_events": "Jugadas", "filter_all": "Todas", "filter_shots": "Disparos",
        "filter_passes": "Pases", "filter_keeper": "Portero", "filter_other": "Otras",
        "col_clock": "Reloj", "col_event": "Jugada", "col_player": "Jugador", "col_team": "Equipo",
        "col_sight": "Visión", "no_events": "Aún no hay jugadas con este filtro.",
        "scrub": "Minuto", "prev_moment": "Momento anterior", "next_moment": "Momento siguiente",
        "back_to_live": "Volver al directo", "ai_insight": "Análisis de IA", "quick_insight": "Análisis rápido",
        "inspect_hint": "Haz clic en un marcador del campo, o en una fila de Jugadas, para inspeccionarla. "
                        "El partido se pausa.",
        "not_perceived": "El portero no percibió la jugada seleccionada. "
                         "Cambia a Reveal para inspeccionarla, o elige otra.",
        "window_line": "En los {s} segundos anteriores: viste {seen} jugadas y no viste {missed}.",
        "missed_list": "Lo que no viste", "show_snapshot": "El momento",
        "ev": {"pass": "Pase", "cross": "Centro", "through_ball": "Pase al hueco", "box_entry": "Entrada al área",
               "shot": "Disparo", "goal": "Gol", "keeper_save": "Parada", "keeper_claim": "Centro atrapado",
               "keeper_sweep": "Salida", "keeper_close_down": "Achique",
               "keeper_distribution": "Distribución", "tackle": "Entrada",
               "possession_change": "Cambio de posesión"},
        "sit": {"open_play": "Juego abierto", "cutback": "Pase atrás", "header_from_cross": "Cabezazo tras centro",
                "one_on_one": "Mano a mano", "two_on_one": "Dos contra uno", "rebound": "Rechace",
                "second_ball": "Segunda jugada", "corner": "Córner", "free_kick": "Falta directa", "penalty": "Penalti"},
    },
}


for _lang in TEXT:  # event names are shared with inspector.py, so they are written once
    TEXT[_lang]["ev"] = inspector.EVENT_NAMES[_lang]


# ---------- The match basics (cached) ----------

@st.cache_data
def basics(fingerprint):
    """Teams and the final second, read once per match file. The fingerprint
    changes when the match file does, so a regenerated match is picked up."""
    return match_info(), match_end_second()


match, END_SEC = basics(match_fingerprint())
HOME, AWAY = match["home"], match["away"]
END_MIN = max(1, -(-int(END_SEC) // 60))        # full match length in minutes, added time included
SPAN_MIN = -(-END_MIN // 5) * 5                 # the bar is whole five-minute segments
HALF_TIME_SEC = match.get("half_time_s", END_SEC / 2)

# The match position lives in session_state, so changing any sidebar option
# re-renders the page without restarting the match.
for key, start in (("match_sec", 0), ("playing", False), ("last_wall", time.time()),
                   ("selected_event_id", None), ("timer_on", False), ("scrub", 0)):
    st.session_state.setdefault(key, start)  # each key on its own, so none is ever missing


# ---------- Styling ----------

def inject_css():
    """Send the stylesheet (theme.py) to the page. Called once per full run."""
    st.markdown(f"<style>{theme.build_css()}</style>", unsafe_allow_html=True)


inject_css()


# ---------- Sidebar controls ----------

st.sidebar.markdown('<span class="ll-eyebrow">Last Line</span>', unsafe_allow_html=True)
view = st.sidebar.radio("View", [EYES, REVEAL], key="view", horizontal=True)
mode_label = st.sidebar.radio("Mode", ["Casual fan", "Analyst"], key="mode", horizontal=True)
club = st.sidebar.selectbox("Favorite club (the keeper you follow)", [HOME, AWAY, BOTH], key="club",
                            format_func=lambda c: "Both keepers" if c == BOTH else c)
language_label = st.sidebar.radio("Language / Idioma", ["English", "Español"], key="language",
                                  horizontal=True)
speed = st.sidebar.select_slider("Replay speed", SPEEDS, value=DEFAULT_SPEED, key="speed",
                                 format_func=lambda s: f"{s}x · full match in {round(END_SEC / s)} s")
fov, sight = vision.DEFAULT_FOV_DEG, vision.DEFAULT_RADIUS_M      # the keeper's modeled sightline is fixed
full_pitch = st.sidebar.checkbox("Show the full pitch (no dimming)", key="full_pitch")

play_col, pause_col, restart_col = st.sidebar.columns(3)
if play_col.button("Play", key="play", type="primary", icon=":material/play_arrow:"):
    if st.session_state.match_sec >= END_SEC:
        st.session_state.match_sec = 0  # pressing Play at full time starts again
    st.session_state.playing = True
    st.session_state.last_wall = time.time()
    st.session_state.selected_event_id = None   # playing again closes the inspector, like Back to live
if pause_col.button("Pause", key="pause", icon=":material/pause:"):
    st.session_state.playing = False
if restart_col.button("Restart", key="restart", icon=":material/replay:"):
    selection.restart(st.session_state)   # the clock to zero, nothing selected

mode = "casual" if mode_label == "Casual fan" else "analyst"
lang = "en" if language_label == "English" else "es"
t = TEXT[lang]
followed = [HOME, AWAY] if club == BOTH else [club]
st.sidebar.caption(t["full_pitch_help"])

esc = html.escape

# ---------- Header ----------

st.markdown(f'<div class="ll-header"><span class="ll-eyebrow">{esc(t["eyebrow"])}</span>'
            f'<div class="ll-wordmark">Last Line</div><p class="ll-tagline">{esc(t["tagline"])}</p></div>',
            unsafe_allow_html=True)


# ---------- Small helpers ----------

def clock_text(seconds):
    """The match clock a fan sees: 45:00 again after half time, 90+3:25 in added time."""
    return display_clock(seconds, HALF_TIME_SEC)


def minute_text(seconds):
    """A short minute label for the slider and the timeline: 56, 45+2, 90+4."""
    return minute_label(seconds, HALF_TIME_SEC)


def event_clock(event):
    """The clock an event happened at, as a fan sees it (written by the engine on each event)."""
    return event.get("clock") or clock_text(match_second(event))


def verdict_label(verdict):
    return VERDICT_ES[verdict] if lang == "es" else verdict


def dist_verdict_label(verdict):
    return DIST_VERDICT_ES[verdict] if lang == "es" else verdict


def pill(text, lime=False):
    return f'<span class="ll-pill{" ll-pill--lime" if lime else ""}">{esc(text)}</span>'


def meter(value, maximum):
    return f'<div class="ll-meter"><span style="width:{min(value / maximum, 1.0) * 100:.0f}%"></span></div>'


# Small inline icons: a danger level always shows a shape and a word, never color alone
DANGER_ICONS = {
    "low": '<svg viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="4.5" fill="none" '
           'stroke="currentColor" stroke-width="1.6"/></svg>',
    "medium": '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M6 1.5 11 10.5H1Z" fill="none" '
              'stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>',
    "high": '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M6 1 11 6 6 11 1 6Z" '
            'fill="currentColor"/></svg>',
}


def danger_pill(level):
    return f'<span class="ll-pill ll-pill--lime">{DANGER_ICONS[level]}{esc(t[level])}</span>'


def stat(label, value, extra=""):
    return (f'<div class="ll-stat"><span class="ll-label">{esc(label)}</span>'
            f'<span class="ll-stat-value">{esc(str(value))}</span>{extra}</div>')


# ---------- Top bar: score, clock and the 90-minute timeline ----------

def topbar_html(score, now):
    home_goals, away_goals = score.split("-")
    clock = "FT" if now >= END_SEC else clock_text(now)
    aria = f"{HOME} {home_goals} – {away_goals} {AWAY}, {clock}"
    return (f'<div class="ll-topbar" role="group" aria-label="{esc(aria, quote=True)}">'
            f'<div class="ll-team">{esc(HOME)}</div>'
            f'<div class="ll-scorebox"><span class="ll-score">{home_goals} – {away_goals}</span>'
            f'<span class="ll-clock-big">{clock}</span></div>'
            f'<div class="ll-team ll-team--away">{esc(AWAY)}</div></div>')


def timeline_html(now, ticks=()):
    """A segmented match bar (five-minute segments, added time included), a tick at half time,
    a diamond for every goal so far, a small tick for every key moment so far
    (`ticks` is a list of (second, label)), and a label like 67' / 90'."""
    minute = min(float(END_MIN), now / 60)
    count = -(-END_MIN // 5)
    segments = "".join(
        f'<div class="ll-seg"><span style="width:{max(0.0, min(1.0, (minute - i * 5) / 5)) * 100:.0f}%"></span></div>'
        for i in range(count))
    goals = [(s, team) for s, team in keeper_eyes(HOME).goal_seconds() if s <= now]
    diamonds = "".join(
        f'<span class="ll-goal" style="left:{min(s / 60, SPAN_MIN) / SPAN_MIN * 100:.2f}%" '
        f'title="{esc(t["goal"], quote=True)} {minute_text(s)}&#39; {esc(team, quote=True)}"></span>'
        for s, team in goals)
    marks = "".join(f'<span class="ll-tick" style="left:{min(sec / 60, SPAN_MIN) / SPAN_MIN * 100:.2f}%" '
                    f'title="{esc(label, quote=True)}"></span>' for sec, label in ticks if sec <= now)
    goal_text = ", ".join(f"{minute_text(s)}'" for s, _ in goals) or "-"
    aria = f"{clock_text(now)} of {clock_text(END_SEC)}. {t['goal']}: {goal_text}"
    return (f'<div class="ll-timeline" role="img" aria-label="{esc(aria, quote=True)}">'
            f'<div class="ll-segs" style="grid-template-columns:repeat({count},1fr)">{segments}</div>'
            f'<span class="ll-ht" style="left:{HALF_TIME_SEC / 60 / SPAN_MIN * 100:.2f}%"></span>{marks}{diamonds}'
            f'<div class="ll-tl-label"><span>{esc(minute_text(now))}&#39;</span><span class="ll-ht-label" style="left:{HALF_TIME_SEC / 60 / SPAN_MIN * 100:.2f}%">HT 45&#39;</span>'
            f'<span>{esc(minute_text(END_SEC))}&#39;</span></div></div>')


# ---------- Charts ----------

def path_text(points):
    """An SVG path through (x up the pitch, y across) points, in plot coordinates:
    plot x is the pitch width (y) and plot y is the length (x), so the goal is at the bottom."""
    return "M " + " L ".join(f"{y:.2f},{x:.2f}" for x, y in points)


def add_path(fig, points, closed=False, fill=None, color=None, width=1.5):
    shape = dict(type="path", path=path_text(points) + (" Z" if closed else ""), layer="below",
                 line=dict(color=color or "rgba(0,0,0,0)", width=width if color else 0))
    if fill:
        shape["fillcolor"] = fill
    fig.add_shape(**shape)


def rect_points(x0, x1, y0, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def arc_points(cx, cy, radius, start_deg, end_deg, steps=40):
    angles = [start_deg + (end_deg - start_deg) * i / steps for i in range(steps + 1)]
    return [(cx + radius * math.cos(math.radians(a)), cy + radius * math.sin(math.radians(a)))
            for a in angles]


def draw_pitch(fig):
    """The whole pitch, from the followed goal line (x = 0) to the far goal (x = 105)."""
    line = theme.PITCH_LINE
    add_path(fig, rect_points(0, 105.0, 0, 68), closed=True, fill=theme.CARD, color=line)
    add_path(fig, [(52.5, 0), (52.5, 68)], color=line)                               # halfway line
    add_path(fig, arc_points(52.5, 34, 9.15, 0, 360), color=line)                    # center circle
    for goal_line, direction in ((0.0, 1), (105.0, -1)):                             # the same markings at both ends
        far = goal_line + direction
        add_path(fig, rect_points(goal_line, goal_line + direction * 16.5, 13.84, 54.16), closed=True, color=line)  # penalty area
        add_path(fig, rect_points(goal_line, goal_line + direction * 5.5, 24.84, 43.16), closed=True, color=line)   # six-yard box
        add_path(fig, rect_points(goal_line - direction * 2.2, goal_line, GOAL_Y_MIN, GOAL_Y_MAX), closed=True, color=line)  # goal
        spot = goal_line + direction * 11
        add_path(fig, arc_points(spot, 34, 9.15, -53, 53) if direction == 1 else arc_points(spot, 34, 9.15, 127, 233), color=line)  # penalty arc
        add_path(fig, arc_points(spot, 34, 0.35, 0, 360, 12), closed=True, fill=line)   # penalty spot


def cone_points(keeper, facing, fov_deg, radius=vision.DEFAULT_RADIUS_M):
    """The sightline wedge: the keeper, then an arc `radius` meters away."""
    return [keeper] + arc_points(keeper[0], keeper[1], radius, facing - fov_deg / 2,
                                 facing + fov_deg / 2, 36)


def event_hover(row):
    event = row["event"]
    sight = t["legend_missed"] if row["sight"] == "missed" else t["sight_" + row["sight"]]
    why = f" · {t[REASON_KEY[row['reason']]]}" if row["reason"] else ""
    return (f"{event_clock(event)} · {t['ev'][event['type']]}<br>"
            f"{esc(event['player'])} ({esc(event['team'])})<br>{sight}{why} · "
            f"{row['distance_m']:.0f} {t['m']}")


def keeper_pitch(sense, rows, fov_deg, height=PITCH_HEIGHT, selected_id=None, full_pitch=False,
                 sight_m=vision.DEFAULT_RADIUS_M):
    """The Keeper's eyes pitch. `sense` is the keeper's position, the ball and
    the direction they face; `rows` are the last events (perceived ones; in the
    Reveal view also the missed ones, drawn hollow). Every event marker carries
    its event id, so a click can select it; `selected_id` gets a ring. `full_pitch`
    turns the dimming off. `sense["players"]` are the other players (from the tracking):
    in Keeper's eyes only those in view, in Reveal everyone, hollow when out of sight.
    `sight_m` is the sight range: the cone's length."""
    fig = go.Figure()
    keeper, ball, facing = sense["keeper"], sense["ball"], sense["facing"]
    top = PLOT_TOP
    draw_pitch(fig)

    cone = [(min(max(x, 0.0), top), min(max(y, 0.0), 68.0))
            for x, y in cone_points(keeper, facing, fov_deg, sight_m)]   # keep it on the pitch
    # Dim everything outside the cone: a big rectangle with the cone cut out of it
    # (even-odd fill), in the page background at 70% opacity
    outer = rect_points(-4, top + 2, -3, 71)
    if not full_pitch:
        fig.add_shape(type="path", layer="below", fillrule="evenodd", line=dict(width=0),
                      fillcolor=theme.rgba(theme.BG, 0.7),
                      path=path_text(outer) + " Z " + path_text(cone) + " Z")
    # The cone itself: lime at 18%, 1 px lime edge
    fig.add_shape(type="path", layer="below", fillcolor=theme.rgba(theme.LIME, 0.18),
                  line=dict(color=theme.LIME, width=1), path=path_text(cone) + " Z")

    # The other players, from the tracking: filled when in view, hollow when out of sight (Reveal only)
    crowd = [p for p in sense.get("players", []) if p["x"] <= top + 0.5]
    for mine in (True, False):
        for visible in (True, False):
            group = [p for p in crowd if (p["team"] == sense.get("team")) == mine and p["visible"] == visible]
            if not group:
                continue
            colour = theme.BODY if mine else theme.HEADING
            fig.add_trace(go.Scatter(
                x=[p["y"] for p in group], y=[p["x"] for p in group], mode="markers",
                name=t["players_mine"] if mine else t["players_theirs"],
                showlegend=visible, legendgroup="mine" if mine else "theirs",
                marker=dict(symbol="circle" if visible else "circle-open", size=8 if visible else 9,
                            color=colour, opacity=0.9 if visible else 0.5,
                            line=dict(width=1, color=theme.BG if visible else colour)),
                hovertext=[f"{p['name']} · {p['role']}" + ("" if visible else f" · {t['players_hidden']}") for p in group],
                hoverinfo="text"))

    # The trail: recent events joined oldest to newest, fading in
    shown = [r for r in rows if r["position"][0] <= top]
    n = len(shown)
    for i in range(1, n):
        a, b = shown[i - 1]["position"], shown[i]["position"]
        fig.add_trace(go.Scatter(x=[a[1], b[1]], y=[a[0], b[0]], mode="lines", showlegend=False,
                                 hoverinfo="skip",
                                 line=dict(color=theme.rgba(theme.LIME, 0.08 + 0.5 * i / n), width=2)))

    # The events, one trace per kind so the legend names each shape
    by_kind = {}
    for i, row in enumerate(shown):
        kind = "missed" if row["sight"] == "missed" else (
            "goal" if row["event"]["type"] == "goal" else row["sight"])
        opacity = 0.3 + 0.7 * (i + 1) / n
        if kind != "missed" and not vision.is_visible(keeper, facing, row["position"], fov_deg):
            opacity *= 0.55  # felt or remembered, but outside the cone right now
        by_kind.setdefault(kind, []).append((row, opacity))
    for kind in ("seen", "own", "felt", "goal", "missed"):
        items = by_kind.get(kind)
        if not items:
            continue
        hollow = kind == "missed"
        fig.add_trace(go.Scatter(
            x=[r["position"][1] for r, _ in items], y=[r["position"][0] for r, _ in items],
            mode="markers", name=t["legend_" + kind],
            marker=dict(symbol=SIGHT_SYMBOLS[kind], size=19 if kind == "goal" else 11,
                        color=theme.MONO_LABEL if hollow else theme.LIME,
                        opacity=[o for _, o in items],
                        line=dict(width=2 if hollow else 1.2,
                                  color=theme.MONO_LABEL if hollow else theme.BG)),
            hovertext=[event_hover(r) for r, _ in items], hoverinfo="text",
            customdata=[r["event"]["id"] for r, _ in items]))
    chosen = [r for r in shown if r["event"]["id"] == selected_id]
    if chosen:  # a ring around the event being inspected
        fig.add_trace(go.Scatter(x=[chosen[0]["position"][1]], y=[chosen[0]["position"][0]], mode="markers",
                                 showlegend=False, hoverinfo="skip",
                                 marker=dict(symbol="circle-open", size=27, line=dict(width=3, color=theme.HEADING))))

    # The ball: a keeper always tracks it, seen or not
    near = ball[0] <= top - 1
    ball_y = ball[0] if near else top - 1.2
    hover = t["ball"] if near else t["ball_far"].format(
        d=round(math.hypot(ball[0] - keeper[0], ball[1] - keeper[1])))
    fig.add_trace(go.Scatter(x=[ball[1]], y=[ball_y], mode="markers", name=t["ball"],
                             marker=dict(symbol="circle" if near else "triangle-up",
                                         size=10 if near else 11, color=theme.BALL,
                                         line=dict(width=1.5, color=theme.BG)),
                             hovertext=[hover], hoverinfo="text"))
    # The keeper
    fig.add_trace(go.Scatter(x=[keeper[1]], y=[keeper[0]], mode="markers", name=t["keeper"],
                             marker=dict(symbol="circle", size=17, color=theme.LIME,
                                         line=dict(width=2.5, color=theme.BG)),
                             hovertext=[t["keeper"]], hoverinfo="text"))

    # The cone's label, on its axis and kept inside the plot
    lx = max(4.0, min(top - 4.5, keeper[0] + 24 * math.cos(math.radians(facing))))
    ly = max(8.0, min(60.0, keeper[1] + 24 * math.sin(math.radians(facing))))
    fig.add_annotation(x=ly, y=lx, text=f"{t['sightline'].upper()} · {fov_deg}°", showarrow=False,
                       font=dict(family=theme.FONT_PLOTLY_MONO, size=10, color=theme.LIME),
                       bgcolor=theme.rgba(theme.BG, 0.6), borderpad=3)

    fig.update_layout(**theme.plotly_layout(height))
    fig.update_xaxes(range=[69, -1], visible=False)            # reversed: the keeper's left is on the left
    fig.update_yaxes(range=[-3.2, top], visible=False, scaleanchor="x", scaleratio=1)
    return fig


def hover_text(shot):
    event, insight = shot["event"], shot["insight"]
    text = (f"{event_clock(event)} · {esc(event['player'])} ({esc(event['team'])})<br>"
            f"{t[event['outcome']]} · {event['distance_m']} {t['m']} · {event['speed_kmh']} km/h")
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
                        color=[s["insight"]["saveability"] for s in group] if has_score else theme.BODY,
                        coloraxis="coloraxis" if has_score else None,
                        line=dict(width=1.5, color=theme.MARKER_OUTLINE)),
            hovertext=[hover_text(s) for s in group], hoverinfo="text",
            customdata=[s["event"]["id"] for s in group]))
    fig.update_layout(coloraxis=dict(
        colorscale=theme.SAVEABILITY_SCALE, cmin=0, cmax=100, showscale=show_scale,
        colorbar=dict(title=dict(text=t["saveability"], font=dict(color=theme.BODY)),
                      tickfont=dict(color=theme.BODY), tickvals=[0, 35, 65, 100], len=0.8,
                      outlinewidth=0)))


def shot_map(shots):
    """Every shot at one goal, colored by saveability (hard to save: dark; easy: lime)."""
    fig = go.Figure()
    line = theme.PITCH_LINE
    add_path(fig, rect_points(0, 52.5, 0, 68), closed=True, fill=theme.CARD, color=line)
    add_path(fig, rect_points(0, 16.5, 13.84, 54.16), closed=True, color=line)
    add_path(fig, rect_points(0, 5.5, 24.84, 43.16), closed=True, color=line)
    add_path(fig, rect_points(-1.5, 0, GOAL_Y_MIN, GOAL_Y_MAX), closed=True, color=line)
    add_path(fig, arc_points(11, 34, 9.15, -53, 53), color=line)
    add_path(fig, arc_points(52.5, 34, 9.15, 90, 270), color=line)
    # Shots are recorded in the shooter's frame (goal at x = 105): flip into this goal's frame
    add_shots(fig, shots, x_of=lambda s: s["event"]["y"], y_of=lambda s: 105 - s["event"]["x"],
              outcomes=SYMBOLS, show_scale=True)
    fig.update_layout(**theme.plotly_layout(470))
    fig.update_xaxes(range=[69, -1], visible=False)
    fig.update_yaxes(range=[-3, 54], visible=False, scaleanchor="x", scaleratio=1)
    return fig


def goal_mouth(shots):
    fig = go.Figure()
    add_path(fig, [(0, GOAL_Y_MIN), (GOAL_HEIGHT, GOAL_Y_MIN), (GOAL_HEIGHT, GOAL_Y_MAX), (0, GOAL_Y_MAX)],
             color=theme.BODY, width=2)
    add_path(fig, [(0, 29.6), (0, 38.4)], color=theme.PITCH_LINE)
    on_target = [s for s in shots if s["insight"]]
    add_shots(fig, on_target, x_of=lambda s: s["event"]["end_y"], y_of=lambda s: s["event"]["end_z"],
              outcomes=["goal", "saved"], show_scale=False)
    layout = theme.plotly_layout(230)
    layout["showlegend"] = False
    fig.update_layout(**layout)
    fig.update_xaxes(range=[38.4, 29.6], visible=False)
    fig.update_yaxes(range=[-0.15, 2.8], visible=False, scaleanchor="x", scaleratio=1)
    return fig


# ---------- Page sections ----------

def keeper_panel(snapshot, unseen=None):
    """Workload meter and danger indicator. `unseen` is (missed in the last 30 s,
    missed so far) in the Keeper's eyes views; the official panels leave it out."""
    parts = [stat(t["workload"], snapshot["workload"], meter(snapshot["workload"], WORKLOAD_MAX)),
             f'<div class="ll-stat"><span class="ll-label">{esc(t["danger"])}</span>'
             f'{danger_pill(snapshot["danger"])}</div>']
    if unseen:
        parts += [stat(t["unseen_30"], unseen[0]), stat(t["unseen_total"], unseen[1])]
    st.markdown(f'<div class="ll-panel"><div class="ll-panel-row">{"".join(parts)}</div></div>',
                unsafe_allow_html=True)


def numbers_markdown(moment):
    """The stats behind a card, for its "Show the numbers" expander."""
    d, shot = moment["distribution"], moment["shot"]
    lines = [f"- **{t['n_off_line']}**: {moment['keeper_off_line_m']} {t['m']}",
             f"- **{t['n_distance']}**: {moment['event_distance_m']} {t['m']}",
             f"- **{t['n_sight']}**: {t['sight_' + moment['sight']]}",
             f"- **{t['n_missed_before']}**: {moment['unseen_before']}"]
    if moment["saveability"] is not None:
        lines = [f"- **{t['n_saveability']}**: {moment['saveability']}/100",
                 f"- **{t['n_verdict']}**: {verdict_label(moment['verdict'])}",
                 f"- **{t['n_key_factor']}**: {moment['key_factor']}",
                 f"- **{t['n_situation']}**: {t['sit'][moment['situation']]}",
                 f"- **{t['n_shot']}**: {shot['distance_m']} {t['m']}, {shot['speed_kmh']} km/h, "
                 f"{moment['player']}"] + lines
    if d:
        lines = [f"- **{t['quality']}**: {d['quality']}/100 ({dist_verdict_label(d['verdict'])})",
                 f"- **{t['n_target']}**: {d['target_role']} {d['target_player']}, {d['distance_m']} {t['m']}",
                 f"- **{t['n_method']}**: {d['method'].replace('_', ' ')} ({d['technique'].replace('_', ' ')})",
                 f"- **{t['n_pressure']}**: {d['pressure']}",
                 f"- **{t['n_decision']}**: {d['decision_score']}, **{t['n_difficulty']}**: {d['difficulty']}",
                 f"- **{t['n_options']}**: {d['options_seen']}, **{t['n_unseen_options']}**: {d['unseen_options']}"
                 ] + lines
    return "\n".join(lines)


def moment_card(moment):
    """One key moment: a mono label row, a headline with the verdict, the
    explanation, sight pills (text, not color alone), and the numbers."""
    d = moment["distribution"]
    if moment["type"] == "goal":
        headline = f"{t['card_goal']} · {verdict_label(moment['verdict'])}"
    elif moment["saveability"] is not None:
        headline = verdict_label(moment["verdict"]).capitalize()
    elif d:
        headline = f"{t['card_keeper_distribution']} · {dist_verdict_label(d['verdict'])}"
    else:
        headline = t["card_" + moment["type"]]
    pills = pill(t["sight_" + moment["sight"]], lime=moment["sight"] == "seen")
    if moment["saveability"] is not None:
        pills += pill(f"{t['saveability']} {moment['saveability']}")
    if d:
        pills += pill(f"{t['quality']} {d['quality']}")
    chosen = st.session_state.selected_event_id == moment["event_id"]
    with st.container(key=f"card_sel_{moment['event_id']}" if chosen else f"card_{moment['event_id']}"):
        st.markdown(f'<div class="ll-card-head"><span class="ll-clock">{moment["clock"]}</span>'
                    f'<span class="ll-label">{esc(t["tag_" + moment["type"]])}</span>{pills}</div>'
                    f'<div class="ll-headline">{esc(headline)}</div>', unsafe_allow_html=True)
        body = get_insight_text(moment, mode, lang, club, "eyes", live=False)   # cache or quick text: never block the replay
        st.markdown(f'<div class="ll-body">{esc(body)}</div>', unsafe_allow_html=True)
        with st.expander(t["numbers"]):
            st.markdown(numbers_markdown(moment))
        st.button(t["showing_on_pitch"] if chosen else t["show_on_pitch"], key=f"show_{moment['event_id']}",
                  on_click=choose, args=(moment["event_id"],), disabled=chosen, icon=":material/my_location:")


def cards_column(moments, teams):
    st.markdown(f"#### {t['moments']}")
    shown = [m for m in moments if m["keeper_team"] in teams]
    with st.container(height=1100, border=False):
        if not shown:
            st.caption(t["no_moments"])
        for moment in reversed(shown):  # newest first
            moment_card(moment)


# ---------- Picking an event to inspect ----------

CLICK_CONFIG = {"displayModeBar": False}
FILTERS = {  # the Events list filters: name -> event types (None = all)
    "all": None,
    "shots": ("shot", "goal"),
    "passes": ("pass", "through_ball", "cross", "box_entry"),
    "keeper": ("keeper_save", "keeper_claim", "keeper_sweep", "keeper_close_down", "keeper_distribution",
               "keeper_punch"),
    "other": "rest",   # everything the other filters leave out: tackles, set pieces, fouls, cards...
}
NAMED_TYPES = {kind for types in FILTERS.values() if isinstance(types, tuple) for kind in types}


@st.cache_data
def all_moments(fingerprint):
    """Every key moment of the match, for the Previous / Next moment buttons."""
    return replay_to(match, None, END_SEC)[2]


def current_team():
    """The keeper whose eyes the pitch views use right now."""
    return st.session_state.get("eyes_keeper", HOME) if club == BOTH else club


def current_filter():
    return filter_for(current_team(), st.session_state.get("fov", vision.DEFAULT_FOV_DEG),
                      st.session_state.get("sight", vision.DEFAULT_RADIUS_M))


def reveal_on():
    return st.session_state.get("view", EYES) == REVEAL


def can_inspect(event_id):
    """May this event be selected right now? It must have happened, and (in
    Keeper's eyes) the keeper must have perceived it. In Reveal any event will do."""
    return current_filter().can_select(event_id, st.session_state.match_sec, reveal_on())


def choose(event_id):
    selection.select(st.session_state, event_id, can_inspect(event_id))


def on_chart_pick(chart_key):
    """Called when a marker on a chart is clicked: select that event."""
    try:
        points = st.session_state[chart_key]["selection"]["points"]
        found = points[0].get("customdata") if points else None
    except (KeyError, TypeError, IndexError):
        return
    if isinstance(found, (list, tuple)):
        found = found[0] if found else None
    if found is not None:
        choose(int(found))


def on_list_pick(list_key):
    """Called when a row in the Events list is clicked."""
    try:
        rows = st.session_state[list_key]["selection"]["rows"]
    except (KeyError, TypeError):
        return
    ids = st.session_state.get("evlist_ids", [])
    if rows and rows[0] < len(ids):
        choose(ids[rows[0]])


def selected_second():
    row = current_filter().lookup(st.session_state.selected_event_id, True) \
        if st.session_state.selected_event_id is not None else None
    return match_second(row["event"]) if row else None


def on_scrub():
    """The minute slider moved: jump there and pause."""
    selection.jump_to(st.session_state, min(END_SEC, st.session_state.scrub * 60),
                      selected_second=selected_second())


def jump_moment(direction):
    """Previous / Next key moment for the keeper being watched: jump to it, select it, pause."""
    now = st.session_state.match_sec
    moments = [m for m in all_moments(match_fingerprint()) if m["keeper_team"] == current_team()]
    if direction > 0:
        target = next((m for m in moments if m["second"] + 2 > now), None)
    else:
        target = next((m for m in reversed(moments) if m["second"] + 2 < now - 1), None)
    if target is None:
        return
    st.session_state.match_sec = target["second"] + 2
    selection.jump_to(st.session_state, target["second"] + 2, target["event_id"],
                      allowed=can_inspect(target["event_id"]), selected_second=selected_second())


def back_to_live():
    selection.back_to_live(st.session_state, st.session_state.match_sec >= END_SEC)


def events_list(f, now, reveal):
    """A scrollable list of events up to now, with filters. Clicking a row selects it."""
    choice = st.radio(t["tab_events"], list(FILTERS), key="ev_filter", horizontal=True,
                      format_func=lambda k: t["filter_" + k], label_visibility="collapsed")
    wanted = FILTERS[choice]
    ids, table = [], []
    for event_id in reversed(f.selectable_ids(now, reveal)):   # newest first
        row = f.lookup(event_id, reveal)
        event = row["event"]
        if wanted == "rest" and event["type"] in NAMED_TYPES:
            continue
        if isinstance(wanted, tuple) and event["type"] not in wanted:
            continue
        ids.append(event_id)
        table.append({t["col_clock"]: event_clock(event), t["col_event"]: t["ev"][event["type"]],
                      t["col_player"]: event["player"], t["col_team"]: event["team"],
                      t["col_sight"]: inspector.SIGHT_NAMES[lang][row["sight"]]})
    st.session_state.evlist_ids = ids
    if not table:
        st.caption(t["no_events"])
        return
    list_key = f"evlist_{choice}_{len(ids)}_{int(reveal)}"   # a new list gets a fresh (empty) selection
    st.dataframe(table, hide_index=True, key=list_key, height=430, width="stretch",
                 on_select=partial(on_list_pick, list_key), selection_mode="single-row")


def controls_strip(now, finished):
    """The minute scrubber, Previous / Next key moment, and Back to live."""
    ss = st.session_state
    ss.scrub = min(END_MIN, int(now // 60))          # the slider follows the clock
    slider_col, prev_col, next_col, live_col = st.columns([5, 1.6, 1.6, 1.8], vertical_alignment="bottom")
    slider_col.select_slider(t["scrub"], options=list(range(END_MIN + 1)), key="scrub", on_change=on_scrub,
                               format_func=lambda m: minute_text(m * 60))   # shows 44, 45+1, 45+2, 46, ... 90+4
    prev_col.button(t["prev_moment"], key="prev_moment", on_click=jump_moment, args=(-1,),
                    icon=":material/skip_previous:")
    next_col.button(t["next_moment"], key="next_moment", on_click=jump_moment, args=(1,),
                    icon=":material/skip_next:")
    live_col.button(t["back_to_live"], key="back_to_live", type="primary", on_click=back_to_live,
                    icon=":material/play_arrow:",
                    disabled=(ss.playing and ss.selected_event_id is None) or (finished and ss.selected_event_id is None))


def inspector_panel(team, now, reveal):
    """The inspector: the moment you picked, its snapshot, its insight and its numbers."""
    event_id = st.session_state.selected_event_id
    if event_id is None:
        st.caption(t["inspect_hint"])
        return
    f = filter_for(team, fov, sight)
    if not f.can_select(event_id, now, reveal):
        st.markdown(f'<div class="ll-panel">{esc(t["not_perceived"])}</div>', unsafe_allow_html=True)
        return
    facts = f.facts(event_id, reveal=reveal, upto_sec=now)
    event = facts["event"]
    with st.spinner(t["asking_agents"]):          # only slow on a cache miss, when the agents are asked
        text, source = get_event_text(team, facts, mode, lang, club, "eyes")
    players = esc(event["player"])
    if facts["type"] in ("pass", "through_ball", "cross", "box_entry") and facts["receiver"]:
        players += f" → {esc(facts['receiver'])}"
    elif facts["type"] == "keeper_distribution":
        players += f" → {esc(event['target_player'])}"
    source_pill = pill(t["ai_insight"] if source == "ai" else t["quick_insight"], lime=source == "ai")
    sight_pill = pill(inspector.SIGHT_NAMES[lang][facts["sight"]], lime=facts["sight"] == "seen")
    window = f.window_summary(event_id)
    with st.container(key="inspector"):
        text_col = st.container()                      # the moment itself is shown on the big pitch below
        with text_col:
            st.markdown(f'<div class="ll-inspector-head"><span class="ll-clock">{facts["clock"]}</span>'
                        f'<span class="ll-label">{esc(t["ev"][facts["type"]])}</span>{sight_pill}{source_pill}</div>'
                        f'<div class="ll-headline">{players}</div>'
                        f'<div class="ll-body">{esc(text)}</div>'
                        f'<div class="ll-seen-line">{esc(t["window_line"].format(s=30, seen=window["seen"], missed=window["missed"]))}</div>',
                        unsafe_allow_html=True)
            if reveal and window["missed"]:       # Reveal lists what was missed; Keeper's eyes only counts it
                st.markdown(f"**{t['missed_list']}**")
                st.markdown("".join(
                    f'<div class="ll-missed"><span class="ll-clock">{event_clock(m.event)}</span>'
                    f'<span>{esc(t["ev"][m.event["type"]])} · {esc(m.event["player"])}</span>'
                    f'<span>{esc(inspector.MISSED_WHY[lang][m.reason])}</span></div>'
                    for m in window["missed_events"][-8:]), unsafe_allow_html=True)
            with st.expander(t["numbers"]):
                st.markdown("\n".join(f"- **{label}**: {value}" for label, value in inspector.numbers_rows(facts, lang)))
    st.button(t["back_to_live"], key="inspector_back_to_live", on_click=back_to_live,
              icon=":material/play_arrow:")


def side_tabs(first_label, first_content, f, now, reveal):
    """The right-hand column: the key moments (or the missed list) and the Events list."""
    first_tab, events_tab = st.tabs([first_label, t["tab_events"]])
    with first_tab:
        first_content()
    with events_tab:
        events_list(f, now, reveal)


def unseen_counts(f, now):
    return (f.unseen_count(since_sec=now - UNSEEN_WINDOW_SEC, until_sec=now), f.unseen_count(until_sec=now))


def pitch_focus(f, now, reveal):
    """What the big pitch shows: the live moment, or the selected event as it was (its keeper,
    ball and players, and the events leading up to it). Returns (sense, rows, focused)."""
    chosen = st.session_state.selected_event_id
    if chosen is not None and f.can_select(chosen, now, reveal):
        return (f.snapshot(chosen, reveal), f.recent(RECENT_EVENTS, now, include_missed=reveal, upto_id=chosen), True)
    return f.state_at(now, reveal=reveal), f.recent(RECENT_EVENTS, now, include_missed=reveal), False


def focus_note(f):
    row = f.lookup(st.session_state.selected_event_id, True)
    st.caption(t["pitch_focus"].format(clock=event_clock(row["event"])))


def eyes_view(team, now, moments):
    f = filter_for(team, fov, sight)
    sense, rows, focused = pitch_focus(f, now, False)
    pitch_col, cards_col = st.columns([3, 2], gap="large")  # pitch about 60%, cards about 40%
    with pitch_col:
        st.markdown(f"#### {f.keeper_name()} · {team}")
        keeper_panel(perceived_state(team, fov, now, sight).snapshot(now)[team], unseen_counts(f, now))
        chart_key = f"pitch_{team}"
        if focused:
            focus_note(f)
        st.plotly_chart(keeper_pitch(sense, rows, fov, selected_id=st.session_state.selected_event_id,
                                     full_pitch=full_pitch, sight_m=sight),
                        key=chart_key, width="stretch", config=CLICK_CONFIG,
                        on_select=partial(on_chart_pick, chart_key), selection_mode="points")
        st.caption(t["pitch_help"])
    with cards_col:
        side_tabs(t["tab_moments"], lambda: cards_column(moments, [team]), f, now, reveal=False)


def missed_panel(f, now):
    """Reveal view: the missed events by reason, and the latest ones."""
    missed = [m for m in f.missed if m.reason != "unseen_option" and match_second(m.event) <= now]
    options_out = sum(pe.event.get("unseen_options", 0) for pe in f.perceived if pe.second <= now)
    st.markdown(f"#### {t['reveal_title']}")
    st.caption(t["reveal_help"])
    if not missed and not options_out:
        st.markdown(f'<div class="ll-panel">{esc(t["nothing_missed"])}</div>', unsafe_allow_html=True)
        return
    counts = {}
    for m in missed:
        counts[m.reason] = counts.get(m.reason, 0) + 1
    rows = "".join(f'<div class="ll-missed"><span>{esc(t[REASON_KEY[k]])}</span>'
                   f'<span class="ll-clock">{v}</span></div>'
                   for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
    rows += (f'<div class="ll-missed"><span>{esc(t["options_out"])}</span>'
             f'<span class="ll-clock">{options_out}</span></div>')
    latest = "".join(f'<div class="ll-missed"><span class="ll-clock">{event_clock(m.event)}</span>'
                     f'<span>{esc(t["ev"][m.event["type"]])} · {esc(m.event["player"])}</span></div>'
                     for m in missed[-6:][::-1])
    st.markdown(f'<div class="ll-panel">{rows}<div style="height:12px"></div>{latest}</div>',
                unsafe_allow_html=True)


def reveal_view(team, now, moments, shots, official_state):
    f = filter_for(team, fov, sight)
    sense, rows, focused = pitch_focus(f, now, True)
    pitch_col, side_col = st.columns([3, 2], gap="large")
    with pitch_col:
        st.markdown(f"#### {f.keeper_name()} · {team}")
        keeper_panel(perceived_state(team, fov, now, sight).snapshot(now)[team], unseen_counts(f, now))
        chart_key = f"reveal_pitch_{team}"
        if focused:
            focus_note(f)
        st.plotly_chart(keeper_pitch(sense, rows, fov, selected_id=st.session_state.selected_event_id,
                                     full_pitch=full_pitch, sight_m=sight),
                        key=chart_key, width="stretch", config=CLICK_CONFIG,
                        on_select=partial(on_chart_pick, chart_key), selection_mode="points")
        st.caption(t["pitch_help"] + t["pitch_help_reveal"])
    with side_col:
        side_tabs(t["reveal_title"], lambda: missed_panel(f, now), f, now, reveal=True)
    st.markdown(f"#### {t['official']}")
    for goal_team in followed:
        st.markdown(f"##### {keeper_eyes(goal_team).keeper_name()} · {goal_team}")
        keeper_panel(official_state.snapshot(now)[goal_team])
        faced = [s for s in shots if s["keeper_team"] == goal_team]
        map_col, mouth_col = st.columns(2, gap="large")
        with map_col:
            st.caption(t["shot_map"])
            map_key = f"map_{goal_team}"
            st.plotly_chart(shot_map(faced), key=map_key, width="stretch", config=CLICK_CONFIG,
                            on_select=partial(on_chart_pick, map_key), selection_mode="points")
        with mouth_col:
            st.caption(t["goal_mouth"])
            st.plotly_chart(goal_mouth(faced), key=f"goal_{goal_team}", width="stretch",
                            config={"displayModeBar": False})
    cards_column(moments, followed)


def report_tab(now, finished):
    if not finished:
        st.info(t["report_wait"])
    for team in followed:
        r = perceived_state(team, vision.DEFAULT_FOV_DEG, now).keeper_report()[team]
        st.subheader(f"{keeper_eyes(team).keeper_name()} · {team}")
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
            with st.spinner(t["asking_narrator"]):
                text = get_report_text(team, mode, lang)
            if text:
                st.write(text)
            else:
                st.caption(t["report_missing"])


# ---------- The live area ----------
# Everything below the header is a fragment: while the match plays, only this
# part reruns on each tick, so the sidebar and the stylesheet are not re-sent.
# Changing a sidebar control still reruns the whole app. Pause switches the
# timer off (run_every=None).

def advance_clock():
    """Move the match clock by the real time since the last update, times the
    replay speed. Using the wall clock keeps the speed right however often the
    screen refreshes."""
    ss = st.session_state
    now_wall = time.time()
    if ss.playing:
        step = min(now_wall - ss.last_wall, MAX_STEP_SEC)
        ss.match_sec = min(END_SEC, ss.match_sec + step * speed)
    ss.last_wall = now_wall


def render_match():
    advance_clock()
    ss = st.session_state
    now = ss.match_sec
    finished = now >= END_SEC
    official_state, shots, moments, score = replay_to(match, None, now)

    if club == BOTH:  # follow one keeper at a time in the pitch views
        team = st.radio(t["keeper_pick"], [HOME, AWAY], key="eyes_keeper", horizontal=True)
    else:
        team = club
    reveal = view == REVEAL
    ticks = [(m["second"], f"{m['clock']} {t['ev'][m['type']]}") for m in all_moments(match_fingerprint())
             if m["keeper_team"] == team]

    st.markdown(topbar_html(score, now), unsafe_allow_html=True)
    st.markdown(timeline_html(now, ticks), unsafe_allow_html=True)
    controls_strip(now, finished)
    inspector_panel(team, now, reveal)

    live_tab, report_tab_ = st.tabs([t["tab_live"], t["tab_report"]])
    with live_tab:
        if view == EYES:
            eyes_view(team, now, moments)
        else:
            reveal_view(team, now, moments, shots, official_state)
    with report_tab_:
        report_tab(now, finished)
    st.caption(t["synthetic"])

    if finished:
        ss.playing = False
    if ss.playing != ss.timer_on:
        st.rerun()  # a full rerun, so the timer is switched on or off to match


st.session_state.timer_on = st.session_state.playing
st.fragment(render_match, run_every=TICK_SEC if st.session_state.playing else None)()
