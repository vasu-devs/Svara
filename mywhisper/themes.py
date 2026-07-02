"""Overlay themes — modern-minimal by default, pop-culture skins on demand.

Pick with `ui.theme` in config.yaml or live from the tray menu (persists).
Any key below can be overridden per-user via `ui.theme_overrides`, e.g.:

    ui:
      theme: minimal-dark
      theme_overrides:
        accent: "#ff00aa"
        label_listening: "yo, talk"

Theme keys:
  bg, border, text, muted        — pill colors
  dot                            — the recording dot
  accent                         — level meter color
  done                           — success flash color
  font_family, font_size, font_style ("", "bold", "italic")
  bar_style                      — "bars" | "wave" | "dots"
  alpha                          — window opacity 0..1
  width, height                  — pill size (pre-scale)
  glow                           — subtle outer ring in the accent color
  label_listening, label_locked, label_processing, done_prefix
"""

DEFAULT = "minimal-dark"

_BASE = {
    "font_family": "Segoe UI",
    "font_size": 10,
    "font_style": "",
    "bar_style": "bars",
    "alpha": 0.96,
    "width": 320,
    "height": 46,
    "glow": False,
    "label_listening": "Listening",
    "label_locked": "Locked — tap to finish",
    "label_processing": "Working…",
    "done_prefix": "✓",
    # Siri-style flowing strings (ui.style: siri) — iridescent ribbon colors
    "strings": ["#ff5fa2", "#8b5cf6", "#00d4ff"],
    "animate_strings": False,  # True = colors hue-cycle live (RGB-keyboard vibes)
}

THEMES: dict[str, dict] = {
    # ── modern minimal, sick AF ────────────────────────────────────────────
    "minimal-dark": {
        **_BASE,
        "bg": "#101216", "border": "#23272f", "text": "#e8eaed",
        "muted": "#7d8590", "dot": "#ff5f56", "accent": "#e8eaed",
        "done": "#58d5a2",
    },
    "minimal-light": {
        **_BASE,
        "bg": "#f7f8fa", "border": "#e3e6ea", "text": "#1b1f24",
        "muted": "#6b7280", "dot": "#ff3b30", "accent": "#1b1f24",
        "done": "#0a8f5b", "alpha": 0.98,
        "strings": ["#ff2d78", "#6a5cff", "#00b8e6"],
    },
    # ── pop culture ────────────────────────────────────────────────────────
    "matrix": {
        **_BASE,
        "bg": "#000a03", "border": "#003b12", "text": "#00ff66",
        "muted": "#00a344", "dot": "#00ff66", "accent": "#00ff66",
        "done": "#aaffcc", "font_family": "Consolas", "glow": True,
        "strings": ["#00ff66", "#00cc44", "#8dffbb"],
        "label_listening": "> listening_",
        "label_locked": "> locked_",
        "label_processing": "> decoding_",
        "done_prefix": ">",
    },
    "cyberpunk": {
        **_BASE,
        "bg": "#0d0b14", "border": "#fcee0a", "text": "#fcee0a",
        "muted": "#7a7460", "dot": "#ff003c", "accent": "#00f0ff",
        "done": "#00f0ff", "font_family": "Consolas", "font_style": "bold",
        "glow": True,
        "strings": ["#fcee0a", "#00f0ff", "#ff003c"],
        "label_listening": "◉ REC",
        "label_locked": "▣ LOCKED",
        "label_processing": "// PROCESSING",
        "done_prefix": "✓",
    },
    # ── anime ──────────────────────────────────────────────────────────────
    "sakura": {
        **_BASE,
        "bg": "#fff5f7", "border": "#ffd7e0", "text": "#5a3d44",
        "muted": "#b48a95", "dot": "#ff8fab", "accent": "#ff8fab",
        "done": "#e05780", "font_family": "Yu Gothic UI",
        "bar_style": "dots", "alpha": 0.97,
        "strings": ["#ff8fab", "#ffc2d1", "#e05780"],
        "label_listening": "聞いています…",
        "label_locked": "ロック中",
        "label_processing": "変換中…",
        "done_prefix": "完了 ·",
    },
    "evangelion": {
        **_BASE,
        "bg": "#0a0a0a", "border": "#ff6600", "text": "#ff6600",
        "muted": "#7c4a1d", "dot": "#ff2200", "accent": "#9dff00",
        "done": "#9dff00", "font_family": "Consolas", "glow": True,
        "strings": ["#ff6600", "#9dff00", "#ff2200"],
        "label_listening": "SOUND ONLY",
        "label_locked": "A.T. FIELD LOCKED",
        "label_processing": "MAGI ANALYZING…",
        "done_prefix": "◎",
    },
    "saiyan": {
        **_BASE,
        "bg": "#0b0e1a", "border": "#ffb300", "text": "#ffd54f",
        "muted": "#8d6e63", "dot": "#ff6d00", "accent": "#40c4ff",
        "done": "#ffd54f", "font_style": "bold",
        "strings": ["#ffd54f", "#40c4ff", "#ff6d00"],
        "label_listening": "SCOUTER ACTIVE…",
        "label_locked": "FORM LOCKED",
        "label_processing": "POWERING UP…",
        "done_prefix": "⚡",
    },
    # ── fun ────────────────────────────────────────────────────────────────
    "rgb-gamer": {
        **_BASE,
        "bg": "#0a0a12", "border": "#26263a", "text": "#e8eaed",
        "muted": "#8a8aa8", "dot": "#ff0055", "accent": "#00ffee",
        "done": "#00ff88", "glow": True,
        "animate_strings": True,  # 🌈 strings hue-cycle forever
        "label_listening": "REC ●",
        "label_locked": "LOCKED",
        "label_processing": "GG…",
    },
    "dracula": {
        **_BASE,
        "bg": "#1e1f29", "border": "#44475a", "text": "#f8f8f2",
        "muted": "#6272a4", "dot": "#ff5555", "accent": "#bd93f9",
        "done": "#50fa7b",
        "strings": ["#ff79c6", "#bd93f9", "#8be9fd"],
        "label_listening": "listening…",
        "label_locked": "locked 🦇",
    },
    "hologram": {
        **_BASE,
        "bg": "#04141c", "border": "#0e4a5c", "text": "#c8fbff",
        "muted": "#3d7c8c", "dot": "#7cf6ff", "accent": "#7cf6ff",
        "done": "#aef9ff", "glow": True,
        "strings": ["#7cf6ff", "#e6ffff", "#3ec6e0"],
        "label_listening": "TRANSMITTING…",
        "label_locked": "CHANNEL OPEN",
    },
    "midas": {
        **_BASE,
        "bg": "#120e06", "border": "#8a6d1d", "text": "#ffe9a8",
        "muted": "#8a7a4d", "dot": "#ffd700", "accent": "#ffd700",
        "done": "#fff2b0",
        "strings": ["#ffd700", "#ffb84d", "#fff2b0"],
        "label_listening": "golden…",
        "label_locked": "locked",
    },
    # ── retro ──────────────────────────────────────────────────────────────
    "vaporwave": {
        **_BASE,
        "bg": "#1a103c", "border": "#ff71ce", "text": "#ff71ce",
        "muted": "#8878c3", "dot": "#ff71ce", "accent": "#01cdfe",
        "done": "#05ffa1", "font_style": "italic", "bar_style": "wave",
        "strings": ["#ff71ce", "#01cdfe", "#05ffa1"],
        "label_listening": "ｌｉｓｔｅｎｉｎｇ",
        "label_locked": "ｌｏｃｋｅｄ",
        "label_processing": "ｄｒｅａｍｉｎｇ…",
        "done_prefix": "✓",
    },
}


def theme_names() -> list[str]:
    return list(THEMES)


def get_theme(name: str, overrides: dict | None = None) -> dict:
    """Resolve a theme by name and apply user overrides on top."""
    theme = dict(THEMES.get(name, THEMES[DEFAULT]))
    for k, v in (overrides or {}).items():
        if k in _BASE or k in theme:
            theme[k] = v
    return theme
