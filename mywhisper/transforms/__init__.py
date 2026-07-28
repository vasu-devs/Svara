"""Transforms — act on SELECTED text anywhere, powered by your local LLM.

**Slots.** Nine hotkey-addressable rewrites (`transforms.slots`), slot 1
reserved for Prompt Engineer. Each can carry samples of your own writing so the
model matches your voice rather than an adjective's idea of it.

**Polish** (`Win+Alt+P`) keeps working exactly as before, slot-free.

**Command mode** (optional second hotkey): hold it, say an instruction ("make
this friendlier", or a slot name — "apply concise"), release. It applies to the
current selection.

**Diff preview.** A local 3B model rewriting your paragraph is fast and private,
and occasionally drops a clause. `transforms.preview: auto` shows the change
first and applies only what you accept. `on_request` (the default) applies
immediately but keeps the diff available on a shortcut.

Everything needs a local LLM (config: `cleanup.llm`) — without one they toast a
pointer instead of failing silently. Selection is read via Ctrl+C with full
clipboard save/restore; nothing sticks to the clipboard afterwards.
"""

import logging
import threading
import time

from ..injector import _clipboard_get, _clipboard_set, copy_selection, paste_text
from ..redact import shape
from .diff import is_trivial, summarize, word_diff
from .slots import (BUILTINS, POLISH_PROMPT, PROMPT_ENGINEER_PROMPT,
                    SlotRegistry, TransformSlot)

log = logging.getLogger(__name__)

__all__ = ["BUILTINS", "COMMAND_PROMPT", "CommandMode", "POLISH_PROMPT",
           "PROMPT_ENGINEER_PROMPT", "SlotRegistry", "TransformSlot",
           "Transformer", "grab_selection", "is_trivial", "summarize",
           "word_diff"]

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
    _clipboard_set(old if old is not None else "")


class Transformer:
    def __init__(self, llm, tf_cfg: dict | None, history=None, notify=None,
                 app=None):
        self.llm = llm            # pipeline.LlmCleanup — shares the LLM config
        self.registry = SlotRegistry(tf_cfg)
        self.history = history
        self.notify = notify or (lambda *_: None)
        self.app = app            # for the diff window's theme; optional
        self._busy = False
        self._last: tuple[str, str, str] | None = None   # before, after, label

    # -- reload ---------------------------------------------------------------

    def reload(self, tf_cfg: dict | None):
        self.registry.reload(tf_cfg)

    @property
    def max_chars(self) -> int:
        return self.registry.max_chars

    @property
    def polish_prompt(self) -> str:
        return self.registry.polish_prompt

    # -- entry points ---------------------------------------------------------

    def polish(self):
        self.transform_selection(self.registry.polish_prompt, label="Polished")

    def run_slot(self, number: int):
        slot = self.registry.get(number)
        if slot is None:
            self.notify(f"Transform slot {number} isn't configured. Add it "
                        "under transforms.slots in config.yaml.")
            return
        self.transform_selection(slot.system_prompt(), label=slot.name)

    def run_named(self, spoken: str) -> bool:
        """Voice addressing — "apply concise". True if a slot matched."""
        slot = self.registry.by_name(spoken)
        if slot is None:
            return False
        self.transform_selection(slot.system_prompt(), label=slot.name)
        return True

    # -- the dictation-time hook (transforms.auto_after_dictation) ------------

    def apply_to_text(self, text: str, slot: TransformSlot | None = None
                      ) -> str | None:
        """Run a slot over text we already have, without touching the
        selection or the clipboard. Used by `auto_after_dictation`, which runs
        on every finished dictation — so a missing LLM must be a silent no-op
        here, not a toast on every utterance."""
        slot = slot or self.registry.auto_slot()
        if slot is None or not text or not text.strip():
            return None
        if len(text) > self.registry.max_chars:
            return None
        if not self.llm.reachable():
            return None
        result = self.llm.run_prompt(slot.system_prompt(), text)
        if not result or result.strip() == text.strip():
            return None
        return result.strip()

    # -- selection transforms -------------------------------------------------

    def transform_selection(self, system_prompt: str, label: str = "Rewrote"):
        """Read selection → LLM rewrite → (optionally preview) → paste back."""
        if self._busy:
            return
        self._busy = True
        try:
            sel, old = grab_selection()
            if not sel or not sel.strip():
                _restore_clipboard(old)
                self.notify("Select some text first, then press the shortcut.")
                return
            if len(sel) > self.registry.max_chars:
                _restore_clipboard(old)
                self.notify(f"Selection is too long ({len(sel):,} chars — "
                            f"limit {self.registry.max_chars:,}).")
                return
            result = self.llm.run_prompt(system_prompt, sel)
            if result is None:
                _restore_clipboard(old)
                self.notify("This needs a local LLM. Start LM Studio's local "
                            "server (with any model loaded) or install "
                            "Ollama — Svara finds either automatically.")
                return
            result = result.strip()
            if not result or result == sel.strip():
                _restore_clipboard(old)
                self.notify("No changes suggested.")
                return

            self._last = (sel, result, label)
            if self.registry.preview == "auto" and not is_trivial(sel, result):
                if not self._confirm(sel, result, label):
                    _restore_clipboard(old)
                    self.notify("Kept your original.")
                    return

            if self.history:
                self.history.record(sel, kind="transform-original")
            # paste_text replaces the still-highlighted selection; its own
            # clipboard restore would race ours, so restore manually after.
            paste_text(result, restore=False)
            time.sleep(0.4)  # let the target app read the clipboard first
            _restore_clipboard(old)
            added, removed = summarize(sel, result)
            log.info("transform %r applied: +%dw −%dw (%s)", label, added,
                     removed, shape(result))
            self.notify(f"{label} ✓ +{added}/−{removed} — Ctrl+Z in the app to "
                        "undo; the original is in Svara's history.")
        except Exception:  # noqa: BLE001
            log.exception("transform failed")
        finally:
            self._busy = False

    def _confirm(self, before: str, after: str, label: str) -> bool:
        try:
            from ..howto_ui import show_diff
            return show_diff(self.app, before, after, label=label)
        except Exception:  # noqa: BLE001
            # No display, no Tk, broken window — do NOT silently apply an
            # unreviewed rewrite when the user asked to review every one.
            log.exception("diff preview unavailable — treating as reject")
            return False

    def view_last_diff(self):
        """`shortcuts.view_diff` — what did that last transform actually do?"""
        if not self._last:
            self.notify("No transform to review yet.")
            return
        before, after, label = self._last
        try:
            from ..howto_ui import show_diff
            keep_original = not show_diff(self.app, before, after,
                                          label=f"{label} (review)",
                                          mode="review")
        except Exception:  # noqa: BLE001
            log.exception("diff preview unavailable")
            return
        if keep_original:
            _clipboard_set(before)
            self.notify("Your original is on the clipboard — Ctrl+V to put it "
                        "back.")


class CommandMode:
    """Hold a dedicated key, speak an instruction, release — it's applied to
    the selected text. Off unless `shortcuts.command_key` is set in config."""

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
        from ..hotkey import create_listener
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

        def work():
            try:
                segs = self.get_transcriber().transcribe(audio)
                instruction = " ".join(t for t, _, _ in segs).strip()
                if not instruction:
                    self.notify("Didn't catch an instruction — try again.")
                    return
                log.info("voice command received (%s)", shape(instruction))
                # "apply concise" / "make it concise" addresses a slot by name;
                # anything else is a free-form instruction.
                if self.transformer.run_named(instruction):
                    return
                self.transformer.transform_selection(
                    f"{COMMAND_PROMPT}\n\nINSTRUCTION: {instruction}",
                    label="Applied")
            except Exception:  # noqa: BLE001
                log.exception("voice command failed")

        threading.Thread(target=work, daemon=True, name="command-mode").start()
