"""`python -m mywhisper --bench` — the numbers, measured on your machine.

Svara shipped for four versions without publishing a latency or accuracy
figure. That is a fine way to build a product and a bad way to claim one is
fast: "state of the art" is a comparison, and a comparison needs a number.

What it measures, and why each one:

- **TTFW** (time to first word) — hotkey press to first character on screen.
  The only latency the user actually experiences. Everything else is a proxy.
- **Partial-commit latency, p50 / p95 / max** — how long each streaming pass
  takes. Reported as a distribution, never as a mean: published dictation
  benchmarks quote ~275 ms mean with an ~85 ms sigma, which hides a 470 ms
  tail, and the tail is what makes streaming feel like it stutters.
- **WER / CER** — against a reference corpus, overall and restricted to
  dictionary terms, so "does hotword boosting actually work" has an answer.
- **RTF** (real-time factor) — seconds of compute per second of audio. Below
  1.0 or streaming cannot keep up, full stop.
- **Peak RSS** — because a dictation tool that idles at 800 MB is a tax on
  every other app you run.

Every result records the machine, model, device and compute type. A latency
number without its hardware is marketing.

Corpus: drop `<name>.wav` + `<name>.txt` pairs into `bench/corpus/`. WER is
skipped (and said to be skipped) when the directory is empty — silently
reporting 0% on no data would be worse than reporting nothing.
"""

import json
import logging
import platform
import statistics
import subprocess
import sys
import time
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .streaming import StreamState, make_policy

log = logging.getLogger(__name__)

TARGET_TTFW_MS = 300.0        # v1.0 budget from PLAN.md §2
TARGET_P95_MS = 500.0


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _levenshtein(a: list, b: list) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _normalize(text: str) -> list[str]:
    """Standard WER normalisation: casefold, drop punctuation, collapse space.
    Without it you are measuring the post-processor's comma preferences, not
    the recogniser."""
    keep = []
    for ch in (text or "").lower():
        if ch.isalnum() or ch.isspace() or ch == "'":
            keep.append(ch)
        else:
            keep.append(" ")
    return "".join(keep).split()


def wer(reference: str, hypothesis: str) -> float:
    ref = _normalize(reference)
    if not ref:
        return 0.0
    return _levenshtein(ref, _normalize(hypothesis)) / len(ref)


def cer(reference: str, hypothesis: str) -> float:
    ref = " ".join(_normalize(reference))
    if not ref:
        return 0.0
    return _levenshtein(list(ref), list(" ".join(_normalize(hypothesis)))) / len(ref)


def term_recall(reference: str, hypothesis: str, terms: list[str]) -> tuple[int, int]:
    """(hits, occurrences) for dictionary terms — the number that says whether
    hotword boosting earned its place."""
    ref_words = _normalize(reference)
    hyp_words = set(_normalize(hypothesis))
    hits = total = 0
    wanted = {t.lower() for t in terms}
    for word in ref_words:
        if word in wanted:
            total += 1
            if word in hyp_words:
                hits += 1
    return hits, total


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

@dataclass
class Result:
    model: str = ""
    device: str = ""
    compute_type: str = ""
    machine: dict = field(default_factory=dict)
    ttfw_ms: float | None = None
    partial_ms: dict = field(default_factory=dict)
    final_ms: dict = field(default_factory=dict)
    rtf: float | None = None
    wer: float | None = None
    cer: float | None = None
    term_recall: float | None = None
    clips: int = 0
    audio_seconds: float = 0.0
    peak_rss_mb: float | None = None
    warmup_s: float | None = None
    segments_decoded: int = 0
    window_s: dict = field(default_factory=dict)   # audio re-decoded per pass
    valid: bool = True
    notes: list[str] = field(default_factory=list)

    def meets_budget(self) -> bool:
        if not self.valid:
            return False
        return (self.ttfw_ms is not None and self.ttfw_ms <= TARGET_TTFW_MS
                and self.partial_ms.get("p95", 1e9) <= TARGET_P95_MS)


def _machine_info() -> dict:
    info = {
        "os": f"{platform.system()} {platform.release()}",
        "cpu": platform.processor() or platform.machine(),
        "python": platform.python_version(),
        "cores": None,
        "ram_gb": None,
        "gpu": None,
    }
    try:
        import os
        info["cores"] = os.cpu_count()
    except Exception:  # noqa: BLE001
        pass
    try:
        import ctypes

        class _MEMSTAT(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        stat = _MEMSTAT()
        stat.dwLength = ctypes.sizeof(_MEMSTAT)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        info["ram_gb"] = round(stat.ullTotalPhys / (1024 ** 3), 1)
    except Exception:  # noqa: BLE001
        pass
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5, check=False)
        name = (out.stdout or "").strip().splitlines()
        if name:
            info["gpu"] = name[0].strip()
    except Exception:  # noqa: BLE001
        pass
    return info


def _peak_rss_mb() -> float | None:
    try:
        import ctypes
        from ctypes import wintypes

        class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD),
                        ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]

        counters = _PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS)
        # argtypes matter here: without them ctypes passes the process handle
        # as a 32-bit int and the call fails, silently returning a 0 MB peak.
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        get_info = k32.K32GetProcessMemoryInfo
        get_info.argtypes = [wintypes.HANDLE,
                             ctypes.POINTER(_PROCESS_MEMORY_COUNTERS),
                             wintypes.DWORD]
        get_info.restype = wintypes.BOOL
        if not get_info(k32.GetCurrentProcess(), ctypes.byref(counters),
                        counters.cb):
            return None
        return round(counters.PeakWorkingSetSize / (1024 ** 2), 1)
    except Exception:  # noqa: BLE001
        return None


def _percentiles(samples: list[float]) -> dict:
    if not samples:
        return {}
    ordered = sorted(samples)
    def pct(p: float) -> float:
        idx = min(len(ordered) - 1, int(round(p / 100.0 * (len(ordered) - 1))))
        return round(ordered[idx], 1)
    return {
        "n": len(ordered),
        "p50": pct(50), "p95": pct(95),
        "min": round(ordered[0], 1), "max": round(ordered[-1], 1),
        "mean": round(statistics.fmean(ordered), 1),
        "stdev": round(statistics.stdev(ordered), 1) if len(ordered) > 1 else 0.0,
    }


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------

def corpus_dir() -> Path:
    from .paths import base_dir
    return base_dir() / "bench" / "corpus"


def _read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        channels, width, rate, frames = (w.getnchannels(), w.getsampwidth(),
                                         w.getframerate(), w.getnframes())
        raw = w.readframes(frames)
    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(width)
    if dtype is None:
        raise ValueError(f"{path.name}: unsupported sample width {width}")
    audio = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    audio /= float(2 ** (8 * width - 1))
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if rate != 16000:
        # Linear resample. Good enough for a benchmark harness; the corpus
        # should be 16 kHz mono anyway and this only rescues a stray file.
        n_out = int(len(audio) * 16000 / rate)
        audio = np.interp(np.linspace(0, len(audio) - 1, n_out),
                          np.arange(len(audio)), audio).astype(np.float32)
    return audio, 16000


def load_corpus() -> list[tuple[str, np.ndarray, str]]:
    """[(name, audio, reference)] from bench/corpus/*.wav + matching .txt."""
    out = []
    directory = corpus_dir()
    if not directory.is_dir():
        return out
    for wav_path in sorted(directory.glob("*.wav")):
        txt_path = wav_path.with_suffix(".txt")
        if not txt_path.is_file():
            log.warning("bench: %s has no reference .txt — skipped", wav_path.name)
            continue
        try:
            audio, _ = _read_wav(wav_path)
            reference = txt_path.read_text(encoding="utf-8").strip()
        except (OSError, ValueError) as e:
            log.warning("bench: %s unreadable (%s) — skipped", wav_path.name, e)
            continue
        out.append((wav_path.stem, audio, reference))
    return out


def _synthetic_clips(seconds: tuple[float, ...] = (1.0, 3.0, 5.0, 10.0)
                     ) -> list[tuple[str, np.ndarray, str]]:
    """Speech-shaped noise for latency measurement when no corpus exists.

    These produce no meaningful WER — and the report says so rather than
    printing a flattering zero. What they do measure honestly is decode time
    per second of audio, which is what the latency budget is about.
    """
    rng = np.random.default_rng(0xC0FFEE)
    clips = []
    for dur in seconds:
        n = int(dur * 16000)
        noise = rng.standard_normal(n).astype(np.float32)
        # Rough speech envelope: 4 Hz syllable rate, band-limited.
        envelope = 0.5 + 0.5 * np.sin(2 * np.pi * 4 * np.arange(n) / 16000)
        clip = (noise * envelope * 0.05).astype(np.float32)
        clips.append((f"synthetic-{dur:g}s", clip, ""))
    return clips


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

def run_bench(cfg: dict, repeats: int = 3, save: bool = True) -> Result:
    from .transcriber import Transcriber

    mcfg = dict(cfg["model"])
    result = Result(model=str(mcfg.get("name")), machine=_machine_info())

    print(f"\nSvara benchmark — {result.model}")
    print(f"  {result.machine['os']} · {result.machine.get('cpu')} · "
          f"{result.machine.get('cores')} cores · "
          f"{result.machine.get('ram_gb')} GB RAM"
          + (f" · {result.machine['gpu']}" if result.machine.get("gpu") else ""))

    t0 = time.perf_counter()
    transcriber = Transcriber(mcfg)
    result.warmup_s = round(time.perf_counter() - t0, 2)
    result.device = transcriber.device_used
    result.compute_type = transcriber.compute_used
    print(f"  loaded on {result.device} ({result.compute_type}) in "
          f"{result.warmup_s:.1f}s\n")

    clips = load_corpus()
    have_corpus = bool(clips)
    if not have_corpus:
        clips = _synthetic_clips()
        result.notes.append(
            "No corpus found in bench/corpus/ — latency measured on synthetic "
            "speech-shaped audio; WER NOT measured. Add <name>.wav + "
            "<name>.txt pairs for accuracy numbers.")
        print("  ! no corpus — measuring latency only "
              "(drop .wav/.txt pairs into bench/corpus/)\n")

    dictionary_terms = list((cfg.get("dictionary") or {}).get("words") or [])
    scfg = cfg.get("streaming") or {}
    partial_samples: list[float] = []
    final_samples: list[float] = []
    ttfw_samples: list[float] = []
    window_seconds: list[float] = []   # how much audio each partial pass saw
    total_audio = 0.0
    total_compute = 0.0
    decoded = 0                 # segments the decoder actually produced
    wer_scores: list[float] = []
    cer_scores: list[float] = []
    term_hits = term_total = 0

    for name, audio, reference in clips:
        duration = len(audio) / 16000
        for run in range(repeats):
            # TTFW proxy: the first streaming window the app would decode
            # (streaming.min_audio_s of audio), decoded exactly as the streamer
            # decodes it. This is the number the user feels.
            first_window = audio[:int(float(scfg.get("min_audio_s", 0.35)) * 16000)]
            if len(first_window) > 1600:
                t0 = time.perf_counter()
                out = transcriber.transcribe_partial(first_window)
                ttfw_samples.append((time.perf_counter() - t0) * 1000)
                decoded += len(out)

            # Streaming passes, driven through the REAL commit state machine so
            # the window is trimmed exactly as it is in the app. The first cut
            # of this harness re-decoded `audio[:pos]` every pass with no
            # trimming, which made partial latency look far worse than users
            # actually experience — a measurement disagreeing with the thing it
            # measures. Sharing `streaming.py` makes that impossible.
            state = StreamState(
                policy=make_policy(scfg.get("commit_policy", "local_agreement"),
                                   hold_back=int(scfg.get("hold_back", 1)),
                                   confident_after=int(
                                       scfg.get("confident_after", 12))),
                sr=16000,
                max_window_s=float(scfg.get("max_window_s", 0) or 0))
            advance = max(int(16000 * float(scfg.get("interval_ms", 180)) / 1000),
                          1600)
            pos = int(float(scfg.get("min_audio_s", 0.35)) * 16000)
            while pos < len(audio):
                window = audio[state.t0:pos]
                if len(window) < 1600:
                    pos += advance
                    continue
                t0 = time.perf_counter()
                out = transcriber.transcribe_partial(window)
                partial_samples.append((time.perf_counter() - t0) * 1000)
                window_seconds.append(len(window) / 16000)
                decoded += len(out)
                state.step(out, len(window))
                pos += advance

            t0 = time.perf_counter()
            segs = transcriber.transcribe(audio)
            elapsed = time.perf_counter() - t0
            final_samples.append(elapsed * 1000)
            total_compute += elapsed
            total_audio += duration
            decoded += len(segs)

            if run == 0 and have_corpus and reference:
                hypothesis = " ".join(t for t, _, _ in segs)
                wer_scores.append(wer(reference, hypothesis))
                cer_scores.append(cer(reference, hypothesis))
                if dictionary_terms:
                    hits, total = term_recall(reference, hypothesis,
                                              dictionary_terms)
                    term_hits += hits
                    term_total += total
        print(f"  ✓ {name:24} {duration:5.1f}s audio")

    result.clips = len(clips)
    result.segments_decoded = decoded
    result.audio_seconds = round(total_audio, 1)
    # Silero VAD sits in front of the decoder and rejects anything that isn't
    # speech — including the synthetic fallback audio. When that happens every
    # pass returns instantly and the harness would report a gorgeous 5 ms TTFW
    # for a decoder that never ran. That is precisely the flattering-zero
    # failure this file exists to prevent, so the run is marked invalid.
    if decoded == 0:
        result.valid = False
        result.notes.append(
            "NO AUDIO REACHED THE DECODER — the voice-activity filter rejected "
            "every clip, so these timings measure VAD rejection, not "
            "transcription. They are NOT a latency result. Record real speech "
            "into bench/corpus/ (see its README).")
    result.ttfw_ms = round(statistics.median(ttfw_samples), 1) if ttfw_samples else None
    result.partial_ms = _percentiles(partial_samples)
    result.final_ms = _percentiles(final_samples)
    result.window_s = _percentiles(window_seconds)
    result.rtf = round(total_compute / total_audio, 3) if total_audio else None
    result.peak_rss_mb = _peak_rss_mb()
    if wer_scores:
        result.wer = round(statistics.fmean(wer_scores), 4)
        result.cer = round(statistics.fmean(cer_scores), 4)
    if term_total:
        result.term_recall = round(term_hits / term_total, 4)

    _print_report(result)
    if save:
        _save(result)
    return result


def _print_report(r: Result):
    # Without a decode, no timing here means anything — so don't decorate any
    # of them with a budget verdict the reader would take at face value.
    def verdict(ok: bool) -> str:
        if not r.valid:
            return "— not meaningful"
        return "✓" if ok else "✗"

    print("\n" + "─" * 62)
    print(f"  {'model':16} {r.model} on {r.device} ({r.compute_type})")
    if r.ttfw_ms is not None:
        print(f"  {'TTFW':16} {r.ttfw_ms:.0f} ms   "
              f"{verdict(r.ttfw_ms <= TARGET_TTFW_MS)}"
              f"{'' if not r.valid else f' budget {TARGET_TTFW_MS:.0f} ms'}")
    if r.partial_ms:
        p = r.partial_ms
        print(f"  {'partial pass':16} p50 {p['p50']:.0f} · p95 {p['p95']:.0f} · "
              f"max {p['max']:.0f} ms   {verdict(p['p95'] <= TARGET_P95_MS)}"
              f"{'' if not r.valid else f' budget {TARGET_P95_MS:.0f} ms p95'}")
    if r.window_s:
        # Partial latency is mostly a function of this: trimming is what keeps
        # pass time flat however long the utterance runs.
        p = r.window_s
        print(f"  {'window decoded':16} p50 {p['p50']:.1f} · p95 {p['p95']:.1f} · "
              f"max {p['max']:.1f} s of audio per pass")
    if r.final_ms:
        p = r.final_ms
        print(f"  {'final pass':16} p50 {p['p50']:.0f} · p95 {p['p95']:.0f} ms")
    if r.rtf is not None:
        print(f"  {'RTF':16} {r.rtf:.3f}   "
              f"{verdict(r.rtf < 1.0) if r.valid else '— not meaningful'}")
    print(f"  {'decoded':16} {r.segments_decoded} segments")
    if r.wer is not None:
        print(f"  {'WER / CER':16} {r.wer * 100:.2f}% / {r.cer * 100:.2f}%  "
              f"({r.clips} clips, {r.audio_seconds:.0f}s)")
    else:
        print(f"  {'WER':16} not measured (no corpus)")
    if r.term_recall is not None:
        print(f"  {'dict recall':16} {r.term_recall * 100:.1f}%")
    if r.peak_rss_mb:
        print(f"  {'peak RSS':16} {r.peak_rss_mb:.0f} MB")
    print("─" * 62)
    for note in r.notes:
        print(f"  ! {note}")
    print()


def _git_sha() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5,
                             check=False)
        return (out.stdout or "").strip() or "nogit"
    except Exception:  # noqa: BLE001
        return "nogit"


def _save(r: Result):
    from . import __version__
    from .paths import base_dir

    out_dir = base_dir() / "bench" / "results"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        log.warning("could not create %s — result not saved", out_dir)
        return
    payload = asdict(r)
    payload["svara_version"] = __version__
    payload["git"] = _git_sha()
    payload["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    tag = f"{_git_sha()}-{r.model.replace('/', '_')}-{r.device}"
    path = out_dir / f"{tag}.json"
    try:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"  saved → {path.relative_to(base_dir())}\n")
    except OSError:
        log.warning("could not write %s", path)


def main(cfg: dict, repeats: int = 3) -> int:
    try:
        result = run_bench(cfg, repeats=repeats)
    except Exception:  # noqa: BLE001
        log.exception("benchmark failed")
        return 1
    # Non-zero when the run proved nothing or missed the budget, so this can
    # gate a release without anyone having to read the output carefully.
    if not result.valid:
        print("  No usable measurement — see the note above.\n")
        return 3
    if result.ttfw_ms is not None and not result.meets_budget():
        print("  Latency budget missed — see PLAN.md §2 for the targets.\n")
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    from . import config as config_mod
    from .paths import ensure_config

    sys.exit(main(config_mod.load(ensure_config())))
