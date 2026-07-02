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
    def __init__(self, cleanup_cfg: dict):
        self.strip_fillers_enabled = bool(cleanup_cfg["strip_fillers"])
        self.llm = LlmCleanup(cleanup_cfg["llm"])

    def run(self, text: str) -> str:
        if self.strip_fillers_enabled:
            text = strip_fillers(text)
        if self.llm.enabled and text:
            text = self.llm.run(text)
        return text
