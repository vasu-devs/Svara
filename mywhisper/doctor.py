"""`--doctor`: end-to-end environment diagnostics.

Checks Python, audio devices, CUDA DLL visibility, CTranslate2 GPU support,
then checks the configured model from the local cache, without recording audio.
"""

import platform
import logging
import sys
import time


def _ok(msg):
    _report("OK", msg, logging.INFO)


def _warn(msg):
    _report("WARN", msg, logging.WARNING)


def _fail(msg):
    _report("FAIL", msg, logging.ERROR)


def _report(status, msg, level):
    # The release executable has no stdout. Keep diagnostics inspectable in
    # its local log, instead of silently losing every check result.
    if sys.stdout is None:
        logging.getLogger(__name__).log(level, "[%s] %s", status, msg)
    else:
        print(f"  [{status}] {msg}")


def run_doctor(cfg: dict, dll_dirs: list[str]) -> int:
    print("Svara doctor\n" + "=" * 50)
    failures = 0
    device = cfg["model"]["device"]
    resolved_device = device

    # 1. Python / OS
    print(f"\nPython {sys.version.split()[0]} on {platform.platform()}")

    # 2. Audio
    print("\n[1/4] Audio input")
    try:
        import sounddevice as sd

        audio_cfg = cfg["audio"]
        chosen = audio_cfg.get("input_device")
        default_in = sd.query_devices(chosen, kind="input")
        sd.check_input_settings(device=chosen, channels=1, dtype="float32",
                                samplerate=audio_cfg["sample_rate"])
        _ok(f"configured microphone: {default_in['name']} (16 kHz mono supported)")
    except Exception as e:  # noqa: BLE001
        _fail(f"no usable microphone: {e}")
        failures += 1

    # 3. CUDA DLLs + CTranslate2
    print("\n[2/4] CUDA runtime (pip-installed cuBLAS/cuDNN)")
    if dll_dirs:
        for d in dll_dirs:
            _ok(f"DLL dir registered: {d}")
    elif device == "cpu":
        _ok("CPU mode — CUDA runtime is optional")
    else:
        _warn("no nvidia DLL dirs found in site-packages "
              "(fine if using a system CUDA install)")

    print("\n[3/4] CTranslate2 GPU support")
    try:
        import ctranslate2

        _ok(f"ctranslate2 {ctranslate2.__version__}")
        try:
            n = ctranslate2.get_cuda_device_count()
        except Exception:
            if device == "cuda":
                raise
            n = 0
        if device == "auto":
            resolved_device = "cuda" if n > 0 else "cpu"
        if n > 0:
            _ok(f"CUDA devices visible: {n}")
            try:
                types = ctranslate2.get_supported_compute_types("cuda")
                _ok(f"supported GPU compute types: {sorted(types)}")
            except Exception as e:  # noqa: BLE001
                _warn(f"could not query compute types: {e}")
        elif device == "cuda":
            _fail("no CUDA device visible to CTranslate2")
            failures += 1
        else:
            _ok("No CUDA device — CPU dictation is supported")
    except Exception as e:  # noqa: BLE001
        _fail(f"ctranslate2 import failed: {e}")
        failures += 1

    # 4. Real model load + synthetic transcribe on the configured device
    name = cfg["model"]["name"]
    print(f"\n[4/4] Model smoke test ({name}, local cache only)")
    try:
        import numpy as np
        from faster_whisper import WhisperModel

        compute = cfg["model"]["compute_type"] if resolved_device != "cpu" else "int8"
        t0 = time.perf_counter()
        model = WhisperModel(name, device=resolved_device, compute_type=compute,
                             download_root=cfg["model"].get("download_root"),
                             local_files_only=True)
        load_s = time.perf_counter() - t0

        # 2 s of quiet noise — verifies the full encoder/decoder + cuDNN path.
        rng = np.random.default_rng(0)
        audio = (rng.standard_normal(32000) * 0.001).astype(np.float32)
        t0 = time.perf_counter()
        segs, _ = model.transcribe(audio, beam_size=1, language="en")
        list(segs)
        run_s = time.perf_counter() - t0
        _ok(f"{name} on {resolved_device} ({compute}): load {load_s:.1f}s, "
            f"2s-audio transcribe {run_s:.2f}s")
    except Exception as e:  # noqa: BLE001
        _fail(f"model smoke test failed: {e}")
        _warn("If weights are missing, open Svara setup online to download the selected model once. Diagnostics never download models.")
        failures += 1

    print("\n" + "=" * 50)
    if failures == 0:
        print("All checks passed — run `python -m mywhisper --test 5` "
              "to do a live microphone test.")
    else:
        print(f"{failures} check(s) failed — see above.")
    return failures
