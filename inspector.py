"""What to say about one event the user clicks on.

Pure Python (no Streamlit, no match file). It works from the `facts` dict that
PerceptionFilter.facts() builds, so it can only ever talk about what the keeper
could perceive (or, in the Reveal view, what the full data says).

Three jobs:
  template_text(facts, language)   an instant second-person line for ANY event
                                   type, in English or Spanish (the "Quick insight")
  notable_reason(facts)            is this event worth an AI explanation?
  numbers_rows(facts, language)    the rows shown under "Show the numbers"

Event wording for the key moments (shots, goals, claims, sweeps, distributions)
lives here too (second_person_text), so there is one place to change it.
"""
from scoring import REASON_TEXT

# ---------- Notable passes: the ones that get an AI explanation ----------
LONG_FORWARD_M = 20.0   # a pass that gains at least this much ground, going forward
LONG_BALL_M = 45.0      # a ball that travels at least this far
# Also notable: every keeper pass, a pass that sets up a shot, and a pass lost in
# its team's own third. (This match has none of the last kind: its possessions
# only break down in the attacking half.)

VERDICT_ES = {"should save": "debió pararlo", "tough save": "parada difícil",
              "near-unstoppable": "casi imparable"}
DIST_VERDICT_ES = {"excellent": "excelente", "safe": "segura", "risky": "arriesgada",
                   "turnover": "pérdida"}
REASON_ES = {
    "free_man": "encontraste al compañero libre",
    "relieve_press": "sacaste el balón con calma bajo presión",
    "break_press_long": "jugaste largo por encima de la presión",
    "switch_play": "cambiaste el juego al otro lado",
    "safe_retention": "mantuviste el balón sin riesgos",
    "quick_counter": "lo soltaste rápido para lanzar un contraataque",
}
METHOD_EN = {"throw": "throw it", "roll": "roll it out", "ground_pass": "play it short",
             "kick": "kick it long"}
METHOD_ES = {"throw": "lo lanzas con la mano", "roll": "lo sacas rodando",
             "ground_pass": "lo juegas al pie", "kick": "lo despejas largo"}
SITUATION_EN = {"open_play": "from open play", "cutback": "from a cutback",
                "header_from_cross": "with a header from a cross", "one_on_one": "one on one",
                "two_on_one": "after you closed down one attacker and he squared it",
                "rebound": "from the rebound after your save", "second_ball": "from a second ball",
                "corner": "from a corner", "free_kick": "from a free kick", "penalty": "from the penalty spot"}
SITUATION_ES = {"open_play": "en juego abierto", "cutback": "tras un pase atrás",
                "header_from_cross": "de cabeza tras un centro", "one_on_one": "mano a mano",
                "two_on_one": "después de que saliste a un atacante y él se la dejó al otro",
                "rebound": "en el rechace de tu parada", "second_ball": "en una segunda jugada",
                "corner": "tras un córner", "free_kick": "de falta directa", "penalty": "desde el punto de penalti"}

# ---------- Words, in English and Spanish ----------
EVENT_NAMES = {
    "en": {"pass": "Pass", "cross": "Cross", "through_ball": "Through ball", "box_entry": "Box entry",
           "shot": "Shot", "goal": "Goal", "keeper_save": "Save", "keeper_claim": "Claim",
           "keeper_sweep": "Sweep", "keeper_close_down": "Close-down",
           "keeper_distribution": "Distribution", "tackle": "Tackle",
           "possession_change": "Possession change", "dribble": "Dribble", "stoppage": "Stoppage",
           "throw_in": "Throw-in", "corner": "Corner", "free_kick": "Free kick", "penalty": "Penalty",
           "foul": "Foul", "card": "Card", "offside": "Offside", "substitution": "Substitution",
           "keeper_punch": "Punch", "off_ball_run": "Run off the ball"},
    "es": {"pass": "Pase", "cross": "Centro", "through_ball": "Pase al hueco", "box_entry": "Entrada al área",
           "shot": "Disparo", "goal": "Gol", "keeper_save": "Parada", "keeper_claim": "Centro atrapado",
           "keeper_sweep": "Salida", "keeper_close_down": "Achique",
           "keeper_distribution": "Distribución", "tackle": "Entrada",
           "possession_change": "Cambio de posesión", "dribble": "Regate", "stoppage": "Juego parado",
           "throw_in": "Saque de banda", "corner": "Córner", "free_kick": "Tiro libre", "penalty": "Penalti",
           "foul": "Falta", "card": "Tarjeta", "offside": "Fuera de juego", "substitution": "Cambio",
           "keeper_punch": "Despeje de puños", "off_ball_run": "Desmarque"},
}
DIRECTION = {"en": {"forward": "forward", "lateral": "sideways", "backward": "backward"},
             "es": {"forward": "hacia delante", "lateral": "en horizontal", "backward": "hacia atrás"}}
PRESSURE = {"en": {"low": "low", "medium": "medium", "high": "high"},
            "es": {"low": "baja", "medium": "media", "high": "alta"}}
OUTCOME = {"en": {"completed": "it finds a teammate", "lost": "the ball is lost",
                  "keeper": "the keeper deals with it", "shot": "it sets up a shot"},
           "es": {"completed": "encuentra a un compañero", "lost": "se pierde el balón",
                  "keeper": "el portero la resuelve", "shot": "prepara un disparo"}}
MISSED_WHY = {"en": {"beyond_radius": "too far away", "outside_fov": "outside your sightline",
                     "blocked": "a player is in the way"},
              "es": {"beyond_radius": "demasiado lejos", "outside_fov": "fuera de tu línea de visión",
                     "blocked": "un jugador te tapa la vista"}}
SIGHT_NAMES = {"en": {"own": "Your action", "seen": "Seen clearly", "felt": "Late sight", "missed": "Missed"},
               "es": {"own": "Tu acción", "seen": "Visto con claridad", "felt": "Visto tarde", "missed": "No visto"}}
FACTOR_NAMES = {
    "en": {"placement": "Placement", "reaction": "Reaction time", "distance": "Distance", "speed": "Speed",
           "reach": "Reach", "angle": "Angle", "no_deflection": "Clean strike", "lane": "Clear lane",
           "recovery": "Recovery", "keeper_set": "Keeper set", "depth": "Depth", "shift": "Ball shift",
           "swerve": "Swerve", "foot_strike": "Foot strike"},
    "es": {"placement": "Colocación", "reaction": "Tiempo de reacción", "distance": "Distancia",
           "speed": "Velocidad", "reach": "Alcance", "angle": "Ángulo", "no_deflection": "Golpeo limpio",
           "lane": "Línea despejada", "recovery": "Recuperación", "keeper_set": "Portero listo",
           "depth": "Posición", "shift": "Cambio del balón", "swerve": "Efecto", "foot_strike": "Golpeo con el pie"},
}
LABELS = {
    "en": {"saveability": "Saveability", "verdict": "Verdict", "key_factor": "Key factor",
           "situation": "Situation", "quality": "Quality", "decision": "Decision score",
           "difficulty": "Difficulty", "target": "Target", "method": "Method", "pressure": "Pressure",
           "options": "Options in view", "unseen_options": "Options out of sight",
           "distance": "Distance", "direction": "Direction", "forward": "Ground gained",
           "outcome": "Outcome", "leads_to_shot": "Leads to a shot", "off_line": "You stood off your line",
           "from_you": "Distance from you", "sight": "Sight", "yes": "yes", "no": "no",
           "not_seen": "out of your sight", "factors": "Factors (0 hard, 1 easy)", "n/a": "not tracked here",
           "speed": "Speed", "result": "Result"},
    "es": {"saveability": "Salvabilidad", "verdict": "Veredicto", "key_factor": "Factor clave",
           "situation": "Situación", "quality": "Calidad", "decision": "Puntuación de decisión",
           "difficulty": "Dificultad", "target": "Destino", "method": "Método", "pressure": "Presión",
           "options": "Opciones a la vista", "unseen_options": "Opciones fuera de vista",
           "distance": "Distancia", "direction": "Dirección", "forward": "Terreno ganado",
           "outcome": "Resultado", "leads_to_shot": "Acaba en tiro", "off_line": "Estabas fuera de tu línea",
           "from_you": "Distancia a ti", "sight": "Visión", "yes": "sí", "no": "no",
           "not_seen": "fuera de tu vista", "factors": "Factores (0 difícil, 1 fácil)", "n/a": "no registrado aquí",
           "speed": "Velocidad", "result": "Resultado"},
}


# ---------- Which events deserve an AI explanation ----------

def notable_reason(facts):
    """Why an event is notable (a short code), or None. Pass FULL facts (from
    PerceptionFilter.facts with reveal=True): this only decides whether to ask
    the agents, and the agents themselves are then given perceived-only facts.
    "key_moment" events already have explanations in the moment cache."""
    if facts["key_moment"]:
        return "key_moment"
    if facts["type"] == "keeper_distribution":
        return "keeper_pass"
    move = facts["ball_move"]
    if move is None:
        return None
    if move["leads_to_shot"]:
        return "leads_to_shot"
    if move["outcome"] == "lost" and move["own_third"]:
        return "lost_own_third"
    if move["direction"] == "forward" and (move["forward_m"] or 0) >= LONG_FORWARD_M:
        return "long_forward"
    if (move["distance_m"] or 0) >= LONG_BALL_M:
        return "long_ball"
    return None


# ---------- What the agents are told ----------

def agent_facts(facts):
    """A compact, perceived-only version of an event's facts for the agents: no
    positions lists, no traffic, nothing the keeper could not perceive."""
    keep = ("clock", "type", "team", "player", "receiver", "sight", "distance_m",
            "keeper_off_line_m", "unseen_before", "ball_move")
    return {k: facts[k] for k in keep if k in facts}


# ---------- The key moments, in the second person ----------

def moment_like(facts):
    """The fields second_person_text needs, taken from an event's facts. Goals and
    saves are explained together with their shot (facts["shot_ref"])."""
    event, insight = facts["event"], facts["insight"]
    shot_event, shot_insight = (event, insight) if event["type"] == "shot" else (None, None)
    if event["type"] in ("goal", "keeper_save") and facts.get("shot_ref"):
        shot_event, shot_insight = facts["shot_ref"]["event"], facts["shot_ref"]["insight"]
    moment = {"player": shot_event["player"] if shot_event else event["player"], "type": event["type"],
              "keeper_off_line_m": facts["keeper_off_line_m"], "sight": facts["sight"],
              "distribution": None, "shot": None, "saveability": None, "verdict": None,
              "key_factor": None, "situation": None}
    if shot_insight and shot_insight.get("saveability") is not None:
        moment.update(saveability=shot_insight["saveability"], verdict=shot_insight["verdict"],
                      key_factor=shot_insight["key_factor"], situation=shot_insight.get("situation", "open_play"),
                      shot={k: shot_event.get(k) for k in ("distance_m", "speed_kmh", "body_part")})
    if event["type"] == "keeper_distribution" and insight.get("quality") is not None:
        d = {k: event[k] for k in ("trigger", "method", "technique", "target_player", "target_role",
                                   "distance_m", "direction", "pressure", "reason", "outcome",
                                   "x_gain_m", "led_to_shot")}
        d.update({k: insight[k] for k in ("difficulty", "decision_score", "quality", "verdict", "best_option")})
        d["unseen_options"] = event.get("unseen_options", 0)
        d["options_seen"] = len(event["options"])
        moment["distribution"] = d
    return moment


def second_person_text(moment, spanish):
    """Template text for a key moment, built from the scoring fields."""
    off = round(moment["keeper_off_line_m"])
    d, shot = moment["distribution"], moment["shot"]
    if d:
        reason = (REASON_ES if spanish else REASON_TEXT).get(d["reason"], "")
        verb = (METHOD_ES if spanish else METHOD_EN)[d["method"]]
        if spanish:
            return (f"Estás a {off} m de tu línea y {verb} hacia {d['target_role']} "
                    f"{d['target_player']}, a {d['distance_m']} m, con presión {PRESSURE['es'][d['pressure']]}: "
                    f"{reason}. Calidad {d['quality']}/100, {DIST_VERDICT_ES[d['verdict']]}.")
        return (f"You're {off} m off your line and {verb} to {d['target_role']} "
                f"{d['target_player']}, {d['distance_m']} m away, under {d['pressure']} pressure: "
                f"you {reason}. Quality {d['quality']}/100, {d['verdict']}.")
    if moment["saveability"] is not None:
        where = (SITUATION_ES if spanish else SITUATION_EN)[moment["situation"]]
        late = moment["sight"] == "felt"
        if spanish:
            lead = ("No lo ves venir; solo sabes de él cuando llega a tu portería. "
                    if late else f"Estás a {off} m de tu línea. ")
            scored = " Entra." if moment["type"] == "goal" else ""
            return (f"{lead}{moment['player']} dispara desde {shot['distance_m']} m, {where}. "
                    f"Salvabilidad {moment['saveability']}/100: {VERDICT_ES[moment['verdict']]}.{scored}")
        lead = ("You don't see it develop; you only know when it reaches your goal. "
                if late else f"You're {off} m off your line. ")
        scored = " It goes in." if moment["type"] == "goal" else ""
        return (f"{lead}{moment['player']} shoots from {shot['distance_m']} m, {where}. "
                f"Saveability {moment['saveability']}/100: {moment['verdict']} ({moment['key_factor']}).{scored}")
    if moment["type"] == "keeper_claim":
        return (f"Sales a por el centro, a {off} m de tu línea, y lo atrapas." if spanish
                else f"You come for the cross, {off} m off your line, and claim it.")
    return (f"Sales a despejar el peligro, a {off} m de tu línea." if spanish
            else f"You rush out, {off} m off your line, to clear the danger.")


# ---------- Any event, in the second person ----------

def _mine(facts):
    """Is this one of the followed keeper's own actions?"""
    return facts["type"].startswith("keeper_") and facts["team"] == facts["keeper_team"]


def _sight_clause(facts, spanish):
    sight, why = facts["sight"], facts["reason"]
    if sight == "seen":
        return "Está en tu línea de visión." if spanish else "It's in your sightline."
    if sight == "felt":
        return ("Solo te enteras cuando llega a tu portería." if spanish
                else "You only know about it when it reaches your goal.")
    if sight == "missed":
        text = MISSED_WHY["es" if spanish else "en"][why]
        return f"No lo ves: {text}." if spanish else f"You can't see this one: {text}."
    return ""


def _ball_move_details(facts, spanish):
    """', 18 m forward under low pressure; it finds a teammate' for a pass."""
    move, lang = facts["ball_move"], "es" if spanish else "en"
    parts = ""
    if move["distance_m"] is not None and move["distance_m"] >= 1:
        parts += f", {move['distance_m']:.0f} m {DIRECTION[lang][move['direction']]}"
    if move["pressure"]:
        parts += (f" con presión {PRESSURE[lang][move['pressure']]}" if spanish
                  else f" under {PRESSURE[lang][move['pressure']]} pressure")
    if move["outcome"]:
        parts += f"; {OUTCOME[lang][move['outcome']]}"
    if move["leads_to_shot"] and move["outcome"] != "shot":
        parts += " y acaba en tiro" if spanish else " and leads to a shot"
    return parts


def _action_sentence(facts, spanish):
    """One sentence about what happened (no keeper lead, no sight clause)."""
    e, kind = facts["event"], facts["type"]
    player, team = e["player"], e["team"]
    if kind in ("pass", "through_ball", "cross", "box_entry"):
        receiver = facts["receiver"]
        if spanish:
            base = {"pass": f"{player} pasa" + (f" a {receiver}" if receiver else ""),
                    "through_ball": f"{player} filtra un pase al hueco", "cross": f"{player} manda un centro",
                    "box_entry": f"{player} entra con el balón en el área"}[kind]
        else:
            base = {"pass": f"{player} passes" + (f" to {receiver}" if receiver else ""),
                    "through_ball": f"{player} slips in a through ball", "cross": f"{player} whips in a cross",
                    "box_entry": f"{player} carries the ball into the box"}[kind]
        return base + _ball_move_details(facts, spanish)
    if kind == "tackle":
        return f"{player} ({team}) hace una entrada" if spanish else f"{player} ({team}) makes a tackle"
    if kind == "possession_change":
        return (f"{player} ({team}) recupera el balón" if spanish
                else f"{player} ({team}) wins the ball back")
    if kind == "shot":
        outcome = {"off_target": ("se va fuera", "goes wide or over"), "blocked": ("es bloqueado", "is blocked"),
                   "saved": ("va a puerta", "is on target"), "goal": ("va a puerta", "is on target")}[e["outcome"]]
        return (f"{player} dispara desde {e['distance_m']} m y {outcome[0]}" if spanish
                else f"{player} shoots from {e['distance_m']} m and it {outcome[1]}")
    if kind == "goal":
        return f"{player} marca ({e['score']})" if spanish else f"{player} scores ({e['score']})"
    if kind == "keeper_save":
        shooter = (facts.get("shot_ref") or {}).get("event", {}).get("player")
        if _mine(facts):
            return (f"Paras el disparo" + (f" de {shooter}" if shooter else "") if spanish
                    else "You save " + (f"{shooter}'s shot" if shooter else "the shot"))
        return (f"{player}, el otro portero, para el disparo" if spanish
                else f"{player}, the other keeper, saves the shot")
    if kind == "keeper_close_down":
        if _mine(facts):
            return (f"Sales de tu línea a cerrar a {e['target_player']}" if spanish
                    else f"You come off your line to close down {e['target_player']}")
        return (f"{player}, el otro portero, sale a cerrar a {e['target_player']}" if spanish
                else f"{player}, the other keeper, comes out to close down {e['target_player']}")
    if kind in ("keeper_claim", "keeper_sweep"):
        verb = {"keeper_claim": ("atrapa un centro", "claims a cross"),
                "keeper_sweep": ("sale a despejar", "sweeps up the danger")}[kind]
        return f"{player}, el otro portero, {verb[0]}" if spanish else f"{player}, the other keeper, {verb[1]}"
    if kind != "keeper_distribution":
        return _set_piece_sentence(facts, spanish)
    # the other keeper's distribution
    return (f"{player}, el otro portero, juega el balón a {e['target_player']}" if spanish
            else f"{player}, the other keeper, plays the ball to {e['target_player']}")


def _set_piece_sentence(facts, spanish):
    """Stoppages, set pieces, fouls, cards, substitutions, runs and dribbles."""
    e, kind = facts["event"], facts["type"]
    player, team = e["player"], e["team"]
    if kind == "keeper_punch":
        return (f"Despeja de puños {player}, el otro portero" if spanish and not _mine(facts) else
                "Despejas de puños" if spanish else f"{player}, the other keeper, punches clear" if not _mine(facts)
                else "You punch the ball clear")
    pairs = {
        "dribble": (f"{player} avanza con el balón {e.get('length_m', 0):.0f} m", f"{player} drives forward {e.get('length_m', 0):.0f} m with the ball"),
        "throw_in": (f"{player} saca de banda", f"{player} takes a throw-in"),
        "corner": (f"{player} saca un córner ({e.get('delivery', '')})", f"{player} takes a corner ({e.get('delivery', '')})"),
        "free_kick": (f"{player} lanza una falta ({e.get('kind', '')})", f"{player} takes a free kick ({e.get('kind', '')})"),
        "penalty": (f"{player} lanza un penalti", f"{player} takes a penalty"),
        "foul": (f"{player} comete falta sobre {e.get('fouled', 'un rival')}", f"{player} fouls {e.get('fouled', 'an opponent')}"),
        "card": (f"{player} ve una tarjeta {'amarilla' if e.get('card') == 'yellow' else 'roja'}",
                 f"{player} is shown a {e.get('card', 'yellow')} card"),
        "offside": (f"{player} está en fuera de juego", f"{player} is flagged offside"),
        "substitution": (f"{e.get('player_on', player)} entra por {e.get('player_off', '')} ({team})",
                         f"{e.get('player_on', player)} comes on for {e.get('player_off', '')} ({team})"),
        "off_ball_run": (f"{player} se desmarca {e.get('length_m', 0):.0f} m hacia el área", f"{player} sprints {e.get('length_m', 0):.0f} m into the box"),
        "stoppage": (f"Se detiene el juego: {str(e.get('reason', '')).replace('_', ' ')}", f"Play stops: {str(e.get('reason', '')).replace('_', ' ')}"),
    }
    es, en = pairs.get(kind, (f"{player}: {kind}", f"{player}: {kind}"))
    return es if spanish else en


def template_text(facts, language):
    """An instant second-person line for any event, built only from `facts`."""
    spanish = language == "es"
    moment = moment_like(facts)
    # The key moments have their own wording: a shot or goal with a saveability
    # score, the keeper's own distribution, claim or sweep
    own_key_moment = _mine(facts) and (moment["distribution"] or facts["type"] in ("keeper_claim", "keeper_sweep"))
    scored_shot = facts["type"] in ("shot", "goal") and moment["saveability"] is not None
    if own_key_moment or scored_shot:
        return second_person_text(moment, spanish)
    off = round(facts["keeper_off_line_m"])
    lead = f"Estás a {off} m de tu línea. " if spanish else f"You're {off} m off your line. "
    sentence = _action_sentence(facts, spanish)
    return f"{lead}{sentence}. {_sight_clause(facts, spanish)}".strip()


# ---------- The numbers behind an event ----------

def numbers_rows(facts, language):
    """Rows of (label, value) for "Show the numbers", in a language."""
    lang, L = ("es" if language == "es" else "en"), LABELS["es" if language == "es" else "en"]
    event, insight, rows = facts["event"], facts["insight"], []
    shot_ref = facts.get("shot_ref")
    shot_event, shot_insight = (event, insight) if event["type"] == "shot" else (
        (shot_ref["event"], shot_ref["insight"]) if shot_ref else (None, None))

    if shot_insight and shot_insight.get("saveability") is not None:      # a shot on target
        verdict = VERDICT_ES[shot_insight["verdict"]] if lang == "es" else shot_insight["verdict"]
        situation = (SITUATION_ES if lang == "es" else SITUATION_EN)[shot_insight.get("situation", "open_play")]
        rows += [(L["saveability"], f"{shot_insight['saveability']}/100"), (L["verdict"], verdict),
                 (L["key_factor"], shot_insight["key_factor"]), (L["situation"], situation),
                 (L["distance"], f"{shot_event['distance_m']} m"), (L["speed"], f"{shot_event['speed_kmh']} km/h")]
        rows += [(f"{FACTOR_NAMES[lang][name]} ({L['factors'].split('(')[0].strip()})", f"{value:.2f}")
                 for name, value in shot_insight["factors"].items()]
    elif shot_event is not None:                                           # off target or blocked
        rows += [(L["distance"], f"{shot_event['distance_m']} m"), (L["speed"], f"{shot_event['speed_kmh']} km/h"),
                 (L["result"], shot_event["outcome"].replace("_", " "))]
    elif event["type"] == "keeper_distribution" and insight.get("quality") is not None:
        verdict = DIST_VERDICT_ES[insight["verdict"]] if lang == "es" else insight["verdict"]
        rows += [(L["quality"], f"{insight['quality']}/100 ({verdict})"),
                 (L["decision"], str(insight["decision_score"])), (L["difficulty"], str(insight["difficulty"])),
                 (L["target"], f"{event['target_role']} {event['target_player']}, {event['distance_m']} m"),
                 (L["method"], f"{event['method'].replace('_', ' ')} ({event['technique'].replace('_', ' ')})"),
                 (L["pressure"], event["pressure"]),
                 (L["options"], str(len(event["options"]))),
                 (L["unseen_options"], str(event.get("unseen_options", 0)))]
    elif facts["ball_move"] is not None:                                   # an ordinary pass and its kin
        move = facts["ball_move"]
        unknown = L["not_seen"]
        rows += [(L["distance"], f"{move['distance_m']} m" if move["distance_m"] is not None else unknown),
                 (L["direction"], DIRECTION[lang][move["direction"]] if move["direction"] else unknown),
                 (L["forward"], f"{move['forward_m']} m" if move["forward_m"] is not None else unknown),
                 (L["pressure"], PRESSURE[lang][move["pressure"]] if move["pressure"] else L["n/a"]),
                 (L["outcome"], OUTCOME[lang][move["outcome"]] if move["outcome"] else unknown),
                 (L["leads_to_shot"], unknown if move["leads_to_shot"] is None
                  else (L["yes"] if move["leads_to_shot"] else L["no"]))]
    rows += [(L["off_line"], f"{facts['keeper_off_line_m']} m"), (L["from_you"], f"{facts['distance_m']} m"),
             (L["sight"], SIGHT_NAMES[lang][facts["sight"]])]
    return rows
