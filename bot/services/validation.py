"""Validation of LLM-generated phrases.

A phrase written by a language model is read by a child, inside a message the
bot sends with HTML parse mode. That makes model output untrusted input on two
counts: a stray `<` alone makes Telegram reject the whole message, and a phrase
that looks like it is revealing an answer would quietly ruin the exercise.

Everything is escaped on send regardless — escaping is the guarantee, this
validation is the layer that keeps junk out of the pool in the first place.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: Letters, digits, whitespace and the punctuation a cheerful Russian sentence
#: needs. Anything outside this set (bar emoji, handled separately) is refused.
_ALLOWED_PUNCTUATION = set(" \t.,!?:;-—–…()«»\"'%№")
_CYRILLIC = re.compile(r"[а-яёА-ЯЁ]")
_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
_URL = re.compile(r"(https?://|www\.|\w+\.(?:ru|com|org|net|io|me)\b)", re.IGNORECASE)
_ARITHMETIC = re.compile(r"\d\s*[-+*/×÷=]\s*\d")
_MULTI_DIGIT = re.compile(r"\d{2,}")
_MARKUP = re.compile(r"[<>{}\[\]\\|`]")


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok


ZERO_WIDTH_JOINER = "\u200d"
_VARIATION_SELECTORS = {"\ufe0e", "\ufe0f"}
_SKIN_TONES = range(0x1F3FB, 0x1F400)


def _is_emoji_base(char: str) -> bool:
    """A character that renders as a pictograph in its own right.

    Modifiers — variation selectors, skin tones, the zero-width joiner — are
    deliberately excluded: they decorate a base rather than being one, so they
    must not add to the count.
    """
    code = ord(char)
    if char in _VARIATION_SELECTORS or char == ZERO_WIDTH_JOINER or code in _SKIN_TONES:
        return False
    if 0x1F000 <= code <= 0x1FAFF or 0x2600 <= code <= 0x27BF:
        return True
    return unicodedata.category(char) == "So"


def _is_emoji_part(char: str) -> bool:
    """Any character that belongs to an emoji, base or modifier."""
    code = ord(char)
    return (
        _is_emoji_base(char)
        or char in _VARIATION_SELECTORS
        or char == ZERO_WIDTH_JOINER
        or code in _SKIN_TONES
        or unicodedata.category(char) == "Sk"
    )


def count_emoji(text: str) -> int:
    """Count emoji, joining only what Unicode actually joins.

    A run of distinct emoji is a run of distinct emoji — the count must not
    collapse `🎉🎈🥇` into one. Only a zero-width joiner merges neighbours, the
    way it does in a composed family or profession emoji.
    """
    count = 0
    joined_to_previous = False
    for char in text:
        if char == ZERO_WIDTH_JOINER:
            joined_to_previous = True
            continue
        if _is_emoji_base(char):
            if not joined_to_previous:
                count += 1
            joined_to_previous = False
            continue
        joined_to_previous = False
    return count


def validate_phrase(text: str, *, max_length: int, max_emoji: int) -> ValidationResult:
    """Decide whether a generated phrase may enter the pool."""
    stripped = text.strip()

    if not stripped:
        return ValidationResult(False, "empty")
    if len(stripped) > max_length:
        return ValidationResult(False, f"longer than {max_length} characters")
    if "\n" in stripped:
        return ValidationResult(False, "contains a line break")
    if _MARKUP.search(stripped):
        return ValidationResult(False, "contains markup characters")
    if _URL.search(stripped):
        return ValidationResult(False, "contains a link")
    if _LATIN_WORD.search(stripped):
        return ValidationResult(False, "contains a Latin-script word")
    if not _CYRILLIC.search(stripped):
        return ValidationResult(False, "contains no Russian text")
    if _ARITHMETIC.search(stripped):
        return ValidationResult(False, "contains an arithmetic expression")
    if _MULTI_DIGIT.search(stripped):
        return ValidationResult(False, "contains a multi-digit number")

    emoji = count_emoji(stripped)
    if emoji > max_emoji:
        return ValidationResult(False, f"contains {emoji} emoji, more than {max_emoji}")

    for char in stripped:
        if char.isalnum() or char in _ALLOWED_PUNCTUATION or _is_emoji_part(char):
            continue
        return ValidationResult(False, f"contains disallowed character {char!r}")

    return ValidationResult(True)
