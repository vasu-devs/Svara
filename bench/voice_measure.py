"""Score every engine on the user's own voice-onboarding takes, and mine the
systematic misses into corrections.

Run (Linux):  .venv/bin/python bench/voice_measure.py [--root DIR] [--engines turbo,moonshine,parakeet]

Reads  <root>/lines.jsonl + clips/ written by mywhisper.voice_session.
Writes <root>/results.json (WER per engine and style, worst lines) and
       <root>/corrections.yaml (hyp → ref substitutions seen ≥2 times, as
       `dictionary.replacements` entries you can paste into config).
Nothing leaves the machine; nothing is logged but numbers.

Callers: none in the app — a user or the control panel runs it after a
session. Depends on mywhisper.bench for the WER normaliser.
"""

import argparse
import difflib
import json
import os
import sys
import time
import wave
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mywhisper.bench import _normalize, wer  # noqa: E402


def default_root() -> Path:
    if os.name == "nt":
        return ROOT / "voice"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "svara" / "voice"


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768


def make_engines(names: list[str]):
    """name → factory() -> callable(audio) -> text. Each loads on first use."""
    from mywhisper.config import load
    cfg = load(str(ROOT / ("config-linux.yaml" if os.name != "nt" else "config.yaml")))
    mcfg = dict(cfg["model"]); mcfg.update(cfg["asr"])
    out = {}
    if "turbo" in names or "whisper" in names:
        def whisper():
            from mywhisper import cuda_setup
            cuda_setup.setup()
            from mywhisper.asr.faster_whisper import FasterWhisperBackend
            b = FasterWhisperBackend(dict(mcfg, hotwords=None))
            return lambda a: " ".join(s.text for s in b.transcribe(a))
        out["whisper:" + str(mcfg["name"])] = whisper
    if "moonshine" in names:
        def moon():
            from mywhisper.asr.moonshine import MoonshineBackend
            b = MoonshineBackend(mcfg)
            return lambda a: " ".join(s.text for s in b.transcribe(a))
        out["moonshine:" + str(mcfg.get("moonshine", "base"))] = moon
    if "parakeet" in names:
        d = next(iter((ROOT / "bench" / "parakeet").glob("sherpa-onnx-nemo-parakeet*")), None)
        if d is not None:
            def para():
                import sherpa_onnx
                rec = sherpa_onnx.OfflineRecognizer.from_transducer(
                    encoder=f"{d}/encoder.int8.onnx", decoder=f"{d}/decoder.int8.onnx",
                    joiner=f"{d}/joiner.int8.onnx", tokens=f"{d}/tokens.txt",
                    num_threads=8, model_type="nemo_transducer")

                def run(a):
                    s = rec.create_stream(); s.accept_waveform(16000, a); rec.decode_stream(s)
                    return s.result.text
                return run
            out["parakeet-tdt-0.6b-v3"] = para
    return out


def mine_corrections(pairs: list[tuple[str, str]]) -> dict[str, str]:
    """hyp phrase → ref phrase for 1-2 word substitutions seen at least twice
    across takes: the user's systematic misses, not noise."""
    seen: Counter = Counter()
    for ref, hyp in pairs:
        r, h = _normalize(ref), _normalize(hyp)
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=h, b=r, autojunk=False).get_opcodes():
            if op == "replace" and 1 <= i2 - i1 <= 2 and 1 <= j2 - j1 <= 2:
                seen[(" ".join(h[i1:i2]), " ".join(r[j1:j2]))] += 1
    return {hyp: ref for (hyp, ref), n in seen.most_common() if n >= 2}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=default_root())
    ap.add_argument("--engines", default="turbo,moonshine,parakeet")
    ap.add_argument("--limit", type=int, default=0, help="only the first N takes (quick look)")
    args = ap.parse_args()
    index = args.root / "lines.jsonl"
    if not index.exists():
        print(f"no takes yet at {args.root} — run the onboarding first (./run.sh --onboard)")
        return 1
    takes = [json.loads(l) for l in index.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.limit:
        takes = takes[:args.limit]
    engines = make_engines(args.engines.split(","))
    results = {"takes": len(takes), "engines": {}}
    best_pairs: list[tuple[str, str]] = []
    best_name, best_wer = None, 9.0
    for name, factory in engines.items():
        t0 = time.perf_counter()
        run = factory()
        load_s = time.perf_counter() - t0
        per_style = defaultdict(list)
        worst = []
        pairs = []
        t0 = time.perf_counter()
        for rec in takes:
            audio = load_wav(args.root / rec["wav"])
            hyp = run(audio)
            e = wer(rec["text"], hyp)
            per_style[rec["style"]].append(e)
            worst.append((e, rec["line_id"], rec["style"]))
            pairs.append((rec["text"], hyp))
        decode_s = time.perf_counter() - t0
        overall = float(np.mean([e for v in per_style.values() for e in v]))
        results["engines"][name] = {
            "wer": round(overall, 4),
            "by_style": {k: round(float(np.mean(v)), 4) for k, v in sorted(per_style.items())},
            "worst_lines": [(round(e, 3), lid, st) for e, lid, st in sorted(worst, reverse=True)[:10]],
            "load_s": round(load_s, 2), "decode_s": round(decode_s, 2),
        }
        print(f"{name:28s} WER {overall*100:5.1f}%   " +
              "  ".join(f"{k}:{np.mean(v)*100:4.1f}" for k, v in sorted(per_style.items())) +
              f"   ({decode_s:.1f}s)")
        if overall < best_wer:
            best_name, best_wer, best_pairs = name, overall, pairs
    (args.root / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    corr = mine_corrections(best_pairs)
    lines = ["# dictionary.replacements mined from your voice session, using the best",
             f"# engine ({best_name}). Review, then paste under `dictionary:` in your config.",
             "replacements:"]
    lines += [f'  "{h}": "{r}"' for h, r in corr.items()] or ["  {}"]
    (args.root / "corrections.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nbest: {best_name} ({best_wer*100:.1f}%) · {len(corr)} systematic misses → "
          f"{args.root / 'corrections.yaml'} · details in results.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
