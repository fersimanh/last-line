"""Tests for the design tokens in theme.py. Run:  python3 test_theme.py"""
import pathlib
import re
import tomllib

import theme

ROOT = pathlib.Path(__file__).parent
SOURCE = (ROOT / "theme.py").read_text().lower()

# The tokens from the design brief, exactly as written there
TOKENS = {
    "background": "#0b0f0a", "card": "#131a12", "card border": "#25301a", "accent lime": "#c2f160",
    "muted accent": "#425324", "body text": "#a5b7a2", "headings": "#eaf0e9",
    "mono label": "#51694d", "progress track": "#182017", "icon tile": "#1e2613",
    "icon tile border": "#3f4f22",
}
FAINT_CAPTION = "#32492d"  # too dark to read: nothing may use it


def test_every_token_is_in_theme_py():
    for name, hex_color in TOKENS.items():
        assert hex_color in SOURCE, f"{name} {hex_color} is missing from theme.py"
    assert theme.BG == "#0b0f0a" and theme.CARD == "#131a12" and theme.CARD_BORDER == "#25301a"
    assert theme.LIME == "#c2f160" and theme.MUTED_ACCENT == "#425324"
    assert theme.BODY == "#a5b7a2" and theme.HEADING == "#eaf0e9" and theme.MONO_LABEL == "#51694d"
    assert theme.TRACK == "#182017" and theme.ICON_TILE == "#1e2613"
    assert theme.ICON_TILE_BORDER == "#3f4f22"
    print("ok  every design token is defined in theme.py")


def test_fonts_have_fallbacks():
    assert "Fraunces" in theme.FONT_DISPLAY and "Georgia" in theme.FONT_DISPLAY
    assert "Outfit" in theme.FONT_BODY and "system-ui" in theme.FONT_BODY
    assert "JetBrains Mono" in theme.FONT_MONO and "ui-monospace" in theme.FONT_MONO
    assert "fonts.googleapis.com" in theme.FONTS_URL
    for family in ("Fraunces", "Outfit", "JetBrains+Mono"):
        assert family in theme.FONTS_URL
    print("ok  Fraunces, Outfit and JetBrains Mono load from Google Fonts, each with a fallback")


def test_the_css_is_built_from_the_tokens():
    css = theme.build_css()
    assert all(line.strip() for line in css.splitlines()), "a blank line would end the HTML block"
    assert "@import url(" in css and "prefers-reduced-motion" in css
    for value in (theme.BG, theme.CARD, theme.LIME, theme.BODY, theme.HEADING, theme.ICON_TILE,
                  theme.TRACK, theme.MUTED_ACCENT, theme.RADIUS_CARD, theme.RADIUS_BUTTON):
        assert value in css, value
    # colors are written once, in :root, and used through var(--ll-...) everywhere else
    outside_root = css.split("}", 1)[1]
    assert not re.search(r"#[0-9a-fA-F]{6}", outside_root), "a color is hard-coded outside :root"
    print("ok  the CSS is built from the tokens, with no colors hard-coded outside :root")


def test_the_faint_caption_color_is_never_used():
    for path in ROOT.glob("*.py"):
        if path.name != "test_theme.py":
            assert FAINT_CAPTION not in path.read_text().lower(), path.name
    assert FAINT_CAPTION not in theme.build_css().lower()
    assert FAINT_CAPTION not in (ROOT / ".streamlit" / "config.toml").read_text().lower()
    print("ok  the faint caption color #32492d is not used anywhere")


def test_reading_text_has_enough_contrast():
    for name, foreground, background in theme.READABLE_PAIRS:
        ratio = theme.contrast_ratio(foreground, background)
        assert ratio >= theme.MIN_TEXT_CONTRAST, f"{name}: {ratio:.2f}:1"
    print("ok  all reading text is at least 4.5:1 (body 8.4:1 on cards, headings 15:1)")


def test_no_hard_coded_colors_in_the_app():
    app = (ROOT / "app.py").read_text()
    colors = set(re.findall(r"#[0-9a-fA-F]{6}\b", app))
    assert not colors, f"app.py hard-codes colors: {colors} (use theme.py)"
    print("ok  app.py hard-codes no colors")


def test_streamlit_config_matches_the_theme():
    config = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text())
    t = config["theme"]
    assert t["base"] == "dark"
    assert t["primaryColor"] == theme.LIME
    assert t["backgroundColor"] == theme.BG
    assert t["secondaryBackgroundColor"] == theme.CARD
    assert t["textColor"] == theme.BODY
    assert config["client"]["toolbarMode"] == "minimal"
    # Streamlit's built-in red, blue and friends are repainted from the palette
    for hue in ("redColor", "blueColor", "greenColor", "orangeColor", "yellowColor", "violetColor"):
        assert t[hue] == theme.LIME, hue
    print("ok  .streamlit/config.toml matches theme.py and repaints Streamlit's default hues")


def test_plotly_layout_uses_the_tokens():
    layout = theme.plotly_layout(400)
    assert layout["paper_bgcolor"] == "rgba(0,0,0,0)" and layout["plot_bgcolor"] == "rgba(0,0,0,0)"
    assert layout["font"]["family"].startswith("Outfit")
    assert layout["font"]["color"] == theme.BODY
    assert theme.SAVEABILITY_SCALE == [[0, "#3f4f22"], [1, "#c2f160"]]
    assert theme.rgba(theme.LIME, 0.18) == "rgba(194,241,96,0.18)"
    assert theme.rgba(theme.BG, 0.7) == "rgba(11,15,10,0.7)"
    print("ok  Plotly charts: transparent paper, Outfit text, the hard-to-easy lime scale")


if __name__ == "__main__":
    test_every_token_is_in_theme_py()
    test_fonts_have_fallbacks()
    test_the_css_is_built_from_the_tokens()
    test_the_faint_caption_color_is_never_used()
    test_reading_text_has_enough_contrast()
    test_no_hard_coded_colors_in_the_app()
    test_streamlit_config_matches_the_theme()
    test_plotly_layout_uses_the_tokens()
    print("all theme tests passed")
