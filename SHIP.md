# Shipping Svara

## Pre-flight

Run these before every release. Each one has caught something real.

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -q   :: 547 tests at v0.7.0
run.bat --bench                                             :: exit 0/2/3
cd web && npm run build                                     :: the site compiles
```

- **The suite must be fully green**, including `test_redact` (no dictated text
  reaches the log), `test_config_integrity` (config.yaml and DEFAULTS agree, the
  three privacy gates default off) and `test_upgrade` (a v0.4 config still gets
  every 0.5 feature).
- **`--bench` exits `2`** on the CPU default today — that is the known latency
  gap in [`BENCH.md`](BENCH.md), not a regression. Exit `3` means it measured
  nothing and something is wrong.
- **Bump `mywhisper/__init__.py`'s `__version__`.** The setup-done flag embeds
  it, so a bump correctly re-runs first-run setup on the new binary.

## Build the release Svara.exe (what the site links to)

```bat
set MYWHISPER_CPU=1
set MYWHISPER_ONEFILE=1
set PYTHONNOUSERSITE=1
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean MyWhisper.spec
```

Produces **`dist\Svara.exe`** (~111 MB at v0.7.0): a single download-and-run exe with a
branded splash screen. No CUDA bundled — if an NVIDIA GPU is present, the
first-run setup downloads `cuda-runtime.zip` (~1.3 GB) from the GitHub release
on demand.

Then **smoke-test the binary you are about to publish** — not the source tree:

```bat
cd dist && Svara.exe --portable --no-tray
:: wait ~30s, then read dist\logs\mywhisper.log and Ctrl-C / kill it
```

Look for `Model ready`, `Hotkey armed`, `quick shortcuts armed` and no
`SVARA-` error codes. `--portable --no-tray` skips self-install and the setup
window, so this leaves nothing behind (delete `dist\logs`, `dist\config*.yaml`
and `dist\state.json` afterwards).

If another installed instance is already running, leave it undisturbed. Run
`Svara.exe --portable --doctor --cpu` to verify the packaged runtime and cached
model without taking the microphone or hotkeys; inspect `logs\mywhisper.log` and
its exit code. Record that interactive packaged dictation was not retested.

## Publish

**Rename to the version first.** Re-uploading to a URL that already exists —
which `--clobber` does — is a caching landmine: browsers and CDN edges can keep
serving the old binary from that URL indefinitely, so a user's "fresh download"
is silently stale. A new version number is a genuinely new URL.

```bat
copy dist\Svara.exe dist\Svara-0.7.0.exe
git tag -a v0.7.0 -m "Svara v0.7.0"
git push origin v0.7.0
gh release create v0.7.0 dist\Svara-0.7.0.exe dist\SHA256SUMS.txt --verify-tag --draft --title "Svara v0.7.0" --notes-file releases\v0.7.0.md
gh release edit v0.7.0 --draft=false --latest
git push origin main
```

Use a fresh version tag for each release. Before these commands, update the
source/site version and size, prepare the notes and SHA-256 checksum, and commit
all release changes. Verify the draft's uploaded assets before publishing it.
The tag push makes the exact commit available without deploying the main-branch site.

**Publish the asset BEFORE pushing main.** The site's download button and the
in-app auto-updater both start looking the moment the new code is live; if the
asset is not there yet they 404 for real users.

The site's `DOWNLOAD` in [`web/app/page.tsx`](web/app/page.tsx) derives its tagged
URL from `VERSION`. Check the Tests and Pages workflows after pushing main and
verify the public site and download. Keep the existing v0.1.0 CUDA runtime asset:
the optional GPU installer still uses its stable URL.

**The auto-updater** polls `releases/latest` and picks the highest-versioned
`Svara-*.exe` asset. It downloads quietly and applies only when the user clicks
"Restart to update" in the tray, carrying the setup-done flag so nobody is
re-onboarded by an upgrade.

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
- **Self-installing (v0.3.0+):** double-clicking the downloaded exe installs to
  `%LOCALAPPDATA%\Svara`, registers **start-with-Windows** (HKCU Run) + a Start
  Menu entry, migrates any config/state/CUDA runtime sitting next to the old
  exe, and relaunches from the installed copy. The download is disposable.
  `--portable` skips all of it.
- Double-tap **Right Alt** → speak → tap to stop → text at their cursor
- Tray icon with theme / visualizer / background pickers, dictionary editor,
  Start-with-Windows toggle
- No global keyboard hook (poll-only) — safe, never interferes with typing
- `config.yaml` lives in `%LOCALAPPDATA%\Svara` — fully editable (hotkey,
  model, personal dictionary, look…)

## Notes / expectations
- **Size:** the folder is large (~3–5 GB) because it bundles the CUDA GPU
  runtime. For a small CPU-only build, set `model.device: cpu` in config and
  remove the `nvidia.*` collectors from `MyWhisper.spec` before building.
- **GPU:** the bundled CUDA DLLs need an NVIDIA GPU on the target machine. On
  machines without one, MyWhisper auto-falls back to CPU (slower but works).
- **Autostart:** automatic since v0.3.0 (the exe registers itself; toggle in
  the tray). `autostart-enable.bat` remains only for the folder build.
- **Antivirus:** unsigned PyInstaller exes can trip SmartScreen. For public
  distribution, sign the exe with a code-signing certificate.

## Optional: single-file installer
For a one-file installer, point a tool like **Inno Setup** at `dist\MyWhisper\`
and have it create a Start-menu shortcut + optional autostart entry.
