"""Opt-in punctuation/casing presets; no model and no vocabulary rewrite."""
import re

from .base import BaseStage, UtteranceContext
from .corrections import outside_literals

STYLES = {"auto", "formal", "casual", "very_casual", "excited"}


class WritingStyleStage(BaseStage):
    name = "writing_style"
    min_level = 1

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def style_for(self, ctx: UtteranceContext) -> str:
        overrides = self.cfg.get("formatting_styles") or {}
        if not isinstance(overrides, dict):
            overrides = {}
        overrides = {str(k).lower(): v for k, v in overrides.items()}
        category = "chat" if ctx.is_chat else "default"
        chosen = overrides.get(ctx.app.lower(), overrides.get(category,
                               self.cfg.get("writing_style", "auto")))
        return chosen if isinstance(chosen, str) and chosen in STYLES else "auto"

    def applies(self, ctx: UtteranceContext) -> bool:
        return (not ctx.is_terminal and ctx.source != "command"
                and ctx.locale.lower().startswith("en") and self.style_for(ctx) != "auto")

    def run(self, text: str, ctx: UtteranceContext) -> str:
        style = self.style_for(ctx)
        if style == "very_casual":
            text = outside_literals(text, str.lower)
        elif text and text[0].islower() and not re.match(r"https?://|\S+@\S+", text):
            text = text[0].upper() + text[1:]
        # URLs, code, quotes, lists and code-like tokens keep their endings.
        protected_end = bool(re.search(r"(?:https?://\S+|\S+@\S+|[`\"”'])$", text))
        if protected_end or "\n" in text:
            return text
        if style in {"casual", "very_casual"}:
            if text.endswith(".") and not text.endswith(".."):
                return text[:-1]
        elif style in {"formal", "excited"}:
            mark = "!" if style == "excited" else "."
            if style == "excited" and text.endswith(".") and not text.endswith(".."):
                return text[:-1] + mark
            if text and text[-1].isalnum() and not text.isnumeric():
                return text + mark
        return text
