"""Picking a strategy for the app that's about to receive the text."""

import logging

from ..pipeline.base import UtteranceContext
from .strategies import (ClipboardPasteStrategy, SendInputStrategy,
                         ShiftInsertStrategy, TerminalStrategy)

log = logging.getLogger(__name__)

# Apps where Ctrl+V is not paste, or where per-character SendInput crawls.
DEFAULT_TERMINALS = [
    "windowsterminal.exe", "wt.exe", "openconsole.exe", "conhost.exe",
    "cmd.exe", "powershell.exe", "pwsh.exe", "bash.exe", "sh.exe",
    "mintty.exe", "alacritty.exe", "wezterm-gui.exe", "wezterm.exe",
    "kitty.exe", "hyper.exe", "tabby.exe", "putty.exe", "cygwin.exe",
    "ubuntu.exe", "wsl.exe", "wslhost.exe", "fluent-terminal.exe",
    "warp.exe", "ghostty.exe",
]

# Editors whose *integrated terminal* is the common dictation target. They are
# not terminals as a whole, so they get Shift+Insert (which their editor panes
# also accept) rather than full terminal line-splitting.
DEFAULT_SHIFT_INSERT = [
    "cursor.exe", "windsurf.exe", "code.exe", "code - insiders.exe",
]

_STRATEGIES = {
    "type": "type", "sendinput": "type",
    "paste": "paste", "clipboard": "paste",
    "shift_insert": "shift_insert", "shiftinsert": "shift_insert",
    "terminal": "terminal",
}


def classify(app: str, inj_cfg: dict | None) -> str:
    """exe name → strategy key. Explicit `injection.targets` wins over the
    built-in lists, so a user can always override our guess."""
    cfg = inj_cfg or {}
    app = (app or "").lower()
    if not app:
        return _STRATEGIES.get(str(cfg.get("method", "type")).lower(), "type")

    override = (cfg.get("targets") or {}).get(app)
    if override:
        key = _STRATEGIES.get(str(override).lower())
        if key:
            return key
        log.warning("injection.targets[%s] = %r is not a known strategy "
                    "(type|paste|shift_insert|terminal) — ignoring", app, override)

    terminals = {a.lower() for a in (cfg.get("terminal_apps") or DEFAULT_TERMINALS)}
    if app in terminals:
        return "terminal"
    shift = {a.lower() for a in (cfg.get("shift_insert_apps") or DEFAULT_SHIFT_INSERT)}
    if app in shift:
        return "shift_insert"
    return _STRATEGIES.get(str(cfg.get("method", "type")).lower(), "type")


def is_terminal_app(app: str, inj_cfg: dict | None) -> bool:
    """Used by the pipeline to suppress invisible characters and list markers.
    Editors on the Shift+Insert list are *not* terminals: their editor panes
    are ordinary text and want ordinary typography."""
    return classify(app, inj_cfg) == "terminal"


def build(key: str, inj_cfg: dict | None, warn=None):
    cfg = inj_cfg or {}
    restore = bool(cfg.get("restore_clipboard", True))
    if key == "terminal":
        return TerminalStrategy(
            newline=cfg.get("terminal_newline", "space"),
            restore=restore,
            paste=bool(cfg.get("terminal_paste", True)),
            warn=warn)
    if key == "shift_insert":
        return ShiftInsertStrategy(restore=restore)
    if key == "paste":
        return ClipboardPasteStrategy(restore=restore)
    return SendInputStrategy()


def resolve(ctx: UtteranceContext, inj_cfg: dict | None, warn=None):
    return build(classify(ctx.app, inj_cfg), inj_cfg, warn=warn)
