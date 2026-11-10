# Local development and validation

Do not launch Svara, its overlays/settings/tray, or interactive desktop tests as
routine validation. Do not simulate global hotkeys: they can activate the user's
already-running copy of Svara. Only run those checks if the user explicitly asks
for interactive testing.

Use targeted headless tests. Do not run blanket `unittest discover` during an
interactive user session: some test modules create Tk windows at import time,
and others exercise real global keyboard input.

For transcript cleanup work, this is a headless verification command:

```powershell
.venv/Scripts/python.exe -m unittest tests.test_cleanup tests.test_pipeline tests.test_corrections tests.test_flow_features tests.test_llm_backend tests.test_config_integrity tests.test_redact -q
```

On Linux the same suites run with `.venv/bin/python -m unittest …`, plus
`tests.test_linux_desktop` for the Hyprland hotkey transport and the uinput
typist (see `LINUX.md`). Windows-only suites (`test_install`,
`test_hotkey_gesture`, `test_hotkey_real_keys`) fail there by design.

For vocabulary/history changes, `tests.test_libraries` and
`tests.test_history_insights` are also headless and use temporary fixtures.

Preserve unrelated in-progress work, particularly website changes. Do not
terminate or restart the user's installed app to validate source changes.
