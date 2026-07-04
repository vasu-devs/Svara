# Shipping MyWhisper

## Build the release Svara.exe (what the site links to)

```bat
set MYWHISPER_CPU=1
set MYWHISPER_ONEFILE=1
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean MyWhisper.spec
```

Produces **`dist\Svara.exe`** (~107 MB): a single download-and-run exe with a
branded splash screen. No CUDA bundled — if an NVIDIA GPU is present, the
first-run setup downloads `cuda-runtime.zip` (~1.3 GB) from the GitHub release
on demand. Upload with:

```bat
gh release upload v0.1.0 dist\Svara.exe --clobber
```

## Build the standalone folder app

```bat
build.bat
```

This produces **`dist\MyWhisper\`** — a self-contained folder containing
`MyWhisper.exe` and everything it needs (Python, faster-whisper, CUDA runtime,
the UI). No Python install required on the target machine.

**To ship:** zip the `dist\MyWhisper` folder and send it. The user unzips and
double-clicks `MyWhisper.exe`. On first run it downloads the speech model
(~1.6 GB) into their user cache; after that it runs fully offline.

## What the user gets
- Double-tap **Right Alt** → speak → tap to stop → text at their cursor
- Tray icon with theme / visualizer / background pickers
- No global keyboard hook (poll-only) — safe, never interferes with typing
- `config.yaml` sits next to the exe — fully editable (hotkey, model, look…)

## Notes / expectations
- **Size:** the folder is large (~3–5 GB) because it bundles the CUDA GPU
  runtime. For a small CPU-only build, set `model.device: cpu` in config and
  remove the `nvidia.*` collectors from `MyWhisper.spec` before building.
- **GPU:** the bundled CUDA DLLs need an NVIDIA GPU on the target machine. On
  machines without one, MyWhisper auto-falls back to CPU (slower but works).
- **Autostart:** ship `autostart-enable.bat` alongside, or add a shortcut to the
  user's Startup folder pointing at `MyWhisper.exe`.
- **Antivirus:** unsigned PyInstaller exes can trip SmartScreen. For public
  distribution, sign the exe with a code-signing certificate.

## Optional: single-file installer
For a one-file installer, point a tool like **Inno Setup** at `dist\MyWhisper\`
and have it create a Start-menu shortcut + optional autostart entry.
