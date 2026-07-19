"""System tray icon (pystray) — status, look pickers, quick toggles, quit."""

import logging
import sys

from .overlay import BGS, WAVES
from .themes import theme_names

log = logging.getLogger(__name__)

try:
    import pystray
    from PIL import Image, ImageDraw

    AVAILABLE = True
except ImportError:  # tray is optional — app runs headless without it
    AVAILABLE = False


def _make_image(active: bool = False) -> "Image.Image":
    """Draw a simple microphone glyph."""
    size = 64
    bg = (77, 208, 167, 255) if not active else (255, 107, 107, 255)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, size - 2, size - 2), fill=bg)
    dark = (15, 20, 25, 255)
    # mic capsule
    d.rounded_rectangle((24, 12, 40, 36), radius=8, fill=dark)
    # mic cradle
    d.arc((18, 22, 46, 44), start=0, end=180, fill=dark, width=4)
    # stem + base
    d.rectangle((30, 44, 34, 50), fill=dark)
    d.rectangle((24, 50, 40, 53), fill=dark)
    return img


class Tray:
    def __init__(self, app):
        self.app = app
        self.icon = None
        if not AVAILABLE:
            log.warning("pystray/Pillow not installed — running without tray icon")
            return

        def theme_item(name: str):
            # pystray validates callback arity — capture `name` via closure,
            # not a default arg (a 3rd parameter makes _assert_action reject it).
            def action(icon, item):
                self.app.set_theme(name)

            def is_checked(item):
                return self.app.current_theme == name

            return pystray.MenuItem(name, action, checked=is_checked, radio=True)

        def wave_item(name: str):
            def action(icon, item):
                self.app.set_wave_named(name)

            def is_checked(item):
                return self.app.current_wave == name

            return pystray.MenuItem(name, action, checked=is_checked, radio=True)

        def bg_item(name: str):
            def action(icon, item):
                self.app.set_bg_named(name)

            def is_checked(item):
                return self.app.current_bg == name

            return pystray.MenuItem(name, action, checked=is_checked, radio=True)

        def lang_item(code, label):
            def action(icon, item):
                self.app.set_language(code)

            def is_checked(item):
                return self.app.current_language == code

            return pystray.MenuItem(label, action, checked=is_checked, radio=True)

        def model_item(value, name, sub):
            def action(icon, item):
                self.app.set_model(value)

            def is_checked(item):
                return self.app.cfg["model"]["name"] == value

            return pystray.MenuItem(name, action, checked=is_checked, radio=True)

        def streaming_item(mode, label):
            def action(icon, item):
                self.app.set_streaming_mode(mode)

            def is_checked(item):
                return self.app.cfg["streaming"]["mode"] == mode

            return pystray.MenuItem(label, action, checked=is_checked, radio=True)

        def device_item(device, label):
            def action(icon, item):
                self.app.set_device(device)

            def is_checked(item):
                return self.app.transcriber.device_used == device

            return pystray.MenuItem(label, action, checked=is_checked, radio=True)

        from .howto_ui import LANGS
        from .setup_ui import _CPU_OK, MODELS

        # A GPU-only model would otherwise silently load on CPU (tens of
        # seconds per utterance) if picked here — matching setup's own
        # _plan(), don't even offer it when there's no GPU to run it on.
        offered_models = MODELS if app.gpu_available else [
            m for m in MODELS if m[0] in _CPU_OK]

        menu = pystray.Menu(
            pystray.MenuItem(
                lambda item: f"Svara — {self.app.model_label}",
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "How to use / Test…",
                lambda icon, item: self.app.show_howto(),
                default=True,  # double-clicking the tray icon opens it too
            ),
            pystray.MenuItem(
                "Model",
                pystray.Menu(*[model_item(*m) for m in offered_models]),
            ),
            pystray.MenuItem(
                "Device",
                pystray.Menu(
                    device_item("cpu", "CPU"),
                    pystray.MenuItem(
                        "GPU (NVIDIA)",
                        lambda icon, item: self.app.set_device("cuda"),
                        checked=lambda item: self.app.transcriber.device_used == "cuda",
                        radio=True,
                        # hide entirely on machines with no NVIDIA GPU at all.
                        visible=lambda item: self.app.gpu_available,
                    ),
                ),
            ),
            pystray.MenuItem(
                "Streaming",
                pystray.Menu(
                    streaming_item("live", "Live — type as you speak"),
                    streaming_item("preview", "Preview — show while speaking, type after"),
                    streaming_item("off", "Off — classic, type after you stop"),
                ),
            ),
            pystray.MenuItem(
                "Language",
                pystray.Menu(*[lang_item(c, lbl) for c, lbl in LANGS]),
                # English-only models can't switch language — hide the menu.
                visible=lambda item: self.app.is_multilingual,
            ),
            pystray.MenuItem(
                "Theme",
                pystray.Menu(*[theme_item(n) for n in theme_names()]),
            ),
            pystray.MenuItem(
                "Visualizer",
                pystray.Menu(*[wave_item(n) for n in WAVES]),
            ),
            pystray.MenuItem(
                "Background",
                pystray.Menu(*[bg_item(n) for n in BGS]),
            ),
            pystray.MenuItem(
                "Dictionary",
                pystray.Menu(
                    pystray.MenuItem(
                        "Edit words, fixes & snippets…",
                        lambda icon, item: self.app.edit_dictionary(),
                    ),
                    pystray.MenuItem(
                        "Reload (apply changes now)",
                        lambda icon, item: self.app.reload_dictionary(),
                    ),
                ),
            ),
            pystray.MenuItem(
                "Start with Windows",
                lambda icon, item: self.app.toggle_autostart(),
                checked=lambda item: self.app.autostart_enabled,
                # meaningless for source runs — there's no exe to register
                visible=lambda item: getattr(sys, "frozen", False),
            ),
            pystray.MenuItem(
                "Paused",
                lambda icon, item: self.app.toggle_paused(),
                checked=lambda item: self.app.paused,
            ),
            pystray.MenuItem(
                "Strip filler words",
                lambda icon, item: self.app.toggle_fillers(),
                checked=lambda item: self.app.cleanup.strip_fillers_enabled,
            ),
            pystray.MenuItem(
                "LLM cleanup (Ollama)",
                lambda icon, item: self.app.toggle_llm(),
                checked=lambda item: self.app.cleanup.llm.cfg["enabled"],
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda icon, item: self.app.shutdown()),
        )
        hk = app.cfg["recording"].get("hotkey", "right alt")
        self.icon = pystray.Icon(
            "Svara", _make_image(), f"Svara — double-tap {hk} to dictate", menu)

    def set_recording(self, active: bool):
        if self.icon:
            self.icon.icon = _make_image(active)

    def notify(self, message: str, title: str = "Svara"):
        """Windows toast balloon from the tray icon (best-effort)."""
        if self.icon:
            try:
                self.icon.notify(message, title)
            except Exception:  # noqa: BLE001 — feedback must never crash the app
                log.debug("tray notify failed", exc_info=True)

    def run(self):
        """Blocking — call from the main thread."""
        if self.icon:
            self.icon.run()

    def stop(self):
        if self.icon:
            self.icon.stop()
