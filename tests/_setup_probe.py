"""Builds the real first-run setup window and reports what it looks like.

Run as a SUBPROCESS by tests/test_setup_screens.py, for two reasons. The
window constructs its own `ctk.CTk()` root, and a second Tk root inside a
process that already has one is a well-known way to get flaky, order-dependent
failures. And `_run_setup_ctk` ends in `mainloop()`, which never returns — so
the loop is stubbed out here rather than in the suite, where the patch could
leak into another test.

Nothing is mocked except the event loop and the model download. Everything the
user would see is really built.

Prints one JSON object on stdout. Not a test itself; it has no assertions.
"""

import json
import os
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def walk(widget, out):
    out.append(widget)
    for child in widget.winfo_children():
        walk(child, out)
    return out


def in_scrollable(widget) -> bool:
    """True if any ancestor is a scrollable frame, i.e. the widget is meant to
    be reachable by scrolling rather than visible all at once."""
    node = widget
    while node is not None:
        if "scrollable" in type(node).__name__.lower():
            return True
        node = getattr(node, "master", None)
    return False


def describe(root) -> dict:
    import tkinter as tk

    root.update_idletasks()
    root.update()

    widgets = walk(root, [])
    texts, truncated, offscreen = [], [], []
    height = root.winfo_height()
    bottom = root.winfo_rooty() + height

    for w in widgets:
        try:
            text = str(w.cget("text"))
        except Exception:  # noqa: BLE001 — most widgets have no text option
            continue
        if not text.strip():
            continue
        texts.append(text)
        if not w.winfo_ismapped():
            continue
        # Requested vs allocated: pack cuts the text rather than overflowing,
        # so screen coordinates alone never reveal a severed label.
        short = w.winfo_reqwidth() - w.winfo_width()
        if short > 1:
            truncated.append({"text": text[:44], "cut": short})
        # A control below the window's own bottom edge cannot be clicked -
        # UNLESS it lives in the scrollable model list, where being below the
        # fold is the entire point and the user scrolls to it. Conflating the
        # two would either hide a real bug or flag a working scroll area.
        if w.winfo_rooty() + w.winfo_height() > bottom + 1:
            entry = {"text": text[:44],
                     "over": w.winfo_rooty() + w.winfo_height() - bottom,
                     "scrolls": in_scrollable(w)}
            offscreen.append(entry)

    return {
        "ok": True,
        "width": root.winfo_width(),
        "height": height,
        "screen_h": root.winfo_screenheight(),
        "widget_count": len(widgets),
        "texts": texts,
        "truncated": truncated,
        "offscreen": offscreen,
    }


def main() -> None:
    scaling = float(os.environ.get("PROBE_SCALING", "1.333"))
    report: dict = {"ok": False}
    try:
        import customtkinter as ctk

        from mywhisper import config as config_mod, setup_ui

        captured = {}

        # mainloop never returns; capture the fully-built window instead of
        # entering it, then describe what the user would have been looking at.
        def fake_mainloop(self):
            captured["root"] = self
            self.tk.call("tk", "scaling", scaling)
            report.update(describe(self))

        with mock.patch.object(ctk.CTk, "mainloop", fake_mainloop), \
             mock.patch.object(setup_ui, "_download_model"), \
             mock.patch.object(setup_ui, "_load_model", return_value=None):
            cfg = config_mod.load(None)
            setup_ui._run_setup_ctk(cfg, None)

        if "root" not in captured:
            report = {"ok": False, "error": "mainloop was never reached"}
    except Exception as exc:  # noqa: BLE001 — the failure IS the result
        import traceback
        report = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                  "trace": traceback.format_exc()[-1200:]}

    print(json.dumps(report))


if __name__ == "__main__":
    main()
