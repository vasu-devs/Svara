"""Explicit, bounded voice syntax; produces text, never executes a command."""
import re

from .base import BaseStage, UtteranceContext
from .corrections import outside_literals

_NAME = re.compile(
    r"\b(camel case|snake case|pascal case|kebab case|constant case)\s+"
    r"([A-Za-z0-9]+(?:[ \t]+[A-Za-z0-9]+){0,15}?)\s+end name\b", re.I)
_FILE = re.compile(r"\bfile name\s+([A-Za-z0-9 ]{1,160}?)\s+end file\b", re.I)
_SYMBOLS = {"dot": ".", "slash": "/", "underscore": "_", "dash": "-"}


def developer_syntax(text: str) -> str:
    def name(match):
        style = match[1].lower()
        words = match[2].lower().split()
        if words[0][0].isdigit():
            return match[0]  # not a valid identifier
        if style == "camel case":
            return words[0] + "".join(w.capitalize() for w in words[1:])
        if style == "pascal case":
            return "".join(w.capitalize() for w in words)
        if style == "snake case":
            return "_".join(words)
        if style == "constant case":
            return "_".join(words).upper()
        return "-".join(words)

    def filename(match):
        parts = match[1].split()
        # Spaces are joined only through an explicit separator; don't guess
        # whether "my file" means myFile, my_file or a filename with a space.
        out, previous_word = "", False
        for part in parts:
            symbol = _SYMBOLS.get(part.lower())
            if symbol is not None:
                out += symbol
                previous_word = False
            else:
                if previous_word:
                    return match[0]
                out += part
                previous_word = True
        if not out or out.endswith(("/", ".", "_", "-")) or ".." in out:
            return match[0]
        return out

    return outside_literals(text, lambda part: _FILE.sub(filename, _NAME.sub(name, part)))


class DeveloperStage(BaseStage):
    name = "developer_syntax"
    min_level = 1

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def applies(self, ctx: UtteranceContext) -> bool:
        return self.enabled and ctx.source != "command"

    def run(self, text: str, ctx: UtteranceContext) -> str:
        return developer_syntax(text)
