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
