"""Sanitising for free-text fields typed by reviewers.

Reviewers must never type patient identifiers into these fields. The text is stored only
in the reviews table; it is not copied into the audit log and never logged.
"""

from __future__ import annotations

import unicodedata
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, StringConstraints

REVIEWER_MAX = 100
TEXT_MAX = 1000


def clean_text(value: object, allow_newlines: bool) -> object:
    """Strip control and invisible format characters, normalise newlines, trim.

    Removes Unicode categories Cc (control) and Cf (format, which includes zero-width
    and bidirectional-override characters that can make stored text display differently
    from what it contains). Newlines survive only where ``allow_newlines`` is true.
    Non-strings are returned unchanged so pydantic reports the type error.
    """
    if not isinstance(value, str):
        return value
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    kept = []
    for ch in value:
        category = unicodedata.category(ch)
        if ch == "\n" and allow_newlines:
            kept.append(ch)
        elif ch == "\t":
            kept.append(" ")
        elif category not in ("Cc", "Cf"):
            kept.append(ch)
    return "".join(kept).strip()


def _single_line(value: object) -> object:
    return clean_text(value, allow_newlines=False)


def _multi_line(value: object) -> object:
    return clean_text(value, allow_newlines=True)


def _empty_to_none(value: str) -> str | None:
    """Text that is empty after cleaning counts as not given."""
    return value or None


# Length limits apply after cleaning, so invisible padding cannot exceed them.
ReviewerName = Annotated[
    str,
    BeforeValidator(_single_line),
    StringConstraints(min_length=1, max_length=REVIEWER_MAX),
]
FreeText = Annotated[
    str,
    BeforeValidator(_multi_line),
    StringConstraints(max_length=TEXT_MAX),
    AfterValidator(_empty_to_none),
]
