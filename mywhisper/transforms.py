"""Transforms — act on SELECTED text anywhere, powered by the local LLM.

Polish (hotkey): select text in any app → press the shortcut → the selection
is replaced in place with a cleaned-up version. The target app's own Ctrl+Z
undoes it, and the original is also saved to Svara's history.

Command mode (optional second hotkey): hold it, SAY an instruction ("make
this friendlier", "turn into bullet points"), release — the instruction is
applied to the current selection.

Both need Ollama (config: cleanup.llm) — without it they toast a pointer
instead of failing silently. Selection is read via Ctrl+C with full clipboard
save/restore; nothing sticks to the clipboard afterwards.
"""

import logging
import time

from .injector import (_clipboard_get, _clipboard_set, copy_selection,
                       paste_text)

log = logging.getLogger(__name__)

POLISH_PROMPT = (
    "You are a writing polish tool. Rewrite the user's text to be clearer and "
    "more concise. Fix grammar and punctuation. Preserve the meaning, tone, "
    "formatting, links and language. Never add new content or commentary. "
    "Output ONLY the rewritten text."
)

COMMAND_PROMPT = (
    "You are a text-editing tool. Apply the INSTRUCTION to the TEXT. "
    "Output ONLY the resulting text — no commentary, no quotes, no preamble."
)

_SENTINEL = "⁣svara-transform⁣"  # never a real user clipboard value


def grab_selection() -> tuple[str | None, str | None]:
    """(selected_text, previous_clipboard). Selection is read by planting a
    sentinel on the clipboard, sending Ctrl+C, and seeing if it changed —
    the only reliable "was anything selected?" signal Windows offers."""
    old = _clipboard_get()
    if not _clipboard_set(_SENTINEL):
        return None, old
    copy_selection()
    # Apps write the clipboard asynchronously — poll briefly instead of one
    # fixed sleep so fast apps stay fast and slow apps still work.
    sel = None
    deadline = time.monotonic() + 0.8
    while time.monotonic() < deadline:
        time.sleep(0.05)
        now = _clipboard_get()
        if now is not None and now != _SENTINEL:
            sel = now
            break
    return sel, old


def _restore_clipboard(old: str | None):
    if old is not None:
        _clipboard_set(old)
    else:
        _clipboard_set("")


class Transformer:
    def __init__(self, llm, tf_cfg: dict | None, history=None, notify=None):
        self.llm = llm  # cleanup.LlmCleanup — shares the user's Ollama config
        cfg = tf_cfg or {}
        self.polish_prompt = cfg.get("polish_prompt") or POLISH_PROMPT
        self.max_chars = int(cfg.get("max_chars", 8000))
        self.history = history
        self.notify = notify or (lambda *_: None)
        self._busy = False

    def polish(self):
        self.transform_selection(self.polish_prompt, label="Polished")

    def transform_selection(self, system_prompt: str, label: str = "Rewrote"):
        """Read selection → LLM rewrite → paste back in place."""
        if self._busy:
            return
        self._busy = True
        try:
            sel, old = grab_selection()
            if not sel or not sel.strip():
                _restore_clipboard(old)
                self.notify("Select some text first, then press the shortcut.")
                return
            if len(sel) > self.max_chars:
                _restore_clipboard(old)
                self.notify(f"Selection is too long ({len(sel):,} chars — "
                            f"limit {self.max_chars:,}).")
                return
            result = self.llm.run_prompt(system_prompt, sel)
            if result is None:
                _restore_clipboard(old)
                self.notify("This needs the local LLM. Install Ollama, run "
                            "'ollama pull qwen2.5:3b-instruct', and enable "
                            "cleanup.llm in config.")
                return
            result = result.strip()
            if not result or result == sel.strip():
                _restore_clipboard(old)
                self.notify("No changes suggested.")
                return
            if self.history:
                self.history.record(sel, kind="transform-original")
            # paste_text replaces the still-highlighted selection; its own
            # clipboard restore would race ours, so restore manually after.
            paste_text(result, restore=False)
            time.sleep(0.4)  # let the target app read the clipboard first
            _restore_clipboard(old)
            self.notify(f"{label} ✓ — Ctrl+Z in the app to undo; the "
                        "original is in Svara's history.")
        except Exception:  # noqa: BLE001
            log.exception("transform failed")
        finally:
            self._busy = False


class CommandMode:
    """Hold a dedicated key, speak an instruction, release — it's applied to
    the selected text. Off unless shortcuts.command_key is set in config."""

    def __init__(self, key: str, rec_cfg: dict, recorder, get_transcriber,
                 transformer: Transformer, overlay=None, notify=None):
        self.recorder = recorder
        # A getter, not the instance: model/device switches swap the app's
        # transcriber, and commands must use whatever is live right now.
        self.get_transcriber = get_transcriber
        self.transformer = transformer
        self.overlay = overlay
        self.notify = notify or (lambda *_: None)
        self._active = False
        from .hotkey import create_listener
        cfg = dict(rec_cfg)
        cfg.update(hotkey=key, mode="hold_to_record", double_tap_lock=False,
                   suppress_key=False)
        self.listener = create_listener(
            cfg, self._start, self._commit, self._cancel, lambda: None,
            is_recording=lambda: self._active)

    def start(self):
        self.listener.start()
        log.info("command mode armed: hold [%s] and speak an instruction",
                 self.listener.spec)

    def stop(self):
        try:
            self.listener.stop()
        except Exception:  # noqa: BLE001
            pass

    def _start(self):
        if self.recorder.recording:  # a dictation is running — stay out
            return
        self._active = True
        self.recorder.start()
        if self.overlay:
            self.overlay.show("listening")

    def _cancel(self):
        if not self._active:
            return
        self._active = False
        self.recorder.stop(keep_tail=False)
        if self.overlay:
            self.overlay.hide()

    def _commit(self):
        if not self._active:
            return
        self._active = False
        audio = self.recorder.stop()
        if self.overlay:
            self.overlay.hide()
        if audio is None:
            return
        import threading

        def work():
            try:
                segs = self.get_transcriber().transcribe(audio)
                instruction = " ".join(t for t, _, _ in segs).strip()
                if not instruction:
                    self.notify("Didn't catch an instruction — try again.")
                    return
                log.info("voice command: %s", instruction)
                self.transformer.transform_selection(
                    f"{COMMAND_PROMPT}\n\nINSTRUCTION: {instruction}",
                    label="Applied")
            except Exception:  # noqa: BLE001
                log.exception("voice command failed")

        threading.Thread(target=work, daemon=True, name="command-mode").start()
