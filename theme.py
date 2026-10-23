"""The "Onside look": every design token for Last Line, defined once.

Both the CSS (build_css) and the Plotly charts (plotly_layout, SAVEABILITY_SCALE)
read from here, so no color or font is written down twice. Pure Python, no
Streamlit, so it is easy to test. .streamlit/config.toml repeats a handful of
these colors because Streamlit reads that file before any Python runs;
test_theme.py checks the two never drift apart.

Dark only. Last Line has its own name and mark: no Onside name or logo.
"""

# ---------- Colors ----------
BG = "#0b0f0a"                  # page background
CARD = "#131a12"                # cards, sidebar, pitch fill
CARD_BORDER = "#25301a"         # 1 px card borders
LIME = "#c2f160"                # accent
MUTED_ACCENT = "#425324"        # disabled controls
BODY = "#a5b7a2"                # body text
HEADING = "#eaf0e9"             # headings and big numbers
MONO_LABEL = "#51694d"          # SMALL labels only, never text people must read
TRACK = "#182017"               # progress and meter tracks
ICON_TILE = "#1e2613"           # pill and icon-tile fill
ICON_TILE_BORDER = "#3f4f22"    # pill and icon-tile border; also the pitch lines
PITCH_LINE = ICON_TILE_BORDER
BALL = HEADING
# The brief also lists a faint caption color. It is too dark to read, so it is
# deliberately not defined here: nothing in Last Line may use it (test_theme.py checks).

# Saveability scale: hard to save -> easy to save
SAVEABILITY_SCALE = [[0, ICON_TILE_BORDER], [1, LIME]]
MARKER_OUTLINE = BODY           # outline on shot markers, so they show on the dark pitch

# ---------- Fonts (with fallbacks, so the app works if Google Fonts fails to load) ----------
FONT_DISPLAY = "'Fraunces', Georgia, serif"            # wordmark, headings, big numbers
FONT_BODY = "'Outfit', system-ui, sans-serif"          # body text and controls
FONT_MONO = "'JetBrains Mono', ui-monospace, monospace"  # small uppercase labels, timestamps
FONT_PLOTLY = "Outfit, system-ui, sans-serif"          # Plotly takes a plain family list
FONT_PLOTLY_MONO = "JetBrains Mono, ui-monospace, monospace"
FONTS_URL = ("https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600..900"
             "&family=Outfit:wght@400;500;600;700"
             "&family=JetBrains+Mono:wght@400;500&display=swap")

# ---------- Shapes ----------
RADIUS_CARD = "16px"
RADIUS_BUTTON = "14px"
CARD_PADDING = "20px"
MAX_WIDTH = "1200px"
SPACING = "24px"


# ---------- Helpers ----------

def rgba(hex_color, alpha):
    """'#c2f160', 0.18 -> 'rgba(194,241,96,0.18)' (Plotly wants rgba for transparency)."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def _luminance(hex_color):
    h = hex_color.lstrip("#")
    channels = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(foreground, background):
    """WCAG contrast ratio between two hex colors (1 to 21)."""
    a, b = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (a + 0.05) / (b + 0.05)


# Pairs that carry reading text, and the ratio they must reach (WCAG AA body text)
READABLE_PAIRS = [
    ("body text on the page", BODY, BG),
    ("body text on a card", BODY, CARD),
    ("headings on the page", HEADING, BG),
    ("headings on a card", HEADING, CARD),
    ("lime on the page", LIME, BG),
    ("lime on a card", LIME, CARD),
    ("lime on a pill", LIME, ICON_TILE),
    ("body text on a pill", BODY, ICON_TILE),
    ("dark text on a lime button", BG, LIME),
]
MIN_TEXT_CONTRAST = 4.5


# ---------- Plotly ----------

def plotly_layout(height):
    """The base layout every chart starts from: transparent paper, Outfit text."""
    return dict(
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT_PLOTLY, color=BODY, size=13),
        margin=dict(l=0, r=0, t=10, b=0),
        legend=dict(orientation="h", y=-0.04, font=dict(family=FONT_PLOTLY, color=BODY, size=12),
                    bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(bgcolor=CARD, bordercolor=ICON_TILE_BORDER,
                        font=dict(family=FONT_PLOTLY, color=HEADING, size=13)),
    )


# ---------- CSS ----------

def _variables():
    pairs = {
        "bg": BG, "card": CARD, "border": CARD_BORDER, "lime": LIME, "muted": MUTED_ACCENT,
        "body": BODY, "heading": HEADING, "mono": MONO_LABEL, "track": TRACK,
        "tile": ICON_TILE, "tile-border": ICON_TILE_BORDER,
        "font-display": FONT_DISPLAY, "font-body": FONT_BODY, "font-mono": FONT_MONO,
        "radius-card": RADIUS_CARD, "radius-button": RADIUS_BUTTON, "pad": CARD_PADDING,
        "gap": SPACING,
    }
    return ":root{" + ";".join(f"--ll-{k}:{v}" for k, v in pairs.items()) + "}"


# Everything below reads colors and fonts through var(--ll-...), defined from the
# tokens above. No blank lines: Streamlit's markdown ends a raw HTML block at one.
_CSS = """
html,body,.stApp,[data-testid="stAppViewContainer"]{background:var(--ll-bg);color:var(--ll-body);font-family:var(--ll-font-body)}
[data-testid="stHeader"]{background:transparent}
[data-testid="stToolbar"],[data-testid="stDecoration"],[data-testid="stStatusWidget"],#MainMenu,footer{display:none!important}
[data-testid="stMainBlockContainer"],.block-container{max-width:MAXWIDTH;padding:2rem 1.5rem 4rem}
[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"]{gap:1rem}
h1,h2,h3,h4,h5{font-family:var(--ll-font-display);color:var(--ll-heading);font-weight:800;letter-spacing:-.01em}
p,li,label,[data-testid="stMarkdownContainer"]{color:var(--ll-body)}
a{color:var(--ll-lime)}
*:focus-visible{outline:2px solid var(--ll-lime)!important;outline-offset:2px}
div[data-baseweb="select"]>div:focus-within,div[data-baseweb="input"]:focus-within{border-color:var(--ll-lime)!important;box-shadow:0 0 0 1px var(--ll-lime)!important}
.ll-eyebrow,.ll-label{font-family:var(--ll-font-mono);font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--ll-mono)}
.ll-header{padding:4px 0 8px}
.ll-wordmark{font-family:var(--ll-font-display);font-weight:900;font-size:44px;line-height:1.05;color:var(--ll-lime);margin:4px 0 2px}
.ll-tagline{font-size:16px;color:var(--ll-body);margin:0}
.ll-topbar{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:var(--ll-gap);background:var(--ll-card);border:1px solid var(--ll-border);border-radius:var(--ll-radius-card);padding:var(--ll-pad)}
.ll-team{font-family:var(--ll-font-display);font-weight:800;font-size:20px;color:var(--ll-heading)}
.ll-team--away{text-align:right}
.ll-scorebox{display:flex;flex-direction:column;align-items:center}
.ll-score{font-family:var(--ll-font-display);font-weight:900;font-size:52px;line-height:1;color:var(--ll-heading)}
.ll-clock-big{font-family:var(--ll-font-display);font-weight:800;font-size:22px;color:var(--ll-lime)}
.ll-timeline{position:relative;padding:14px 0 4px;margin-top:6px}
/* While the match plays the live area reruns every tick; Streamlit would grey it out each time. Keep it at full strength. */
[data-stale="true"]{opacity:1 !important;transition:none !important}
.ll-segs{display:grid;grid-template-columns:repeat(18,1fr);gap:3px}
.ll-seg{height:10px;background:var(--ll-track);border-radius:3px;overflow:hidden}
.ll-seg>span{display:block;height:100%;background:var(--ll-lime)}
.ll-ht{position:absolute;left:50%;top:8px;bottom:22px;width:2px;background:var(--ll-tile-border);transform:translateX(-50%)}
.ll-tick{position:absolute;top:27px;width:2px;height:7px;background:var(--ll-body);transform:translateX(-50%)}
.ll-goal{position:absolute;top:1px;width:10px;height:10px;background:var(--ll-heading);border:1px solid var(--ll-bg);transform:translateX(-50%) rotate(45deg)}
.ll-tl-label{display:grid;grid-template-columns:1fr auto 1fr;margin-top:16px;font-family:var(--ll-font-mono);font-size:12px;color:var(--ll-body)}
.ll-tl-label span:last-child{text-align:right}
[class*="st-key-card_"],[class*="st-key-inspector"]{background:var(--ll-card);border:1px solid var(--ll-border);border-radius:var(--ll-radius-card);padding:var(--ll-pad)}
.ll-inspector-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.ll-seen-line{font-size:14px;color:var(--ll-body);margin:8px 0 4px}
.ll-card-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.ll-clock{font-family:var(--ll-font-mono);font-size:12px;color:var(--ll-body)}
.ll-headline{font-family:var(--ll-font-display);font-weight:800;font-size:24px;line-height:1.15;color:var(--ll-heading);margin:8px 0 6px}
.ll-body{font-size:15px;line-height:1.55;color:var(--ll-body)}
.ll-pill{display:inline-flex;align-items:center;gap:6px;padding:2px 10px;border-radius:999px;border:1px solid var(--ll-tile-border);background:var(--ll-tile);font-family:var(--ll-font-mono);font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--ll-body);white-space:nowrap}
.ll-pill--lime{color:var(--ll-lime)}
.ll-pill svg{width:12px;height:12px;flex:none}
.ll-meter{height:8px;background:var(--ll-track);border-radius:999px;overflow:hidden}
.ll-meter>span{display:block;height:100%;background:var(--ll-lime)}
.ll-stat{display:flex;flex-direction:column;gap:6px}
.ll-stat-value{font-family:var(--ll-font-display);font-weight:800;font-size:30px;color:var(--ll-heading);line-height:1}
.ll-panel{background:var(--ll-card);border:1px solid var(--ll-border);border-radius:var(--ll-radius-card);padding:var(--ll-pad)}
.ll-panel-row{display:flex;gap:var(--ll-gap);flex-wrap:wrap;align-items:center}
.ll-missed{display:flex;justify-content:space-between;gap:12px;padding:6px 0;border-bottom:1px solid var(--ll-border);font-size:14px}
[data-testid="stSidebar"]{background:var(--ll-card);border-right:1px solid var(--ll-border)}
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p{font-family:var(--ll-font-mono);font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--ll-mono)}
[data-testid="stSidebar"] .ll-eyebrow{display:block;margin:4px 0 8px}
[data-testid="stRadio"] [role="radiogroup"]{gap:6px;flex-wrap:wrap}
[data-testid="stRadio"] label[data-baseweb="radio"]{margin:0;padding:6px 14px;border:1px solid var(--ll-border);border-radius:999px;background:var(--ll-bg);cursor:pointer}
[data-testid="stRadio"] label[data-baseweb="radio"]>div:first-child{display:none}
[data-testid="stRadio"] label[data-baseweb="radio"] p{color:var(--ll-body);font-weight:500}
[data-testid="stRadio"] label[data-baseweb="radio"]:hover{border-color:var(--ll-lime)}
[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked){background:var(--ll-lime);border-color:var(--ll-lime)}
[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) p{color:var(--ll-bg);font-weight:700}
[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:focus-visible){outline:2px solid var(--ll-lime);outline-offset:2px}
div[data-baseweb="select"]>div{background:var(--ll-bg);border:1px solid var(--ll-border);border-radius:12px}
[data-testid="stSlider"] div[role="slider"]{background:var(--ll-lime);box-shadow:none}
[data-testid="stSlider"] [data-testid="stThumbValue"],[data-testid="stSliderTickBarMin"],[data-testid="stSliderTickBarMax"]{color:var(--ll-body)}
[data-testid="stBaseButton-primary"]{background:var(--ll-lime);color:var(--ll-bg);font-weight:700;border:1px solid var(--ll-lime);border-radius:var(--ll-radius-button)}
[data-testid="stBaseButton-primary"]:hover{background:var(--ll-heading);border-color:var(--ll-heading);color:var(--ll-bg)}
[data-testid="stBaseButton-secondary"]{background:transparent;color:var(--ll-body);border:1px solid var(--ll-border);border-radius:var(--ll-radius-button)}
[data-testid="stBaseButton-secondary"]:hover{border-color:var(--ll-lime);color:var(--ll-lime);background:transparent}
[data-testid="stBaseButton-primary"]:disabled,[data-testid="stBaseButton-secondary"]:disabled{background:var(--ll-muted);border-color:var(--ll-muted);color:var(--ll-bg);cursor:not-allowed}
button[data-baseweb="tab"]{color:var(--ll-body);font-family:var(--ll-font-body);font-weight:600}
button[data-baseweb="tab"][aria-selected="true"]{color:var(--ll-lime)}
[data-baseweb="tab-highlight"]{background:var(--ll-lime)!important}
[data-baseweb="tab-border"]{background:var(--ll-border)!important}
[data-testid="stMetric"]{background:var(--ll-card);border:1px solid var(--ll-border);border-radius:var(--ll-radius-card);padding:16px}
[data-testid="stMetricValue"]{font-family:var(--ll-font-display);font-weight:800;color:var(--ll-heading)}
[data-testid="stMetricLabel"] p{font-family:var(--ll-font-mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--ll-body)}
[data-testid="stExpander"]{background:var(--ll-card);border:1px solid var(--ll-border);border-radius:12px}
[data-testid="stExpander"] summary p{color:var(--ll-body)}
[data-testid="stPlotlyChart"]{background:transparent}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
@media (max-width:760px){.ll-topbar{grid-template-columns:1fr}.ll-team--away{text-align:left}.ll-score{font-size:40px}}
"""


def build_css():
    """The whole stylesheet as one string, with a comment marker so tests can
    find it. Fonts load through a Google Fonts @import; every font stack has a
    fallback, so the app still works if the import fails."""
    body = _CSS.replace("MAXWIDTH", MAX_WIDTH)
    css = f"/* ll-css */@import url('{FONTS_URL}');{_variables()}{body}"
    return "\n".join(line for line in css.splitlines() if line.strip())
