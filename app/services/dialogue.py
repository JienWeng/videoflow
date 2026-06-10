"""Dialogue detection: every shot must carry one short spoken line in 「」.

The captions pipeline extracts these lines and Kling voices them, so a shot
without a 「」 line renders silent. A line counts only when it is non-empty
and short (<= 60 characters inside the quotes).
"""

from __future__ import annotations

import re

DIALOGUE_RE = re.compile(r"「[^」]{1,60}」")


def has_dialogue(text: str) -> bool:
    """True when the text contains at least one short spoken 「」 line."""
    return bool(DIALOGUE_RE.search(text or ""))
