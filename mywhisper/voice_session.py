"""Voice onboarding: the user reads lines we show, in several styles, and
every take is kept with its reference text. See docs/voice-onboarding-design.md.

What the recordings are for, in order of value: a real word error rate for
every engine on THIS voice, a personal correction layer mined from the
systematic misses, and (on a GPU) an adapted model. All of it stays on the
machine, under the user's data directory; one call wipes it.

This module is the session itself: which line comes next, where a take is
saved, how far along the user is. The app feeds it audio; the island shows
its prompt. No audio is interpreted here.
"""

import json
import logging
import random
import time
import wave
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

# Lines 1-30: Harvard sentences (IEEE 1969, public domain), phonetically
# balanced. 31-40: the pairs accented English tends to merge. 41-60: the
# user's world — numbers, code, names, Svara's own spoken commands.
LINES = [
    "The birch canoe slid on the smooth planks.",
    "Glue the sheet to the dark blue background.",
    "It's easy to tell the depth of a well.",
    "These days a chicken leg is a rare dish.",
    "Rice is often served in round bowls.",
    "The juice of lemons makes fine punch.",
    "The box was thrown beside the parked truck.",
    "The hogs were fed chopped corn and garbage.",
    "Four hours of steady work faced us.",
    "A large size in stockings is hard to sell.",
    "The boy was there when the sun rose.",
    "A rod is used to catch pink salmon.",
    "The source of the huge river is the clear spring.",
    "Kick the ball straight and follow through.",
    "Help the woman get back to her feet.",
    "A pot of tea helps to pass the evening.",
    "Smoky fires lack flame and heat.",
    "The soft cushion broke the man's fall.",
    "The salt breeze came across from the sea.",
    "The girl at the booth sold fifty bonds.",
    "The small pup gnawed a hole in the sock.",
    "The fish twisted and turned on the bent hook.",
    "Press the pants and sew a button on the vest.",
    "The swan dive was far short of perfect.",
    "The beauty of the view stunned the young boy.",
    "Two blue fish swam in the tank.",
    "Her purse was full of useless trash.",
    "The colt reared and threw the tall rider.",
    "It snowed, rained, and hailed the same morning.",
    "Read verse out loud for pleasure.",
    "Vicky's wet velvet vest was worth twelve wins.",
    "Three thin thieves thought they'd thread the needle.",
    "She sells sushi while Sasha shows the shells.",
    "Larry really relies on the rural railway.",
    "Keep the cap on the cup until the top pops.",
    "The bat, the bad, the back, the bag, the bass.",
    "Thirty-three thirsty thrushes threw thistles.",
    "Please place the pleated plaid blanket flat.",
    "Which witch watched the wedge of cheese?",
    "The judge urged the jury to adjourn gently.",
    "My email is first dot last at example dot com.",
    "Meet me at 4:45 on the 23rd of March, not the 24th.",
    "The invoice total is 1,250 dollars and 99 cents.",
    "Call 555-0123 and ask for extension 42.",
    "The function is called get user by id, in snake case.",
    "Push the branch to GitHub and open a pull request.",
    "Set the timeout to 300 milliseconds and retry twice.",
    "SQL, API, JSON, HTTP, UUID, GPU, and SSH.",
    "The meeting moved from Tuesday to Thursday, no, to Friday.",
    "Send the report to Alice, sorry, to Bob, before lunch.",
    "Remove the last three words.",
    "Scratch that, start the sentence again.",
    "Delete the last sentence and keep the rest.",
    "New paragraph. The second part begins here.",
    "Open quote, buttery smooth, close quote.",
    "Hyprland, Quickshell, Moonshine, Whisper, Ollama, Svara.",
    "Twenty twenty-six, nineteen ninety-nine, two thousand and five.",
    "The quick brown fox jumps over the lazy dog.",
    "Um, so, like, I was thinking we could, uh, ship it today.",
    "That's it, I'm done, stop listening.",
]

# (key, how to read this block, how many of the lines). About 100 takes, 8-10
# minutes of speech: all 60 lines once in the user's normal voice (the
# measurement set), then a short sample of the two styles that hurt
# recognition most. Adaptation gains flatten past ~30 minutes; this is the
# floor that still measures. The control panel's "record more" adds blocks.
STYLES = [
    ("normal", "Read it the way you usually dictate.", 60),
    ("fast", "Read it fast, like you're in a hurry.", 20),
    ("quiet", "Read it quietly, almost a murmur.", 20),
]

# Labels for the progress rail, where the full hint would not fit.
SHORT = {"normal": "Your usual way", "fast": "Fast", "clear": "Slow and clear",
         "quiet": "Quiet", "loud": "Loud", "flat": "Tired and flat",
         "accent": "Strongest accent"}

MIN_TAKE_S = 0.6   # shorter than this is a slip of the key, not a reading
MAX_TAKE_WER = 0.6  # a take must at least resemble its line: above this it is something else


def matches(reference: str, heard: str) -> bool:
    """Did the mic hear the line? Accent and a misread word pass; a sentence
    said to someone else, silence, or 'hello' do not. Hands-free listening
    depends on this: without it the session saves the room."""
    from .bench import wer
    if not heard or not heard.strip():
        return False
    return wer(reference, heard) <= MAX_TAKE_WER
SR = 16000


class VoiceSession:
    def __init__(self, root: Path, lines: list[str] | None = None,
                 styles: list[tuple[str, str]] | None = None, seed: int = 7):
        self.root = Path(root)
        self.clips = self.root / "clips"
        self.index = self.root / "lines.jsonl"
        self.lines = list(lines or LINES)
        # (key, hint) or (key, hint, count); a missing count means every line
        self.styles = [(st[0], st[1]) for st in (styles or STYLES)]
        self._count = {st[0]: (st[2] if len(st) > 2 else len(self.lines))
                       for st in (styles or STYLES)}
        self.clips.mkdir(parents=True, exist_ok=True)
        self._done: set[tuple[int, str]] = set()
        self._takes: dict[tuple[int, str], int] = {}
        self.last_text = ""          # the line whose take was saved most recently
        self.seconds = 0.0           # audio kept so far, this session and earlier ones
        for rec in self.records():
            try:
                key = (int(rec["line_id"]), str(rec["style"]))
            except (ValueError, KeyError, TypeError):
                continue
            self._done.add(key)
            self._takes[key] = max(self._takes.get(key, 0), int(rec.get("take", 1)))
            self.seconds += float(rec.get("duration_s", 0) or 0)
        # one shuffled line order per style, stable across restarts
        self._order = {}
        for i, (style, _hint) in enumerate(self.styles):
            ids = list(range(1, len(self.lines) + 1))
            random.Random(seed + i).shuffle(ids)
            self._order[style] = ids[:self._count[style]]

    # -- where we are ----------------------------------------------------------------

    @property
    def total(self) -> int:
        return sum(len(v) for v in self._order.values())

    @property
    def done(self) -> int:
        return sum(1 for style, ids in self._order.items()
                   for i in ids if (i, style) in self._done)

    @property
    def finished(self) -> bool:
        return self.current is None

    @property
    def current(self) -> tuple[int, str, str] | None:
        """(line_id, text, style) of the next line to read, or None."""
        for style, _hint in self.styles:
            for line_id in self._order[style]:
                if (line_id, style) not in self._done:
                    return line_id, self.lines[line_id - 1], style
        return None

    def upcoming(self) -> str | None:
        """Text of the line after the current one, for the teleprompter."""
        seen = False
        for style, _hint in self.styles:
            for line_id in self._order[style]:
                if (line_id, style) in self._done:
                    continue
                if seen:
                    return self.lines[line_id - 1]
                seen = True
        return None

    def progress(self) -> list[dict]:
        """Per style: short label, lines done, lines in the block."""
        return [{"label": SHORT.get(style, style),
                 "done": sum(1 for i in self._order[style] if (i, style) in self._done),
                 "total": len(self._order[style])} for style, _hint in self.styles]

    def style_hint(self, style: str) -> str:
        return dict(self.styles).get(style, style)

    def block_start(self) -> bool:
        """True when the current line is the first of its style block."""
        cur = self.current
        if cur is None:
            return False
        return not any(key[1] == cur[2] for key in self._done)

    # -- takes ----------------------------------------------------------------------

    def save_take(self, audio: np.ndarray) -> Path | None:
        """Keep `audio` (float32, 16 kHz) as the current line's take and move
        on. None when there is nothing to read or the take was a key slip."""
        cur = self.current
        if cur is None or audio is None or len(audio) < MIN_TAKE_S * SR:
            return None
        line_id, text, style = cur
        take = self._takes.get((line_id, style), 0) + 1
        path = self.clips / f"{line_id:03d}-{style}-{take}.wav"
        pcm = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes((pcm * 32767).astype("<i2").tobytes())
        rec = {"line_id": line_id, "text": text, "style": style, "take": take,
               "wav": str(path.relative_to(self.root)),
               "duration_s": round(len(audio) / SR, 2),
               "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        with self.index.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        self._done.add((line_id, style))
        self._takes[(line_id, style)] = take
        self.last_text = text
        self.seconds += len(audio) / SR
        return path

    def skip(self) -> None:
        """Mark the current line done without a take (the user passed on it)."""
        cur = self.current
        if cur is not None:
            self._done.add((cur[0], cur[2]))

    def records(self) -> list[dict]:
        if not self.index.exists():
            return []
        out = []
        for raw in self.index.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(raw))
            except ValueError:
                continue
        return out
