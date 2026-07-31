"""Moonshine ONNX backend — the recogniser that doesn't pad to 30 seconds.

ROADMAP item #1, measured on this machine before a line of this file was
written: on a **1-second streaming window Moonshine tiny decodes in ~120 ms
where faster-whisper base.en needs ~630 ms** — because Whisper's encoder runs
on a mel spectrogram padded to a fixed 30 s and Moonshine's runs on what you
actually said. On a full 7.4 s utterance the two produce the same transcript at
the same cost. Variable-length input is the entire premise, and it is exactly
the shape of Svara's streaming problem.

Trade-offs, stated up front:
- **English only.** The registry refuses it for other languages.
- **No word timings** from the decoder. Timings drive window trimming and
  loudness→CAPS, so partials here are decoded per **Silero-VAD chunk** and the
  chunk boundaries become segment boundaries — trimming keeps working, CAPS
  degrades to chunk granularity.
- **No hotwords.** The personal dictionary's decode-time boost does not apply;
  replacement rules still run. This is why `hybrid` (Moonshine partials +
  faster-whisper finals) is the recommended way to use it.

The model loader below is vendored from Useful Sensors' `useful-moonshine-onnx`
package (MIT licence, Copyright (c) 2024 Useful Sensors) rather than imported:
the package's install-time dependency tail (librosa → numba → llvmlite, scipy,
scikit-learn) exists only for decoding audio *files*, which Svara never does —
we always hand it a numpy array. Vendoring the ~100 loader lines keeps roughly
200 MB of transitive weight out of the frozen build. Runtime needs only
`onnxruntime`, `huggingface_hub`, `tokenizers`, and numpy — the last three ship
with faster-whisper already. The tokenizer JSON is carried in `assets/`
(also MIT, same origin) because the upstream HF repo does not host it.
"""

import logging
import sys
import threading
import time
from pathlib import Path

import numpy as np

from ..redact import E_STT_LOAD
from .base import AsrBackend, BackendCaps, Segment

log = logging.getLogger(__name__)

SR = 16000
MAX_CLIP_S = 60.0        # Moonshine rejects >64 s in one call — stay clear
_MODELS = {
    "tiny": dict(num_layers=6, num_key_value_heads=8, head_dim=36),
    "base": dict(num_layers=8, num_key_value_heads=8, head_dim=52),
}


def _tokenizer_path() -> Path | None:
    """assets/moonshine-tokenizer.json — repo, frozen bundle, or the installed
    upstream package, whichever exists."""
    candidates = []
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidates.append(base / "assets" / "moonshine-tokenizer.json")
    candidates.append(Path(__file__).resolve().parents[2] / "assets"
                      / "moonshine-tokenizer.json")
    try:
        import moonshine_onnx
        candidates.append(Path(moonshine_onnx.ASSETS_DIR) / "tokenizer.json")
    except ImportError:
        pass
    for c in candidates:
        if c.is_file():
            return c
    return None


class _VendoredMoonshine:
    """Minimal port of MoonshineOnnxModel (MIT, Useful Sensors): two ONNX
    sessions and a greedy KV-cached decode loop."""

    def __init__(self, size: str):
        import onnxruntime
        from huggingface_hub import hf_hub_download

        if size not in _MODELS:
            raise ValueError(f"unknown moonshine size {size!r} "
                             f"(known: {', '.join(_MODELS)})")
        spec = _MODELS[size]
        self.num_layers = spec["num_layers"]
        self.num_key_value_heads = spec["num_key_value_heads"]
        self.head_dim = spec["head_dim"]
        self.decoder_start_token_id = 1
        self.eos_token_id = 2

        sub = f"onnx/merged/{size}/float"
        encoder = hf_hub_download("UsefulSensors/moonshine",
                                  "encoder_model.onnx", subfolder=sub)
        decoder = hf_hub_download("UsefulSensors/moonshine",
                                  "decoder_model_merged.onnx", subfolder=sub)
        opts = onnxruntime.SessionOptions()
        opts.log_severity_level = 3  # ORT is chatty at INFO
        self.encoder = onnxruntime.InferenceSession(encoder, opts)
        self.decoder = onnxruntime.InferenceSession(decoder, opts)
        self.encoder_input_names = [x.name for x in self.encoder.get_inputs()]
        self.decoder_input_names = [x.name for x in self.decoder.get_inputs()]

    def generate(self, audio: np.ndarray, max_len: int | None = None) -> list[int]:
        """audio: float32 [num_samples] @16 kHz → token ids (greedy).

        Two guards the upstream loop doesn't have, both for the streaming
        case where a chunk ends mid-word: a duration-scaled token budget
        (0.8 s of speech is not 40 tokens), and an abort when the tail of
        the sequence starts repeating itself — the failure mode of greedy
        decoding on truncated audio is a loop, and every looped token is
        pure wasted latency followed by garbage text."""
        audio = audio.astype(np.float32)[np.newaxis, :]
        if max_len is None:
            # ≈ 8 tokens/s of real speech, plus a little headroom.
            max_len = max(12, int(audio.size / SR * 8) + 8)
        mask = np.ones_like(audio, dtype=np.int64)
        enc_in = {"input_values": audio}
        if "attention_mask" in self.encoder_input_names:
            enc_in["attention_mask"] = mask
        hidden = self.encoder.run(None, enc_in)[0]

        past = {
            f"past_key_values.{i}.{a}.{b}": np.zeros(
                (0, self.num_key_value_heads, 1, self.head_dim),
                dtype=np.float32)
            for i in range(self.num_layers)
            for a in ("decoder", "encoder") for b in ("key", "value")
        }
        tokens = [self.decoder_start_token_id]
        input_ids = [tokens]
        for i in range(max_len):
            use_cache = i > 0
            dec_in = dict(input_ids=input_ids, encoder_hidden_states=hidden,
                          use_cache_branch=[use_cache], **past)
            if "encoder_attention_mask" in self.decoder_input_names:
                dec_in["encoder_attention_mask"] = mask
            logits, *present = self.decoder.run(None, dec_in)
            next_token = int(logits[0, -1].argmax())
            tokens.append(next_token)
            if next_token == self.eos_token_id:
                break
            if _looping(tokens):
                break
            input_ids = [[next_token]]
            for k, v in zip(past.keys(), present):
                if not use_cache or "decoder" in k:
                    past[k] = v
        return tokens


def _looping(tokens: list[int], span: int = 4) -> bool:
    """The last `span` tokens exactly repeat the `span` before them."""
    if len(tokens) < 2 * span + 1:
        return False
    return tokens[-span:] == tokens[-2 * span:-span]


_BUCKET = SR // 2  # 0.5 s


def _bucket_pad(audio: np.ndarray) -> np.ndarray:
    """Pad with trailing silence up to the next 0.5 s bucket.

    onnxruntime tunes kernels per input shape; VAD hands us a different chunk
    length every pass, and each novel length costs ~100 ms of re-tuning.
    Bucketing bounds the shape set so after a few passes everything is warm.
    A beat of trailing silence is indistinguishable from the speaker pausing."""
    want = max(_BUCKET, ((len(audio) + _BUCKET - 1) // _BUCKET) * _BUCKET)
    if want == len(audio):
        return audio
    out = np.zeros(want, dtype=np.float32)
    out[:len(audio)] = audio
    return out


_PHRASE_LOOP = None  # compiled lazily; see _dedupe_loop


def _dedupe_loop(text: str) -> str:
    """Collapse 'this is the sub. this is the sub. this is the sub.' → one.
    Belt-and-suspenders behind the token-level abort."""
    global _PHRASE_LOOP
    if _PHRASE_LOOP is None:
        import re
        _PHRASE_LOOP = re.compile(r"(.{6,60}?)(?:\s*\1){2,}", re.DOTALL)
    return _PHRASE_LOOP.sub(r"\1", text)


def _vad_chunks(audio: np.ndarray) -> list[tuple[int, int]]:
    """[(start_sample, end_sample)] of speech, via the Silero VAD that already
    ships with faster-whisper. Failing that, the whole window is one chunk —
    Moonshine still decodes it; only trimming granularity is lost."""
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        spans = get_speech_timestamps(
            audio, VadOptions(min_silence_duration_ms=300,
                              speech_pad_ms=120))
        out = [(int(s["start"]), int(s["end"])) for s in spans]
        return out or [(0, len(audio))]
    except Exception:  # noqa: BLE001 — VAD is an optimisation, not a dependency
        return [(0, len(audio))]


class MoonshineBackend(AsrBackend):
    def __init__(self, mcfg: dict):
        self.cfg = mcfg
        self.device_used = "cpu"       # ONNX CPU EP — that is the point: it's fast there
        self.compute_used = "onnx-float"
        self.model = None              # parity with the fw backend attribute
        self._lock = threading.Lock()
        size = str(mcfg.get("moonshine", "tiny")).split("/")[-1]
        tok_path = _tokenizer_path()
        if tok_path is None:
            raise RuntimeError(f"{E_STT_LOAD} moonshine tokenizer asset missing")
        t0 = time.perf_counter()
        log.info("Loading model 'moonshine/%s' (onnx, cpu)…", size)
        self._model = _VendoredMoonshine(size)
        import tokenizers
        self._tokenizer = tokenizers.Tokenizer.from_file(str(tok_path))
        # Warmup so the first real dictation doesn't pay session init —
        # including Silero VAD, whose first call loads its own model.
        self._model.generate(np.zeros(SR // 2, dtype=np.float32))
        _vad_chunks(np.zeros(SR, dtype=np.float32))
        log.info("Model ready: moonshine/%s — load %.1fs",
                 size, time.perf_counter() - t0)
        self._size = size

    @property
    def capabilities(self) -> BackendCaps:
        return BackendCaps(name=f"moonshine/{self._size}",
                           streaming_native=False, multilingual=False,
                           word_timings=False, translate=False, hotwords=False)

    def _decode(self, audio: np.ndarray) -> str:
        if len(audio) < int(0.12 * SR):   # under Moonshine's 0.1 s floor
            return ""
        if len(audio) > int(MAX_CLIP_S * SR):
            audio = audio[-int(MAX_CLIP_S * SR):]
        tokens = self._model.generate(_bucket_pad(audio))
        text = self._tokenizer.decode(tokens, skip_special_tokens=True).strip()
        return _dedupe_loop(text)

    def transcribe(self, audio: np.ndarray) -> list[Segment]:
        """Final pass: decode per VAD chunk so long utterances stay under the
        64 s ceiling and segments carry usable boundaries."""
        with self._lock:
            segs = []
            for start, end in _vad_chunks(audio):
                text = self._decode(audio[start:end])
                if text:
                    segs.append(Segment(text, start / SR, end / SR))
            return segs

    def transcribe_partial(self, audio: np.ndarray,
                           prompt: str | None = None) -> list[Segment]:
        """The pass this backend exists for. VAD-chunked so `plan_trim` gets
        real silence boundaries; `prompt` is accepted-and-ignored (no such
        conditioning in Moonshine)."""
        with self._lock:
            segs = []
            for start, end in _vad_chunks(audio):
                text = self._decode(audio[start:end])
                if text:
                    segs.append(Segment(text, start / SR, end / SR))
            return segs

    def transcribe_final_window(self, audio: np.ndarray) -> list[Segment]:
        return self.transcribe_partial(audio)
