"""Language-specific typography — the rules a native reader notices immediately.

Three families, all rules-based: no model, no latency, no network.

**French.** French typography puts a space before "high" punctuation. Not any
space — a *non-breaking* one, or the line wraps and leaves a lonely `?` at the
start of the next line. Following the Imprimerie nationale convention (which is
also what Word and LibreOffice do for French):

- `espace fine insécable` U+202F before `;` `!` `?` and before `»`
- `espace mots insécable` U+00A0 before `:` — the colon is the standard
  exception and takes a full non-breaking space
- U+202F after `«`

**CJK.** Chinese/Japanese/Korean full-width punctuation carries its own
sidebearing. Whisper often emits a Latin-style space around it, which reads to a
native eye like double-spacing does in English. Strip it.

**English variants.** en-US / en-GB / en-CA differ in ways spell-check will
flag in the reader's editor. Configured explicitly rather than auto-detected,
because a dictation tool guessing your dialect mid-paragraph is worse than one
that never tries.

Two suppression rules matter more than any of the above, and both have tests:

1. **Never in a terminal.** An invisible U+202F inside a shell command produces
   an error message that names a character the user cannot see. `is_terminal`
   turns the whole stage off.
2. **Never inside a time, ratio, URL, or code span.** `12:30` must not become
   `12 :30`, and `http://x` must not gain a space before its colon.
"""

import re

from .base import BaseStage, UtteranceContext

NNBSP = " "   # narrow no-break space
NBSP = " "    # no-break space


# --------------------------------------------------------------------------
# French
# --------------------------------------------------------------------------

# A colon preceded by a digit and followed by a digit is a time or a ratio.
# A colon preceded by a scheme-ish word and followed by "//" is a URL.
_FR_PROTECT = re.compile(r"(\d\s*:\s*\d|\b[a-z][a-z0-9+.\-]*://\S*|`[^`]*`)")
_FR_HIGH = re.compile(r"[   ]*([;!?»])")
_FR_COLON = re.compile(r"[   ]*(:)")
_FR_OPEN = re.compile(r"(«)[   ]*")


def french_spacing(text: str) -> str:
    """Insert French non-breaking spaces, skipping protected spans."""
    parts = _FR_PROTECT.split(text)
    out = []
    for i, part in enumerate(parts):
        if i % 2:            # the captured protected span — leave it alone
            out.append(part)
            continue
        part = _FR_HIGH.sub(NNBSP + r"\1", part)
        part = _FR_COLON.sub(NBSP + r"\1", part)
        part = _FR_OPEN.sub(r"\1" + NNBSP, part)
        out.append(part)
    return "".join(out)


# --------------------------------------------------------------------------
# CJK
# --------------------------------------------------------------------------

_CJK_PUNCT = "。！？、，：；（）〈〉《》「」『』【】〔〕・…—～"
_CJK_RANGE = (
    r"぀-ヿ"      # kana
    r"㐀-䶿"      # CJK ext A
    r"一-鿿"      # CJK unified
    r"가-힯"      # hangul
    r"＀-￯"      # full-width forms
)
_CJK_SPACE_AROUND_PUNCT = re.compile(rf"\s*([{re.escape(_CJK_PUNCT)}])\s*")
_CJK_INTERCHAR = re.compile(rf"([{_CJK_RANGE}]) +(?=[{_CJK_RANGE}])")


def cjk_spacing(text: str) -> str:
    """Remove Latin-style spacing around full-width punctuation and between
    adjacent CJK characters. Spaces between CJK and Latin are *kept* — that
    one is genuinely correct and removing it is the classic over-correction."""
    text = _CJK_SPACE_AROUND_PUNCT.sub(r"\1", text)
    text = _CJK_INTERCHAR.sub(r"\1", text)
    return text


# --------------------------------------------------------------------------
# English variants
# --------------------------------------------------------------------------

# Finite, curated pairs (us → gb). Suffixes are matched from a closed set so
# "color" can never fire inside "Colorado".
_SUFFIX = r"(?:s|es|ed|ing|er|ers|est|ful|fully|less|ly|ist|ists|ism|ation|ations|able|ably|ous|ously)?"

_OUR = {
    "color": "colour", "honor": "honour", "favor": "favour",
    "flavor": "flavour", "humor": "humour", "labor": "labour",
    "neighbor": "neighbour", "rumor": "rumour", "savor": "savour",
    "vapor": "vapour", "behavior": "behaviour", "endeavor": "endeavour",
    "harbor": "harbour", "armor": "armour", "ardor": "ardour",
    "candor": "candour", "clamor": "clamour", "splendor": "splendour",
    "valor": "valour", "vigor": "vigour", "odor": "odour",
    "parlor": "parlour", "rigor": "rigour", "tumor": "tumour",
    "demeanor": "demeanour", "fervor": "fervour", "rancor": "rancour",
}
_RE = {
    "center": "centre", "theater": "theatre", "meter": "metre",
    "liter": "litre", "fiber": "fibre", "caliber": "calibre",
    "somber": "sombre", "specter": "spectre", "luster": "lustre",
    "saber": "sabre", "scepter": "sceptre", "sepulcher": "sepulchre",
}
_ENCE = {
    "defense": "defence", "offense": "offence", "pretense": "pretence",
}
_OGUE = {
    "catalog": "catalogue", "dialog": "dialogue", "analog": "analogue",
    "monolog": "monologue", "epilog": "epilogue", "prolog": "prologue",
}
# Consonant doubling before a suffix. Explicit forms — the underlying rule
# ("double the l when the final syllable is unstressed") is not mechanisable.
_LL = {
    "traveled": "travelled", "traveling": "travelling",
    "traveler": "traveller", "travelers": "travellers",
    "canceled": "cancelled", "canceling": "cancelling",
    "modeled": "modelled", "modeling": "modelling",
    "labeled": "labelled", "labeling": "labelling",
    "fueled": "fuelled", "fueling": "fuelling",
    "signaled": "signalled", "signaling": "signalling",
    "totaled": "totalled", "totaling": "totalling",
    "counselor": "counsellor", "counselors": "counsellors",
    "jeweler": "jeweller", "jewelers": "jewellers",
    "marvelous": "marvellous", "marveled": "marvelled",
    "quarreled": "quarrelled", "rivaled": "rivalled",
    # the reverse direction — US doubles where GB does not
    "skillful": "skilful", "fulfill": "fulfil", "fulfills": "fulfils",
    "enroll": "enrol", "enrolls": "enrols", "installment": "instalment",
    "willful": "wilful", "appall": "appal",
}

# Words ending -ise that are NEVER -ize in any variant. Getting this list wrong
# is the classic failure of naive -ise/-ize converters ("surprize", "advertize").
_ALWAYS_ISE = {
    "advertise", "advise", "apprise", "arise", "braise", "bruise", "chastise",
    "circumcise", "comprise", "compromise", "concise", "cruise", "demise",
    "despise", "devise", "disguise", "enterprise", "excise", "exercise",
    "expertise", "franchise", "guise", "improvise", "incise", "likewise",
    "malaise", "mayonnaise", "merchandise", "mortise", "noise", "otherwise",
    "paradise", "poise", "porpoise", "praise", "precise", "premise",
    "promise", "raise", "appraise", "revise", "rise", "supervise", "surmise",
    "surprise", "televise", "tortoise", "treatise", "valise", "wise",
    "clockwise", "anise", "chemise", "reprise", "franchise",
}
# …and the mirror: never -ise.
_ALWAYS_IZE = {"capsize", "seize", "size", "prize", "assize", "resize",
               "downsize", "upsize", "oversize"}

_ISE_RE = re.compile(r"\b([A-Za-z]{3,})(is|iz)(e|es|ed|ing|ation|ations|er|ers)\b")
_YSE_RE = re.compile(r"\b([A-Za-z]{3,})(ys|yz)(e|es|ed|ing|er|ers)\b")

# Profiles: which side of each family a variant sits on.
_PROFILES = {
    "en-US": {"our": "us", "re": "us", "ence": "us", "ogue": "us",
              "ll": "us", "ize": "z"},
    "en-GB": {"our": "gb", "re": "gb", "ence": "gb", "ogue": "gb",
              "ll": "gb", "ize": "s"},
    "en-CA": {"our": "gb", "re": "gb", "ence": "gb", "ogue": "gb",
              "ll": "gb", "ize": "z"},   # Canadian: British -our, American -ize
    "en-AU": {"our": "gb", "re": "gb", "ence": "gb", "ogue": "gb",
              "ll": "gb", "ize": "s"},
    "en-NZ": {"our": "gb", "re": "gb", "ence": "gb", "ogue": "gb",
              "ll": "gb", "ize": "s"},
    "en-IN": {"our": "gb", "re": "gb", "ence": "gb", "ogue": "gb",
              "ll": "gb", "ize": "s"},
}


def _match_case(source: str, target: str) -> str:
    """Carry the original's capitalisation onto the replacement."""
    if source.isupper() and len(source) > 1:
        return target.upper()
    if source[:1].isupper():
        return target[:1].upper() + target[1:]
    return target


def _apply_pairs(text: str, pairs: dict[str, str], to_gb: bool,
                 whole_word: bool = False) -> str:
    table = pairs if to_gb else {v: k for k, v in pairs.items()}
    for src, dst in table.items():
        pattern = (rf"\b{src}\b" if whole_word else rf"\b{src}{_SUFFIX}\b")

        def _sub(m: re.Match, src=src, dst=dst) -> str:
            whole = m.group(0)
            return _match_case(whole, dst + whole[len(src):])

        text = re.sub(pattern, _sub, text, flags=re.IGNORECASE)
    return text


def _apply_ize(text: str, want: str) -> str:
    """`want` is 'z' (-ize) or 's' (-ise). Exception lists win over the rule."""
    def _sub(m: re.Match) -> str:
        stem, mid, tail = m.group(1), m.group(2), m.group(3)
        base_s = (stem + "ise").lower()
        base_z = (stem + "ize").lower()
        if base_s in _ALWAYS_ISE:
            mid_out = "is"
        elif base_z in _ALWAYS_IZE:
            mid_out = "iz"
        else:
            mid_out = "iz" if want == "z" else "is"
        if mid_out == mid:
            return m.group(0)
        return stem + _match_case(mid, mid_out) + tail

    text = _ISE_RE.sub(_sub, text)

    def _sub_y(m: re.Match) -> str:
        stem, mid, tail = m.group(1), m.group(2), m.group(3)
        mid_out = "yz" if want == "z" else "ys"
        if mid_out == mid:
            return m.group(0)
        return stem + _match_case(mid, mid_out) + tail

    return _YSE_RE.sub(_sub_y, text)


def english_variant(text: str, variant: str) -> str:
    prof = _PROFILES.get(variant)
    if not prof:
        return text
    to_gb = prof["our"] == "gb"
    text = _apply_pairs(text, _OUR, to_gb)
    text = _apply_pairs(text, _RE, to_gb)
    text = _apply_pairs(text, _ENCE, to_gb)
    text = _apply_pairs(text, _OGUE, to_gb)
    text = _apply_pairs(text, _LL, prof["ll"] == "gb", whole_word=True)
    text = _apply_ize(text, prof["ize"])
    return text


# --------------------------------------------------------------------------
# Locale resolution + the stage
# --------------------------------------------------------------------------

def resolve_locale(language: str | None, english_variant_tag: str = "en-US") -> str:
    """Whisper language code (+ the user's English preference) → BCP-47 tag.

    `language: null` (auto-detect) resolves to the English preference, because
    that is the only variant the user actually configured; applying French
    spacing to auto-detected text would be guessing twice.
    """
    lang = (language or "en").lower().split("-")[0].split("_")[0]
    if lang == "en":
        return english_variant_tag if english_variant_tag in _PROFILES else "en-US"
    return {
        "fr": "fr-FR", "zh": "zh-CN", "ja": "ja-JP", "ko": "ko-KR",
        "hi": "hi-IN", "de": "de-DE", "es": "es-ES", "it": "it-IT",
        "pt": "pt-PT", "ru": "ru-RU", "ar": "ar-SA",
    }.get(lang, lang)


class LocaleTypographyStage(BaseStage):
    name = "locale"
    min_level = 1  # light — this is correctness, not "AI cleanup"

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def applies(self, ctx: UtteranceContext) -> bool:
        # Rule 1: never inject invisible characters into something that will be
        # executed. A U+202F in a shell command is a bug report nobody can read.
        return self.enabled and not ctx.is_terminal

    def run(self, text: str, ctx: UtteranceContext) -> str:
        loc = ctx.locale or "en-US"
        base = loc.split("-")[0]
        if base == "fr":
            return french_spacing(text)
        if base in ("zh", "ja", "ko"):
            return cjk_spacing(text)
        if base == "en":
            return english_variant(text, loc)
        return text
