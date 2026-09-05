# Svara reliability and experience audit

Date: 2026-09-05. Scope: source checkout, desktop dictation lifecycle, settings,
visual rendering, website interactions, dependency health, and both website builds.

## Findings and changes

| Finding | Effect | Change |
| --- | --- | --- |
| No project virtual environment; system Python lacked required packages | The documented source launcher could not run | Created `.venv` and installed the speech, audio, UI, and test dependencies. `setup.bat` now exits on installation errors instead of printing success. |
| YAML syntax validation accepted unusable setting types and ranges | Null sections, zero sample rates, or quoted privacy booleans could crash startup or behave incorrectly | Validate schema-shaped fields and operational bounds; retain valid preferences and restore only invalid fields to defaults. Preserve automatic language detection. |
| Final transcription used the mutable current-app context | A later recording could change the earlier recording's formatting/injection policy | Carry the captured context with each recording; prevent another dictation from starting while finalization is pending. |
| Stream commits and finalization were not synchronized | A last partial could be typed without matching final-tail bookkeeping | Serialize commit bookkeeping with stop/cancel, recheck the active session, and snapshot committed words. |
| Delayed stop timers survived cancellation | An old timer could terminate a subsequent recording | Cancel timers, associate finalization with its recording, and cancel pending timers during shutdown. |
| Missing microphone still allowed a listening/locked overlay | The app looked ready while capturing nothing | Check microphone availability before starting; explain the problem while background recovery continues. |
| Failed microphone starts/retries leaked stream handles | Recovery could leave devices allocated and progressively fail | Close failed candidates and release the stream even if stopping raises. Terminate the spill writer on shutdown. |
| Preview transcripts were discarded by a no-op overlay method | Preview mode consumed recognition work without showing words | Queue partial transcripts to the overlay; expand it into a bounded rolling caption and clear captions when hidden. Include the fallback renderer. |
| Silence left obsolete recovery audio | Empty recordings could be offered for recovery later | Discard recovery data after empty recordings or successful no-speech results. |
| Doctor treated missing CUDA as failure on CPU machines and fetched a different model | Healthy CPU setups appeared broken; offline diagnosis was unreliable | Validate the configured mic's format and configured cached model. No implicit downloads; absent CUDA is acceptable in CPU/auto mode. |
| Windowed executable discarded diagnostic output and return codes | Packaged checks could fail silently and still exit successfully | Log doctor results when no console exists; preserve diagnostic exit codes through the executable supervisor. |
| Settings used a global mouse-wheel binding | Settings could steal scrolling from History/Scratchpad | Scope wheel handling to the settings window. |
| Tk variables implicitly used the first-created interpreter | Dropdowns could display a new choice while reading the old value, depending on window creation order | Bind settings, history search, dictionary, and startup variables explicitly to their owning widgets; add a regression using a second interpreter. |
| Appearance options were scattered across tray controls | Waveform and background choices were hard to discover | Add an Appearance section with palettes, backgrounds, ten visualizers, and persisted reduced-motion control. |
| Existing animations did not fully honor reduced motion | Canvas motion continued despite the OS preference | Static reduced-motion rendering; suspend website canvases when hidden/offscreen; clean up RAFs, observers, and drag timers. |
| Website suggested its simulated signal was real microphone input | The demo could misrepresent its capabilities | Label it as a preview; add explicit scripted speech-to-text examples with play, pause, resume, replay, and progress. |
| Next.js 14.2.15 was obsolete and vulnerable | Server deployments inherited published security findings | Upgrade to Next.js 16.3.4 and React 19.2.8; update types and lockfile. npm audit reported zero vulnerabilities after upgrade. |
| Static pages still requested the visitor API; metadata ignored the base path | Avoidable failed requests and incorrect asset paths on GitHub Pages | Add build-time static/base-path flags, skip the API on static builds, and prefix metadata assets. |
| CI did not build the website for pull requests | Site/framework regressions could reach deployment | Add a server/static build matrix and expand workflow path coverage. |
| Autostart test cleanup restored its mocks before deleting the fixture | The test could delete the real user's startup registration | Clean up while the isolated application name and directory are still patched. |

The Next.js upgrade follows the framework's [security guidance](https://nextjs.org/blog/security-update-2025-12-11);
the final installed versions and audit outcome were verified with npm locally.

## New visual features

- **Orbit:** three elliptical trails with sound-reactive satellites.
- **Ribbon:** layered flowing ribbons driven by microphone level.
- **Preview captions:** a two-line rolling transcript beneath the waveform in preview mode.
- **Appearance settings:** live theme, waveform, background, and reduced-motion controls.
- **Website rehearsal:** filler cleanup, personal dictionary, and terminal-friendly examples.

## Verification

- Release full Windows run: **547 tests passed in 69.9 seconds**, including real Right Alt gestures,
  isolated autostart registration, desktop UI tests, and real faster-whisper
  streaming over synthetic speech. No skip in that run.
- Included rendering regressions exercise Orbit/Ribbon at three scales,
  static reduced-motion frames, and English/CJK/French preview captions.
- Hardware doctor: connected EarPods input supports 16 kHz mono; one CUDA device
  visible; cached `base.en` on CPU loaded in about 0.7 seconds and decoded two
  seconds of synthetic quiet audio in about 0.42 seconds. This is a runtime
  smoke test, not a recognition-accuracy or streaming-latency benchmark.
- Production server build and `/Svara` GitHub Pages static export both pass.
  The server build includes `/api/visits`; the static build excludes it.
- Browser: preview completion, pause/resume controls, terminal newline collapse,
  desktop and 390-pixel mobile layouts. No horizontal mobile overflow or browser
  console errors observed during the checks.
- `git diff --check` passes. Test/build logs are in the ignored `logs/` folder.

## Limits and follow-up work

This is a substantial repair and improvement pass, not a guarantee that every
combination of audio hardware, target application, language, and optional model
has been covered.

- Built the CPU-first v0.7.0 one-file executable (111,261,321 bytes). Its own
  portable doctor exited zero, validated the microphone, loaded cached `base.en`
  in 0.5 seconds and decoded synthetic quiet audio in 0.38 seconds. The existing
  installed app was left running; interactive packaged dictation was not retested.
- The pre-release CPU benchmark measured 648 ms first-word latency, 782 ms
  partial p95, RTF 0.116 and 8.33% WER on three bundled clips. It exits 2 because
  the existing CPU latency targets remain unmet. This is not a claim of improved
  recognition speed. The result records the base commit of the uncommitted
  release worktree and ran alongside packaging.
- User-specific dictation problems in an already-installed release need its
  own version/configuration and a concrete reproduction; this checkout's doctor
  and real-model integration test pass.
- Overlapping dictations are deliberately serialized until processing completes.
  A fully concurrent queue would need independent model prompts, recovery files,
  history metadata, and target-focus ownership for every utterance.
- Formatting context is captured per recording; it does not force another app
  to regain focus. Broader focus-change handling needs dedicated end-to-end
  checks against real target applications.
- Meeting capture, optional local-LLM quality, all multilingual models, and GPU
  throughput were not benchmarked during this pass.
- Preview captions show a bounded tail, not a scrollable transcript. History
  remains the place for completed dictations.
- Website fonts require an initial network-enabled build. The generated site
  serves those fonts locally afterwards.

## Run the improved source

```bat
run.bat --doctor
run.bat --portable
```

Open Settings → Appearance for the new visualizers. Choose “Show in the pill,
type at the end” under Speech for preview captions. For the website, run
`npm ci` and `npm run dev` from `web/` using Node.js 20.9 or newer.
