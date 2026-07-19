"""Transcript post-processing — the "Wispr magic" layer.

Two stages, both optional:
1. Cheap regex filler stripping (um/uh/erm…), on by default.
2. Local LLM cleanup via Ollama (punctuation, false starts, self-corrections),
   off by default; enable in config once Ollama is installed.
"""

import json
import logging
import re
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

_FILLER_RE = re.compile(r"\b(?:um+|uh+|uhm+|erm+|hmm+|mmm+)\b[,.]?\s*", re.IGNORECASE)
_SPACE_RE = re.compile(r"[ \t]{2,}")
_SPACE_PUNCT_RE = re.compile(r"\s+([,.!?;:])")


def strip_fillers(text: str) -> str:
    out = _FILLER_RE.sub("", text)
    out = _SPACE_RE.sub(" ", out)
    out = _SPACE_PUNCT_RE.sub(r"\1", out)
    return out.strip()


# Spoken-punctuation vocabulary: (phrase, exact replacement). The replacement
# includes its own spacing — trailing marks glue left ("hello. "), opening
# marks glue right (" (") — so one pass needs no cleanup afterwards.
_SPOKEN_PUNCT = [
    ("new paragraph", "\n\n"), ("new line", "\n"),
    ("question mark", "? "), ("exclamation mark", "! "),
    ("exclamation point", "! "), ("full stop", ". "), ("period", ". "),
    ("comma", ", "), ("semicolon", "; "), ("colon", ": "),
    ("open quote", " “"), ("close quote", "” "),
    ("open paren", " ("), ("close paren", ") "), ("dash", " — "),
    ("ellipsis", "… "), ("ampersand", " & "),
    ("at sign", "@"), ("hashtag", " #"), ("percent sign", "% "),
]


class Personalizer:
    """The user's own vocabulary — dictionary boosting happens at decode time
    (hotwords); this class is the text side: replacements, snippets, spoken
    punctuation. All matching is case-insensitive on word boundaries so
    "swara" fixes "Swara," too, but never rewrites inside another word."""

    def __init__(self, dict_cfg: dict | None):
        self.reload(dict_cfg)

    def reload(self, dict_cfg: dict | None):
        cfg = dict_cfg or {}
        self.words: list[str] = [str(w) for w in (cfg.get("words") or []) if w]
        self.spoken_punct = bool(cfg.get("spoken_punctuation", False))
        self._rules: list[tuple[re.Pattern, str]] = []
        # snippets first: a longer spoken trigger must win over a replacement
        # that happens to match one of its words
        merged = list((cfg.get("snippets") or {}).items())
        merged += list((cfg.get("replacements") or {}).items())
        for heard, typed in sorted(merged, key=lambda kv: -len(kv[0])):
            if not heard or typed is None:
                continue
            try:
                self._rules.append((
                    re.compile(rf"\b{re.escape(str(heard))}\b", re.IGNORECASE),
                    str(typed)))
            except re.error:
                log.warning("bad dictionary rule %r — skipped", heard)

    @property
    def hotwords(self) -> str | None:
        """Decode-time recognition boost for faster-whisper (hotwords param)."""
        return ", ".join(self.words) if self.words else None

    def apply(self, text: str) -> str:
        for pattern, typed in self._rules:
            # re.sub treats backslashes in the replacement as escapes —
            # user text is literal, so escape them (and stray group refs)
            text = pattern.sub(typed.replace("\\", "\\\\"), text)
        if self.spoken_punct:
            for phrase, repl in _SPOKEN_PUNCT:
                # swallow surrounding spaces and any punctuation Whisper stuck
                # around the phrase itself: "hello, comma, world" → "hello, world"
                text = re.sub(rf"[,.]?\s*\b{re.escape(phrase)}\b[,.]?\s*", repl,
                              text, flags=re.IGNORECASE)
            text = _SPACE_RE.sub(" ", text).strip()
        return text


class LlmCleanup:
    def __init__(self, llm_cfg: dict):
        self.cfg = llm_cfg

    @property
    def enabled(self) -> bool:
        return bool(self.cfg["enabled"])

    def run(self, text: str) -> str:
        """Send text through the local Ollama model. Falls back to input on error."""
        if len(text) < 4:
            return text
        payload = {
            "model": self.cfg["model"],
            "stream": False,
            "keep_alive": self.cfg.get("keep_alive", "10m"),
            "options": {"temperature": 0.1},
            "messages": [
                {"role": "system", "content": self.cfg["prompt"]},
                {"role": "user", "content": text},
            ],
        }
        req = urllib.request.Request(
            self.cfg["url"].rstrip("/") + "/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=float(self.cfg["timeout_s"])) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            cleaned = (body.get("message") or {}).get("content", "").strip()
            # Defensive: models sometimes wrap output in quotes or fences.
            cleaned = cleaned.strip("`").strip()
            if cleaned.startswith('"') and cleaned.endswith('"') and len(cleaned) > 2:
                cleaned = cleaned[1:-1]
            return cleaned or text
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            log.warning("LLM cleanup unavailable (%s) — using raw transcript", e)
            return text


class CleanupPipeline:
    def __init__(self, cleanup_cfg: dict, dict_cfg: dict | None = None):
        self.strip_fillers_enabled = bool(cleanup_cfg["strip_fillers"])
        self.llm = LlmCleanup(cleanup_cfg["llm"])
        self.personalizer = Personalizer(dict_cfg)

    def run(self, text: str) -> str:
        if self.strip_fillers_enabled:
            text = strip_fillers(text)
        if self.llm.enabled and text:
            text = self.llm.run(text)
        # Personal rules run LAST: the user's exact fixes must always win,
        # even over an LLM that "helpfully" reverts a name's spelling.
        return self.personalizer.apply(text)
