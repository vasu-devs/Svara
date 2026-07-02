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
