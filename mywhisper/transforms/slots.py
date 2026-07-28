"""Transform slots — nine voice/hotkey-addressable rewrites of your own design.

One "Polish" prompt covers one intent. In practice people want several: tighten
this, make it friendlier, turn it into bullets, translate the tone into
something an executive will read. So: slots 1–9, each a named prompt bound to a
hotkey, addressable by voice ("apply concise").

**Slot 1 is reserved for Prompt Engineer**, matching the convention the
category has settled on. Rambling at an AI is the single most common thing
people dictate now, and turning a rambled thought into a structured prompt is
the transform that pays for itself fastest.

**Style-by-example.** A slot can point at 1–5 sample files of the user's own
writing, 50–500 words each. They are appended to the system prompt as style
anchors, which teaches tone far better than an adjective does. Both bounds are
enforced: under 50 words carries no signal, and a 3B model running locally has
a real latency cliff — five 500-word samples is a ~3,000-word system prompt on
every keystroke. `MAX_SAMPLE_BUDGET` caps the total and warns rather than
silently blowing `timeout_s`.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..redact import E_CFG_PARSE

log = logging.getLogger(__name__)

MIN_SAMPLE_WORDS = 50
MAX_SAMPLE_WORDS = 500
MAX_SAMPLES = 5
MAX_SAMPLE_BUDGET = 1500      # total words across a slot's samples
MAX_SLOTS = 9

POLISH_PROMPT = (
    "You are a writing polish tool. Rewrite the user's text to be clearer and "
    "more concise. Fix grammar and punctuation. Preserve the meaning, tone, "
    "formatting, links and language. Never add new content or commentary. "
    "Output ONLY the rewritten text."
)

PROMPT_ENGINEER_PROMPT = (
    "You are a prompt engineer. The user dictated a rough, spoken request "
    "intended for an AI assistant. Rewrite it as a clear, well-structured "
    "prompt: state the goal up front, keep every concrete constraint, "
    "requirement, filename and number the user mentioned, and drop the "
    "thinking-out-loud. Use short paragraphs or bullets where that helps. "
    "Do not answer the request, do not invent requirements the user did not "
    "state, and do not add a preamble. Output ONLY the rewritten prompt."
)

BUILTINS = {
    "polish": POLISH_PROMPT,
    "prompt_engineer": PROMPT_ENGINEER_PROMPT,
}


@dataclass
class TransformSlot:
    number: int
    name: str
    prompt: str
    hotkey: str | None = None
    samples: list[str] = field(default_factory=list)
    builtin: str | None = None
    _sample_text: str | None = field(default=None, repr=False)

    def system_prompt(self) -> str:
        """The prompt with style anchors attached (loaded once, then cached)."""
        if self._sample_text is None:
            self._sample_text = _load_samples(self.samples, self.name)
        if not self._sample_text:
            return self.prompt
        return (f"{self.prompt}\n\n"
                "Match the voice of these samples of the user's own writing — "
                "their rhythm, vocabulary and level of formality. Do not copy "
                "their content.\n\n"
                f"{self._sample_text}")

    def invalidate(self):
        self._sample_text = None


def _load_samples(paths: list[str], slot_name: str) -> str:
    from ..paths import base_dir

    if not paths:
        return ""
    if len(paths) > MAX_SAMPLES:
        log.warning("transform %r lists %d samples — using the first %d",
                    slot_name, len(paths), MAX_SAMPLES)
        paths = paths[:MAX_SAMPLES]

    chunks, budget = [], MAX_SAMPLE_BUDGET
    for raw in paths:
        p = Path(raw)
        if not p.is_absolute():
            p = base_dir() / p
        try:
            text = p.read_text(encoding="utf-8").strip()
        except OSError:
            log.warning("%s transform %r: sample %s is unreadable — skipped",
                        E_CFG_PARSE, slot_name, p.name)
            continue
        words = text.split()
        if len(words) < MIN_SAMPLE_WORDS:
            log.warning("transform %r: sample %s has %d words (minimum %d) — "
                        "too short to carry a style; skipped",
                        slot_name, p.name, len(words), MIN_SAMPLE_WORDS)
            continue
        if len(words) > MAX_SAMPLE_WORDS:
            log.info("transform %r: sample %s truncated to %d words",
                     slot_name, p.name, MAX_SAMPLE_WORDS)
            words = words[:MAX_SAMPLE_WORDS]
        if len(words) > budget:
            log.warning("transform %r: sample budget (%d words) reached — "
                        "%s and any later samples dropped. A larger prompt "
                        "means a slower local model on every use.",
                        slot_name, MAX_SAMPLE_BUDGET, p.name)
            break
        budget -= len(words)
        chunks.append("--- sample ---\n" + " ".join(words))
    return "\n\n".join(chunks)


class SlotRegistry:
    """Loads, validates and holds the slots. Reloadable without a restart."""

    def __init__(self, tf_cfg: dict | None):
        self.slots: dict[int, TransformSlot] = {}
        self.reload(tf_cfg)

    def reload(self, tf_cfg: dict | None):
        cfg = tf_cfg or {}
        self.max_chars = int(cfg.get("max_chars", 8000))
        self.preview = str(cfg.get("preview", "on_request")).lower()
        self.auto_after = cfg.get("auto_after_dictation")
        slots: dict[int, TransformSlot] = {}
        seen_hotkeys: dict[str, int] = {}

        raw_slots = cfg.get("slots") or {}
        if not isinstance(raw_slots, dict):
            log.error("%s transforms.slots must be a mapping of 1-9 → slot",
                      E_CFG_PARSE)
            raw_slots = {}

        for key, spec in raw_slots.items():
            try:
                number = int(key)
            except (TypeError, ValueError):
                log.warning("%s transform slot key %r is not a number 1-9 — "
                            "skipped", E_CFG_PARSE, key)
                continue
            if not 1 <= number <= MAX_SLOTS:
                log.warning("%s transform slot %d is outside 1-%d — skipped",
                            E_CFG_PARSE, number, MAX_SLOTS)
                continue
            if not isinstance(spec, dict):
                log.warning("%s transform slot %d must be a mapping — skipped",
                            E_CFG_PARSE, number)
                continue

            builtin = spec.get("builtin")
            prompt = spec.get("prompt")
            if builtin:
                if builtin not in BUILTINS:
                    log.warning("%s transform slot %d: unknown builtin %r "
                                "(known: %s) — skipped", E_CFG_PARSE, number,
                                builtin, ", ".join(BUILTINS))
                    continue
                prompt = prompt or BUILTINS[builtin]
            if not prompt:
                log.warning("%s transform slot %d has neither 'prompt' nor "
                            "'builtin' — skipped", E_CFG_PARSE, number)
                continue

            hotkey = spec.get("hotkey") or None
            if hotkey:
                if hotkey in seen_hotkeys:
                    log.warning("transform slot %d wants hotkey %s, already "
                                "bound to slot %d — slot %d gets no hotkey",
                                number, hotkey, seen_hotkeys[hotkey], number)
                    hotkey = None
                else:
                    seen_hotkeys[hotkey] = number

            samples = spec.get("samples") or []
            if isinstance(samples, str):
                samples = [samples]

            slots[number] = TransformSlot(
                number=number,
                name=str(spec.get("name") or f"Transform {number}"),
                prompt=str(prompt),
                hotkey=hotkey,
                samples=[str(s) for s in samples],
                builtin=builtin,
            )

        # Slot 1 defaults to Prompt Engineer when the user hasn't claimed it.
        if 1 not in slots:
            slots[1] = TransformSlot(
                number=1, name="Prompt Engineer",
                prompt=PROMPT_ENGINEER_PROMPT, builtin="prompt_engineer")

        self.slots = slots
        # Legacy `transforms.polish_prompt` still drives the Polish shortcut.
        self.polish_prompt = cfg.get("polish_prompt") or POLISH_PROMPT
        log.info("transform slots ready: %s",
                 ", ".join(f"{n}={s.name}" for n, s in sorted(slots.items())))

    def get(self, number: int) -> TransformSlot | None:
        return self.slots.get(int(number))

    def by_name(self, spoken: str) -> TransformSlot | None:
        """Voice addressing: "apply concise" → the slot named Concise.
        Matches on a normalised prefix so "make it concise" finds "Concise"."""
        want = "".join(c for c in (spoken or "").lower() if c.isalnum() or c == " ").strip()
        if not want:
            return None
        for slot in self.slots.values():
            name = slot.name.lower()
            if name and (name in want or want in name):
                return slot
        return None

    def hotkey_map(self, run) -> dict[str, callable]:
        """{combo: callable} for QuickKeys. `run` takes a slot number."""
        out = {}
        for number, slot in self.slots.items():
            if slot.hotkey:
                out[slot.hotkey] = (lambda n=number: run(n))
        return out

    def auto_slot(self) -> TransformSlot | None:
        if self.auto_after in (None, "", 0, False):
            return None
        try:
            return self.get(int(self.auto_after))
        except (TypeError, ValueError):
            return None
