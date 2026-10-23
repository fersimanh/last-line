"""Teams for the match engine: formations, tactics, players and their attributes.

Everything here is fictional. A formation is a list of slots; each slot has a
name, a coarse role (the roles the rest of the app already uses: GK, CB, FB, DM,
CM, W, ST) and an anchor position in the TEAM FRAME: x runs from the team's own
goal line (0) to the opponent's (105), y runs across the pitch (0-68).
"""
import random

PITCH_L, PITCH_W = 105.0, 68.0

# slot, coarse role, anchor x, anchor y
FORMATIONS = {
    "4-4-2": [("GK", "GK", 3, 34),
              ("LB", "FB", 30, 60), ("LCB", "CB", 26, 44), ("RCB", "CB", 26, 24), ("RB", "FB", 30, 8),
              ("LM", "W", 52, 58), ("LCM", "CM", 48, 43), ("RCM", "CM", 48, 25), ("RM", "W", 52, 10),
              ("LST", "ST", 70, 42), ("RST", "ST", 70, 26)],
    "4-3-3": [("GK", "GK", 3, 34),
              ("LB", "FB", 32, 61), ("LCB", "CB", 26, 44), ("RCB", "CB", 26, 24), ("RB", "FB", 32, 7),
              ("DM", "DM", 41, 34), ("LCM", "CM", 52, 46), ("RCM", "CM", 52, 22),
              ("LW", "W", 70, 58), ("ST", "ST", 76, 34), ("RW", "W", 70, 10)],
    "4-2-3-1": [("GK", "GK", 3, 34),
                ("LB", "FB", 31, 61), ("LCB", "CB", 26, 44), ("RCB", "CB", 26, 24), ("RB", "FB", 31, 7),
                ("LDM", "DM", 42, 43), ("RDM", "DM", 42, 25),
                ("LAM", "W", 63, 58), ("CAM", "CM", 62, 34), ("RAM", "W", 63, 10), ("ST", "ST", 76, 34)],
}

# Tactics, each 0 to 1. line_height: how high the defensive line stands. width: how
# spread out the team is. press: how many players close the ball down and how hard.
# directness: the share of long and forward balls. crossing: the urge to cross.
TEAMS = [
    {"name": "Harbor United", "formation": "4-3-3",
     "tactics": {"line_height": 0.65, "width": 0.90, "press": 0.70, "directness": 0.30, "crossing": 0.45},
     "keeper": "Mateo Rios",
     "outfield": ["Luca Ferro", "Dani Okoye", "Sam Varga", "Ivo Marsh", "Theo Brandt",
                  "Nico Alves", "Jonas Keller", "Remy Cole", "Andre Salas", "Kofi Mensah"],
     "bench": ["Arlo Finch", "Bram Tolland", "Cian Moreau", "Dex Hallam", "Emil Sato", "Finn Orrin", "Gus Pell"]},
    {"name": "Northgate FC", "formation": "4-4-2",
     "tactics": {"line_height": 0.45, "width": 0.75, "press": 0.45, "directness": 0.65, "crossing": 0.65},
     "keeper": "Elias Novak",
     "outfield": ["Pavel Drum", "Hugo Lind", "Marco Tesch", "Ruben Okafor", "Tomas Reyes",
                  "Aiden Frost", "Viktor Haas", "Leo Santos", "Ben Arkwright", "Yusuf Demir"],
     "bench": ["Ilan Voss", "Jory Kane", "Kane Ostrow", "Lior Banks", "Milan Crowe", "Nils Pryor", "Otto Wells"]},
]

# Typical attributes by coarse role: max speed (m/s), passing, tackling, shooting, control (0-1)
ROLE_ATTRIBUTES = {
    "GK": dict(pace=5.8, passing=0.70, tackling=0.30, shooting=0.20, control=0.60),
    "CB": dict(pace=6.9, passing=0.72, tackling=0.85, shooting=0.35, control=0.60),
    "FB": dict(pace=7.9, passing=0.72, tackling=0.75, shooting=0.40, control=0.70),
    "DM": dict(pace=7.1, passing=0.82, tackling=0.85, shooting=0.45, control=0.72),
    "CM": dict(pace=7.3, passing=0.85, tackling=0.65, shooting=0.60, control=0.80),
    "W": dict(pace=8.3, passing=0.74, tackling=0.50, shooting=0.70, control=0.82),
    "ST": dict(pace=8.0, passing=0.64, tackling=0.45, shooting=0.85, control=0.75),
}
# Names go to the most attacking slots first (so the familiar forwards stay forwards)
NAME_PRIORITY = ["ST", "W", "CM", "DM", "FB", "CB"]


def build_teams(rng):
    """Both teams as dicts with a list of 11 players (the keeper first)."""
    teams = []
    for cfg in TEAMS:
        slots = FORMATIONS[cfg["formation"]]
        order = sorted((s for s in slots if s[1] != "GK"), key=lambda s: NAME_PRIORITY.index(s[1]))
        names = dict(zip([s[0] for s in order], cfg["outfield"]))
        names["GK"] = cfg["keeper"]
        players = []
        for slot, role, ax, ay in slots:
            base = ROLE_ATTRIBUTES[role]
            attrs = {k: round(v + rng.gauss(0, 0.03 if k != "pace" else 0.25), 3) for k, v in base.items()}
            players.append({"name": names[slot], "slot": slot, "role": role, "anchor": (float(ax), float(ay)), **attrs})
        teams.append({"name": cfg["name"], "formation": cfg["formation"], "tactics": dict(cfg["tactics"]),
                      "players": players, "bench": list(cfg["bench"])})
    return teams
