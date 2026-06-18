"""Dialogue detection + pacing: every shot carries one spoken line in 「」, sized
to FILL its shot at a brisk speaking pace (~170-200 WPM) so the video doesn't drag.

The captions pipeline extracts these lines and Kling voices them, so a shot
without a 「」 line renders silent. A line counts when it is non-empty and within
a generous length (<= 220 characters — long enough to FILL a 15s shot at a brisk
pace). Pacing (`pace_check`) sizes the line to the shot duration: too few words =
dead air / slow; too many = rushed.
"""

from __future__ import annotations

import math
import re

from app.config import Settings, get_settings

# Generous upper bound: a 15s shot at ~200 WPM is ~50 words (~250 chars), so the
# cap is high enough that duration-filling lines aren't rejected as "no dialogue".
DIALOGUE_RE = re.compile(r"「[^」]{1,220}」")
_INNER_RE = re.compile(r"「([^」]{1,220})」")
_CJK_RE = re.compile(r"[一-鿿]")


def has_dialogue(text: str) -> bool:
    """True when the text contains at least one short spoken 「」 line."""
    return bool(DIALOGUE_RE.search(text or ""))


def line_inside_quotes(text: str) -> str | None:
    """The text inside the first 「」 spoken line, or None."""
    m = _INNER_RE.search(text or "")
    return m.group(1).strip() if m else None


def spoken_units(line: str) -> tuple[str, int]:
    """How long a spoken line is, for pacing: ('zh', CJK-char-count) when the line
    contains any Chinese, else ('en', word-count). Punctuation/spaces are ignored
    for Chinese."""
    cjk = _CJK_RE.findall(line or "")
    if cjk:
        return "zh", len(cjk)
    return "en", len((line or "").split())


def _bounds(settings: Settings) -> dict:
    return {
        "wpm_min": settings.dialogue_wpm_min,
        "wpm_max": settings.dialogue_wpm_max,
        "cps_min": settings.dialogue_cps_zh_min,
        "cps_max": settings.dialogue_cps_zh_max,
    }


def pace_bounds(
    duration: float, kind: str, settings: Settings | None = None
) -> tuple[int, int]:
    """The (min, max) spoken-unit count that fills `duration` seconds at the target
    pace. English uses words/min; Chinese uses characters/second. Always >= 1."""
    settings = settings or get_settings()
    b = _bounds(settings)
    d = max(0.0, float(duration))
    if kind == "zh":
        lo = math.floor(b["cps_min"] * d)
        hi = math.ceil(b["cps_max"] * d)
    else:
        lo = math.floor(b["wpm_min"] / 60.0 * d)
        hi = math.ceil(b["wpm_max"] / 60.0 * d)
    lo = max(1, lo)
    hi = max(lo, hi)
    return lo, hi


def pace_check(
    line_or_prompt: str, duration: float, settings: Settings | None = None
) -> dict:
    """Judge a shot's spoken line against its duration's pace budget. Returns
    {verdict: none|too_short|ok|too_long, kind, count, lo, hi}."""
    settings = settings or get_settings()
    line = line_inside_quotes(line_or_prompt)
    if not line:
        return {"verdict": "none", "kind": None, "count": 0, "lo": 0, "hi": 0}
    kind, count = spoken_units(line)
    lo, hi = pace_bounds(duration, kind, settings)
    if count < lo:
        verdict = "too_short"
    elif count > hi:
        verdict = "too_long"
    else:
        verdict = "ok"
    return {"verdict": verdict, "kind": kind, "count": count, "lo": lo, "hi": hi}
