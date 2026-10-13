"""Text hygiene for everything a person reads.

`humanize_text` is applied to model generated and template generated text before it is stored
or sent. Rules come from `ui-copywriting.md`: no long dashes, no banned words, no exclamation
marks, no emoji, single spaces. `scripts/check_copy.py` imports `BANNED_WORDS` so there is one
list.
"""

import re

LONG_DASHES = ("—", "–")  # em dash, en dash

# Words and phrases that must never appear in user-facing copy (ui-copywriting.md section 3).
BANNED_WORDS: tuple[str, ...] = (
    "seamless",
    "seamlessly",
    "robust",
    "powerful",
    "leverage",
    "utilise",
    "utilize",
    "unlock",
    "supercharge",
    "elevate",
    "empower",
    "effortless",
    "effortlessly",
    "streamline",
    "cutting-edge",
    "state-of-the-art",
    "game-changer",
    "revolutionary",
    "intelligent",
    "smart",
    "AI-powered",
    "magic",
    "magical",
    "delve",
    "dive in",
    "journey",
    "ecosystem",
    "holistic",
    "synergy",
    "at your fingertips",
    "in today's",
    "it's important to note",
    "welcome back",
    "let's get started",
    "oops",
    "uh oh",
    "hang tight",
    "sit back and relax",
    "simply",
    "just",
    "easily",
    "insights",
    "actionable",
    "best-in-class",
    "next-level",
)

# Rewrites applied case-insensitively on word boundaries. An empty replacement drops the word.
# Longer phrases come first so they win over their parts.
_REWRITES: tuple[tuple[str, str], ...] = (
    (r"it's important to note that", ""),
    (r"it's important to note", ""),
    (r"let's get started", ""),
    (r"welcome back", ""),
    (r"sit back and relax", ""),
    (r"hang tight", ""),
    (r"at your fingertips", "available"),
    (r"in today's", "in the"),
    (r"dive in", "start"),
    (r"uh oh", ""),
    (r"oops", ""),
    (r"state-of-the-art", "modern"),
    (r"cutting-edge", "modern"),
    (r"best-in-class", "good"),
    (r"next-level", "better"),
    (r"game-changer", "big change"),
    (r"ai-powered", ""),
    (r"utili[sz](?:e|es|ed|ing)", "use"),
    (r"leverag(?:e|es|ed|ing)", "use"),
    (r"unlock(?:s|ed|ing)?", "open"),
    (r"supercharg(?:e|es|ed|ing)", "improve"),
    (r"elevat(?:e|es|ed|ing)", "raise"),
    (r"empower(?:s|ed|ing)?", "help"),
    (r"streamlin(?:e|es|ed|ing)", "simplify"),
    (r"delv(?:e|es|ed|ing)", "look"),
    (r"insights", "numbers"),
    (r"insight", "number"),
    (r"actionable", "useful"),
    (r"revolutionary", "new"),
    (r"holistic", "complete"),
    (r"synergy", "fit"),
    (r"ecosystem", "setup"),
    (r"journey", "process"),
    (r"seamlessly", ""),
    (r"seamless", ""),
    (r"effortlessly", ""),
    (r"effortless", ""),
    (r"easily", ""),
    (r"simply", ""),
    (r"just", ""),
    (r"robust", "reliable"),
    (r"powerful", "strong"),
    (r"intelligent", ""),
    (r"smart", ""),
    (r"magical", ""),
    (r"magic", ""),
)

# Marks "the next letter starts a sentence" after a dropped word that was capitalised.
_CAPITALISE_NEXT = "\x00"

_EMOJI = re.compile("[\U0001f000-\U0001faff☀-➿️‍]")
_RANGE_DASH = re.compile(r"(?<=\d)\s*[–—]\s*(?=\d)")
_ANY_DASH = re.compile(r"\s*[–—]\s*")
_SPACES = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:?%)])")
_COMMA_RUN = re.compile(r"(?:,\s*){2,}")
_COMMA_BEFORE_STOP = re.compile(r",\s*([.?])")
_STOP_BEFORE_COMMA = re.compile(r"([.?])\s*,")
_DOUBLE_STOP = re.compile(r"(?<!\.)\.\.(?!\.)")
_ORPHAN_STOP = re.compile(rf"(?<=[.?])\s+({_CAPITALISE_NEXT}?)\.(?!\.)")
_LEADING_JUNK = re.compile(rf"^({_CAPITALISE_NEXT}?)[\s,;:.]+")
_TRAILING_COMMA = re.compile(r"[\s,]+$")
_CAPITALISE = re.compile(_CAPITALISE_NEXT + r"\s*([a-z])")
_MARK_THEN_PUNCT = re.compile(_CAPITALISE_NEXT + r"[\s,;:]*")


def _compile(pattern: str, replacement: str) -> tuple[re.Pattern[str], str]:
    return re.compile(rf"(?<![\w-]){pattern}(?![\w-])", re.IGNORECASE), replacement


_REWRITE_PATTERNS = tuple(_compile(pattern, replacement) for pattern, replacement in _REWRITES)


def _apply_rewrite(pattern: re.Pattern[str], replacement: str, text: str) -> str:
    def swap(match: re.Match[str]) -> str:
        was_capital = match.group(0)[:1].isupper()
        if not replacement:
            return _CAPITALISE_NEXT if was_capital else ""
        return replacement[:1].upper() + replacement[1:] if was_capital else replacement

    return pattern.sub(swap, text)


def humanize_text(text: str) -> str:
    """Return `text` without long dashes, banned words, exclamation marks and emoji."""
    if not text:
        return text
    result = _EMOJI.sub("", text)
    result = _RANGE_DASH.sub(" to ", result)
    result = _ANY_DASH.sub(", ", result)
    for pattern, replacement in _REWRITE_PATTERNS:
        result = _apply_rewrite(pattern, replacement, result)
    result = _MARK_THEN_PUNCT.sub(_CAPITALISE_NEXT, result)
    result = result.replace("!", ".")
    result = _SPACES.sub(" ", result)
    result = _SPACE_BEFORE_PUNCT.sub(r"\1", result)
    result = _COMMA_RUN.sub(", ", result)
    result = _COMMA_BEFORE_STOP.sub(r"\1", result)
    result = _STOP_BEFORE_COMMA.sub(r"\1", result)
    result = _DOUBLE_STOP.sub(".", result)
    result = _ORPHAN_STOP.sub(r"\1", result)
    result = _LEADING_JUNK.sub(r"\1", result)
    result = _TRAILING_COMMA.sub("", result) if result.endswith((",", ", ")) else result
    result = _CAPITALISE.sub(lambda m: m.group(1).upper(), result)
    return result.replace(_CAPITALISE_NEXT, "").strip()


def contains_long_dash(text: str) -> bool:
    return any(dash in text for dash in LONG_DASHES)
