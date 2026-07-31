"""config.yaml and DEFAULTS must agree.

`config.yaml` is the documentation people actually read — it is the file the
packaged app drops next to the exe, fully commented. Two ways that goes wrong,
both silent:

- a key documented in `config.yaml` that `DEFAULTS` has never heard of is a
  promise the code does not keep. The user sets it, nothing happens.
- a key in `DEFAULTS` that `config.yaml` never mentions is a feature nobody can
  find.

Neither shows up in any other test, because both configs "work".

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_config_integrity -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mywhisper import config as config_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _flatten(data: dict, path: str = "") -> set[str]:
    out: set[str] = set()
    for key, value in data.items():
        name = f"{path}{key}"
        out.add(name)
        if isinstance(value, dict) and value:
            out |= _flatten(value, name + ".")
    return out


class TestConfigIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shipped = config_mod.load(ROOT / "config.yaml")
        cls.defaults = config_mod.DEFAULTS

    def test_config_yaml_parses(self):
        self.assertIsInstance(self.shipped, dict)
        self.assertIn("model", self.shipped)

    def test_no_documented_key_is_ignored_by_the_code(self):
        # Slot numbers under transforms.slots are user data, not schema.
        ignore_prefixes = ("transforms.slots.",)
        documented = _flatten(self.shipped)
        known = _flatten(self.defaults)
        orphans = sorted(
            k for k in documented - known
            if not k.startswith(ignore_prefixes))
        self.assertFalse(
            orphans,
            "config.yaml documents keys the code never reads — either wire "
            f"them up or delete them: {orphans}")

    def test_every_default_section_is_documented(self):
        documented = _flatten(self.shipped)
        undocumented = sorted(k for k in self.defaults if k not in documented)
        self.assertFalse(
            undocumented,
            "config.py has sections config.yaml never mentions, so users "
            f"cannot discover them: {undocumented}")

    def test_the_three_privacy_gates_default_to_off(self):
        # If any of these ever flips to on-by-default it must be a deliberate,
        # reviewed act — not a merge artifact. PRIVACY.md documents all three.
        self.assertFalse(self.shipped["logging"]["debug_transcripts"])
        self.assertFalse(self.shipped["dictionary"]["auto_learn"])
        self.assertFalse(self.shipped["context"]["read_caret_text"])
        self.assertFalse(self.defaults["logging"]["debug_transcripts"])
        self.assertFalse(self.defaults["dictionary"]["auto_learn"])
        self.assertFalse(self.defaults["context"]["read_caret_text"])

    def test_terminal_newline_default_can_never_submit(self):
        # "space" collapses newlines so a dictated paragraph cannot press Enter
        # at a shell prompt. "literal" is opt-in for people who know.
        self.assertEqual(self.shipped["injection"]["terminal_newline"], "space")
        self.assertEqual(self.defaults["injection"]["terminal_newline"], "space")

    def test_named_strategies_and_policies_actually_exist(self):
        from mywhisper.injection.resolver import _STRATEGIES
        from mywhisper.streaming import POLICIES

        self.assertIn(self.shipped["injection"]["terminal_newline"],
                      ("space", "shift_enter", "literal"))
        self.assertIn(self.shipped["streaming"]["commit_policy"], POLICIES)
        for exe, strategy in (self.shipped["injection"].get("targets")
                              or {}).items():
            self.assertIn(str(strategy).lower(), _STRATEGIES,
                          f"injection.targets[{exe}] names an unknown strategy")

    def test_shipped_transform_slots_load(self):
        from mywhisper.transforms.slots import SlotRegistry

        registry = SlotRegistry(self.shipped["transforms"])
        self.assertIsNotNone(registry.get(1))
        self.assertEqual(registry.get(1).name, "Prompt Engineer")

    def test_english_variant_default_is_a_known_profile(self):
        from mywhisper.pipeline.locale import _PROFILES

        self.assertIn(self.shipped["locale"]["english_variant"], _PROFILES)

    def test_version_is_consistent(self):
        from mywhisper import __version__

        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()


class TestCiDependencies(unittest.TestCase):
    """Twice now a new test has gone red in CI only because it imported a
    package the dev venv happened to have and the runner did not. Both times
    the code was fine and the workflow was wrong, which is the least useful
    kind of red. This checks the pairing locally, before the push."""

    WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"

    # Third-party modules the pure test suite reaches at import time. Anything
    # added here must also appear in the workflow's pip install line.
    REQUIRED = {"yaml": "pyyaml", "pynput": "pynput", "numpy": "numpy",
                "sounddevice": "sounddevice", "tqdm": "tqdm",
                "comtypes": "comtypes"}

    # Imported behind try/except and genuinely optional: the app degrades on
    # purpose without them and the tests mock them, so CI must NOT install
    # them (they are large, and installing them would hide the degrade paths).
    OPTIONAL = {"faster_whisper", "torch", "openai", "ollama", "ctranslate2",
                "customtkinter", "pystray", "PIL", "win32api", "win32con",
                "win32gui", "win32process", "pytest", "setuptools",
                # CUDA detection; absent on a CPU-only machine by definition.
                "nvidia",
                # Injected by PyInstaller into the frozen exe only. It cannot
                # be pip-installed, and importing it from source must fail.
                "pyi_splash",
                # Arrives with faster-whisper and does the first-run model
                # download. Declared in requirements.txt, but CI never needs
                # it: the download tests mock the whole thing.
                "huggingface_hub",
                # The Moonshine engine (model.backend: moonshine|hybrid) —
                # onnxruntime + the tokenizer loader; the registry degrades to
                # faster-whisper without them, and asr tests mock the sessions.
                # moonshine_onnx itself is only probed for its bundled
                # tokenizer asset; the loader is vendored.
                "onnxruntime", "tokenizers", "moonshine_onnx",
                # Meeting mode's WASAPI loopback capture; the tray toggle
                # toasts a pointer when it's missing, and meeting tests drive
                # the chunker/session with synthetic audio.
                "soundcard"}

    def _imports_anywhere(self) -> dict[str, set[str]]:
        """Every module imported under mywhisper/ and tests/, at ANY
        indentation. The previous version of this guard only knew about a
        hand-written list, which is precisely how comtypes stayed undeclared
        while three separate features depended on it."""
        import ast
        found: dict[str, set[str]] = {}
        for folder in ("mywhisper", "tests"):
            for path in (ROOT / folder).rglob("*.py"):
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
                except SyntaxError:
                    continue
                for node in ast.walk(tree):   # walk == nested imports too
                    if isinstance(node, ast.Import):
                        names = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        names = [node.module] if node.module and not node.level else []
                    else:
                        continue
                    for name in names:
                        root = name.split(".")[0]
                        found.setdefault(root, set()).add(
                            str(path.relative_to(ROOT)))
        return found

    def test_no_third_party_import_is_undeclared(self):
        """A new import must be consciously classified as required or
        optional. Silence is what let comtypes ship undeclared: every call
        site caught the ImportError, so the app just quietly lost the Start
        Menu shortcut instead of failing."""
        local = {"mywhisper", "tests"}
        known = set(self.REQUIRED) | self.OPTIONAL | local
        unclassified = {
            mod: sorted(files)[:3]
            for mod, files in self._imports_anywhere().items()
            if mod not in known and mod not in sys.stdlib_module_names
        }
        self.assertFalse(
            unclassified,
            f"undeclared third-party imports: {unclassified}. Add each to "
            "REQUIRED (and to requirements.txt + tests.yml) if the feature "
            "must work, or to OPTIONAL if it degrades on purpose.")

    def test_required_packages_are_in_requirements(self):
        # CI installing it is not enough: users install from requirements.txt.
        text = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
        missing = [p for p in self.REQUIRED.values() if p.lower() not in text]
        self.assertFalse(
            missing,
            f"{missing} missing from requirements.txt — CI would pass while a "
            "fresh user install silently lost the feature")

    def test_workflow_installs_everything_the_suite_imports(self):
        if not self.WORKFLOW.is_file():
            self.skipTest("workflow not present")
        text = self.WORKFLOW.read_text(encoding="utf-8")
        install = [ln for ln in text.splitlines() if "pip install" in ln]
        self.assertTrue(install, "no pip install step found in tests.yml")
        joined = " ".join(install)
        missing = [pkg for pkg in self.REQUIRED.values() if pkg not in joined]
        self.assertFalse(
            missing,
            f"tests.yml does not install {missing} — CI will go red on import "
            "even though the code is fine")

    def test_every_required_package_is_actually_imported_somewhere(self):
        # The mirror: stops the install line growing stale with packages no
        # test needs any more.
        import importlib
        for module in self.REQUIRED:
            try:
                importlib.import_module(module)
            except ImportError:
                self.skipTest(f"{module} not installed locally either")
