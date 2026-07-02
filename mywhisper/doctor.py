"""`--doctor`: end-to-end environment diagnostics.

Checks Python, audio devices, CUDA DLL visibility, CTranslate2 GPU support,
then loads a tiny model and times a synthetic transcription on the GPU.
"""

import platform
import sys
import time


def _ok(msg):
    print(f"  [OK]   {msg}")


def _warn(msg):
    print(f"  [WARN] {msg}")


def _fail(msg):
    print(f"  [FAIL] {msg}")


def run_doctor(cfg: dict, dll_dirs: list[str]) -> int:
    print("MyWhisper doctor\n" + "=" * 50)
    failures = 0

    # 1. Python / OS
    print(f"\nPython {sys.version.split()[0]} on {platform.platform()}")

    # 2. Audio
    print("\n[1/4] Audio input")
    try:
        import sounddevice as sd

        default_in = sd.query_devices(kind="input")
        _ok(f"default microphone: {default_in['name']}")
    except Exception as e:  # noqa: BLE001
        _fail(f"no usable microphone: {e}")
        failures += 1

    # 3. CUDA DLLs + CTranslate2
    print("\n[2/4] CUDA runtime (pip-installed cuBLAS/cuDNN)")
    if dll_dirs:
        for d in dll_dirs:
            _ok(f"DLL dir registered: {d}")
    else:
        _warn("no nvidia DLL dirs found in site-packages "
              "(fine if using a system CUDA install)")

    print("\n[3/4] CTranslate2 GPU support")
    try:
        import ctranslate2

        _ok(f"ctranslate2 {ctranslate2.__version__}")
        n = ctranslate2.get_cuda_device_count()
        if n > 0:
            _ok(f"CUDA devices visible: {n}")
            try:
                types = ctranslate2.get_supported_compute_types("cuda")
                _ok(f"supported GPU compute types: {sorted(types)}")
            except Exception as e:  # noqa: BLE001
                _warn(f"could not query compute types: {e}")
        else:
            _fail("no CUDA device visible to CTranslate2")
            failures += 1
    except Exception as e:  # noqa: BLE001
        _fail(f"ctranslate2 import failed: {e}")
        failures += 1

    # 4. Real model load + synthetic transcribe on the configured device
    print("\n[4/4] Model smoke test (tiny)")
    try:
        import numpy as np
        from faster_whisper import WhisperModel

        device = cfg["model"]["device"]
        compute = cfg["model"]["compute_type"] if device != "cpu" else "int8"
        t0 = time.perf_counter()
        model = WhisperModel("tiny", device=device, compute_type=compute)
        load_s = time.perf_counter() - t0

        # 2 s of quiet noise — verifies the full encoder/decoder + cuDNN path.
        rng = np.random.default_rng(0)
        audio = (rng.standard_normal(32000) * 0.001).astype(np.float32)
        t0 = time.perf_counter()
        segs, _ = model.transcribe(audio, beam_size=1, language="en")
        list(segs)
        run_s = time.perf_counter() - t0
        _ok(f"tiny model on {device} ({compute}): load {load_s:.1f}s, "
            f"2s-audio transcribe {run_s:.2f}s")
    except Exception as e:  # noqa: BLE001
        _fail(f"model smoke test failed: {e}")
        failures += 1

    print("\n" + "=" * 50)
    if failures == 0:
        print("All checks passed — run `python -m mywhisper --test 5` "
              "to do a live microphone test.")
    else:
        print(f"{failures} check(s) failed — see above.")
    return failures
