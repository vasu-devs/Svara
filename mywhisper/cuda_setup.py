"""Expose pip-installed NVIDIA runtime DLLs (cuBLAS / cuDNN) to CTranslate2 on Windows.

The nvidia-* pip wheels place their DLLs under ``<site-packages>/nvidia/<pkg>/bin``,
which is NOT on the Windows DLL search path. CTranslate2 (the engine behind
faster-whisper) needs cublas64_12.dll and cudnn64_9.dll at runtime, so we register
those directories BEFORE faster_whisper / ctranslate2 are imported.

Call :func:`setup` as the very first thing in the program entry point.
"""

import os
import sys
import sysconfig
from pathlib import Path

# The CUDA runtime (cuBLAS/cuDNN/nvRTC) as a downloadable asset. Fetched once,
# on demand, when an NVIDIA GPU is present and the DLLs aren't already here.
CUDA_URL = "https://github.com/vasu-devs/Svara/releases/download/v0.1.0/cuda-runtime.zip"


def local_cuda_root() -> Path:
    """Where an on-demand CUDA runtime is extracted (next to the exe)."""
    from .paths import base_dir
    return base_dir() / "cuda"


def gpu_present() -> bool:
    """True if an NVIDIA GPU + driver is installed (the CUDA driver DLL loads)."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        ctypes.WinDLL("nvcuda.dll")
        return True
    except Exception:  # noqa: BLE001
        return False


def cuda_available() -> bool:
    """True if the CUDA runtime DLLs are present (bundled or downloaded)."""
    cands = [local_cuda_root() / "nvidia" / "cublas" / "bin"]
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        cands.append(base / "nvidia" / "cublas" / "bin")
    return any((d / "cublas64_12.dll").exists() for d in cands)


def download_cuda(progress=None) -> bool:
    """Download + extract the CUDA runtime next to the exe. progress(done,total).
    Returns True on success. Safe to call again if it fails partway."""
    import urllib.request
    import zipfile

    dest = local_cuda_root()
    try:
        dest.mkdir(parents=True, exist_ok=True)
        tmp = dest / "_cuda_download.part"
        req = urllib.request.Request(CUDA_URL, headers={"User-Agent": "Svara"})
        with urllib.request.urlopen(req) as r:  # noqa: S310 — trusted GitHub URL
            total = int(r.headers.get("Content-Length", 0))
            done = 0
            with open(tmp, "wb") as f:
                while True:
                    chunk = r.read(1 << 18)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        with zipfile.ZipFile(tmp) as z:
            z.extractall(dest)
        try:
            tmp.unlink()
        except OSError:
            pass
        return cuda_available()
    except Exception:  # noqa: BLE001
        return False


def setup() -> list[str]:
    """Register every nvidia/*/bin and nvidia/*/lib dir containing DLLs.

    Returns the list of directories that were added (for diagnostics).
    """
    if os.name != "nt":
        return []

    roots: set[Path] = set()
    # Frozen (PyInstaller) build: DLLs live under the bundle root.
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        roots.add(base / "nvidia")
        roots.add(base)  # some collectors flatten DLLs to the root
    # CUDA runtime downloaded on demand (next to the exe)
    try:
        roots.add(local_cuda_root() / "nvidia")
    except Exception:  # noqa: BLE001
        pass
    for key in ("purelib", "platlib"):
        p = sysconfig.get_paths().get(key)
        if p:
            roots.add(Path(p) / "nvidia")
    try:
        import nvidia  # namespace package created by the nvidia-* wheels

        roots.update(Path(p) for p in nvidia.__path__)
    except ImportError:
        pass

    added: list[str] = []
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for sub in sorted(root.iterdir()):
            if not sub.is_dir():
                continue
            for leaf in ("bin", "lib"):
                d = sub / leaf
                if str(d) in seen or not d.is_dir():
                    continue
                seen.add(str(d))
                try:
                    if not any(f.suffix.lower() == ".dll" for f in d.iterdir()):
                        continue
                except OSError:
                    continue
                try:
                    os.add_dll_directory(str(d))
                except (OSError, AttributeError):
                    pass
                # Older loaders / lazy LoadLibrary calls also search PATH.
                os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
                added.append(str(d))
    return added
