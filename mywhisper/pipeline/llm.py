"""Local-LLM access — the generative cleanup layer, kept on your machine.

This is the piece cloud dictation tools route to a hosted frontier model. Svara
speaks both local dialects instead:

- ollama:  POST {url}/api/chat            (probe: GET {url}/api/tags)
- openai:  POST {openai_url}/chat/completions — LM Studio, llama.cpp server,
           Jan, vLLM… (probe: GET {openai_url}/models)

`api: "auto"` probes Ollama first, then the OpenAI-compatible endpoint, and
remembers what answered. In openai mode the model id comes from the server's
/models list unless `openai_model` pins one — LM Studio serves whatever the user
loaded, so asking beats guessing.

Nothing in here logs prompt or completion text.
"""

import json
import logging
import time
import urllib.error
import urllib.request

from ..redact import E_LLM_CALL, E_LLM_UNREACHABLE, shape
from .base import BaseStage, UtteranceContext

log = logging.getLogger(__name__)


class LlmCleanup:
    def __init__(self, llm_cfg: dict):
        self.cfg = llm_cfg
        self._backend: str | None = None   # "ollama" | "openai" | None
        self._backend_known = False
        self._openai_model: str | None = None
        self._probed_at = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.cfg["enabled"])

    def _openai_base(self) -> str:
        return (self.cfg.get("openai_url")
                or "http://localhost:1234/v1").rstrip("/")

    def _probe_ollama(self) -> bool:
        try:
            with urllib.request.urlopen(
                    self.cfg["url"].rstrip("/") + "/api/tags", timeout=2.0):
                return True
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def _probe_openai(self) -> bool:
        try:
            with urllib.request.urlopen(self._openai_base() + "/models",
                                        timeout=2.0) as r:
                body = json.loads(r.read().decode("utf-8"))
            models = [m.get("id") for m in body.get("data") or [] if m.get("id")]
            if not models:
                return False
            self._openai_model = (self.cfg.get("openai_model") or models[0])
            return True
        except (urllib.error.URLError, TimeoutError, OSError,
                json.JSONDecodeError):
            return False

    def backend(self, ttl_s: float = 600.0) -> str | None:
        """Which local LLM server is answering. Cached both ways — probing
        per-utterance would add latency; a found server is trusted for ttl_s,
        a missing one re-probed after 60s so starting LM Studio/Ollama is
        noticed quickly."""
        now = time.monotonic()
        window = ttl_s if self._backend is not None else 60.0
        if self._backend_known and now - self._probed_at < window:
            return self._backend
        api = str(self.cfg.get("api", "auto")).lower()
        self._probed_at = now
        if api == "ollama":
            self._backend = "ollama" if self._probe_ollama() else None
        elif api == "openai":
            self._backend = "openai" if self._probe_openai() else None
        else:  # auto
            self._backend = ("ollama" if self._probe_ollama()
                             else "openai" if self._probe_openai() else None)
        self._backend_known = True
        if self._backend:
            log.info("local LLM found: %s", self._backend)
        return self._backend

    def reachable(self, ttl_s: float = 600.0) -> bool:
        return self.backend(ttl_s) is not None

    def _call_ollama(self, system_prompt: str, text: str) -> str:
        payload = {
            "model": self.cfg["model"],
            "stream": False,
            "keep_alive": self.cfg.get("keep_alive", "10m"),
            "options": {"temperature": 0.1},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
        }
        req = urllib.request.Request(
            self.cfg["url"].rstrip("/") + "/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=float(self.cfg["timeout_s"])) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return (body.get("message") or {}).get("content", "").strip()

    def _call_openai(self, system_prompt: str, text: str) -> str:
        payload = {
            "model": self._openai_model or self.cfg.get("openai_model") or "",
            "stream": False,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
        }
        req = urllib.request.Request(
            self._openai_base() + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=float(self.cfg["timeout_s"])) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        choices = body.get("choices") or []
        msg = (choices[0].get("message") or {}) if choices else {}
        return (msg.get("content") or "").strip()

    def run_prompt(self, system_prompt: str, text: str,
                   style_hint: str | None = None) -> str | None:
        """One chat call with an arbitrary system prompt. Returns None on any
        failure — callers decide whether that means "fall back to the input"
        (dictation cleanup) or "tell the user" (transforms)."""
        if len(text) < 4:
            return text
        if style_hint:
            system_prompt = f"{system_prompt}\n\nTone/style: {style_hint}"
        backend = self.backend()
        if backend is None:
            log.warning("%s no local LLM server answering — using raw transcript",
                        E_LLM_UNREACHABLE)
            return None
        try:
            t0 = time.perf_counter()
            cleaned = (self._call_ollama(system_prompt, text)
                       if backend == "ollama"
                       else self._call_openai(system_prompt, text))
            log.debug("llm %s: %s in %.2fs", backend, shape(text),
                      time.perf_counter() - t0)
            # Defensive: models sometimes wrap output in quotes or fences.
            cleaned = cleaned.strip("`").strip()
            if cleaned.startswith('"') and cleaned.endswith('"') and len(cleaned) > 2:
                cleaned = cleaned[1:-1]
            return cleaned or None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError,
                OSError, IndexError, KeyError) as e:
            log.warning("%s LLM cleanup unavailable via %s (%s) — using raw "
                        "transcript", E_LLM_CALL, backend, type(e).__name__)
            self._backend, self._backend_known = None, True
            self._probed_at = time.monotonic()
            return None

    def run(self, text: str, style_hint: str | None = None) -> str:
        """Dictation cleanup: LLM pass, falling back to the input on error."""
        out = self.run_prompt(self.cfg["prompt"], text, style_hint=style_hint)
        return out if out is not None else text


class LlmStage(BaseStage):
    """Engages when the user forced it on (`llm.enabled`) or when the cleanup
    dial is at "high" and a local server is actually answering. Level "high"
    with no server behaves exactly as "medium" — no hang, no error, no
    surprise."""

    name = "llm"
    min_level = 0  # gated by `applies`, not by level: `llm.enabled` forces it on

    def __init__(self, llm: LlmCleanup):
        self.llm = llm

    def applies(self, ctx: UtteranceContext) -> bool:
        from .base import rank
        if self.llm.enabled:
            return True
        return rank(ctx.level) >= 3 and self.llm.reachable()

    def run(self, text: str, ctx: UtteranceContext) -> str:
        return self.llm.run(text, style_hint=ctx.style_hint)
