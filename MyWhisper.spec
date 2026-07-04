# PyInstaller spec for MyWhisper — build with:  build.bat
# Produces dist\MyWhisper\MyWhisper.exe (a folder you can zip and ship).
import os
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

# MYWHISPER_CPU=1 → lean CPU-only build: skip the ~1.9 GB CUDA runtime.
CPU_ONLY = os.environ.get("MYWHISPER_CPU") == "1"
# MYWHISPER_ONEFILE=1 → a single download-and-run Svara.exe; else a folder build.
ONEFILE = os.environ.get("MYWHISPER_ONEFILE") == "1"
APP_NAME = "Svara" if ONEFILE else "MyWhisper"

datas, binaries, hiddenimports = [], [], []

# Collect everything (code + data + DLLs) for the tricky packages.
for pkg in ("faster_whisper", "ctranslate2", "av", "sounddevice",
            "pystray", "PIL", "comtypes", "yaml", "pynput", "customtkinter"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# NVIDIA CUDA runtime DLLs (cuBLAS / cuDNN / nvrtc) → bundle under nvidia\<pkg>\bin.
# Skipped for the lean CPU build (this is the ~1.9 GB that dominates the download).
if not CPU_ONLY:
    for pkg in ("nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_nvrtc",
                "nvidia.cuda_runtime"):
        try:
            binaries += collect_dynamic_libs(pkg, destdir=os.path.join(
                "nvidia", pkg.split(".")[1], "bin"))
        except Exception:
            pass

# Ship a default config next to the exe (users can edit it) + the app icon.
datas += [("config.yaml", "."), ("assets/icon.ico", "assets"),
          ("assets/icon.png", "assets")]

hiddenimports += ["comtypes.gen", "mywhisper", "mywhisper.paths",
                  "mywhisper.setup_ui", "tkinter", "tkinter.ttk", "customtkinter"]

a = Analysis(
    ["app_entry.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter.test", "test", "unittest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

_icon = "assets\\icon.ico" if os.path.exists("assets\\icon.ico") else None

if ONEFILE:
    # Single self-contained Svara.exe: download and double-click, no unzip.
    # The splash shows the moment the exe is double-clicked — the 100+ MB
    # onefile extraction plus model load would otherwise be a silent minute.
    splash = Splash(
        "assets/splash.png",
        binaries=a.binaries,
        datas=a.datas,
        text_pos=(38, 252),
        text_size=10,
        text_color="#9a9aa4",
        text_default="starting…",
        always_on_top=True,
    )
    exe = EXE(
        pyz, a.scripts, splash, splash.binaries, a.binaries, a.datas, [],
        name=APP_NAME, console=False,
        disable_windowed_traceback=False, icon=_icon,
    )
else:
    exe = EXE(
        pyz, a.scripts, [], exclude_binaries=True,
        name=APP_NAME, console=False,   # windowed — no console popup
        disable_windowed_traceback=False, icon=_icon,
    )
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=APP_NAME)
