"""Auto-captions (CapCut-style): ASR on the rendered video's voice track via
faster-whisper (open source, local, word-accurate Mandarin), styled ASS
subtitles, FFmpeg/libass burn-in.

The .ass file is kept next to the captioned video so timings/text can be
hand-edited and re-burned. Styling is preset-based (STYLES); fonts are loaded
from storage/fonts (Noto Sans CJK SC ships there for Chinese).
"""

from __future__ import annotations

import asyncio
import dataclasses
import difflib
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, select

from app.config import get_settings
from app.errors import NotFoundError, ProviderError, ValidationFailedError
from app.models import Asset, RenderOutput
from app.models.render_job import RenderJob
from app.models.base import utcnow

logger = logging.getLogger("videoflow.captions")

FONT_NAME = "Noto Sans CJK SC"


@dataclass
class CaptionSegment:
    start: float
    end: float
    text: str


# ASS V4+ style fields per preset. Colours are &HAABBGGRR.
STYLES: dict[str, dict] = {
    # Big bouncy yellow with thick black outline — kids/TikTok look.
    "kids": dict(fontsize=78, primary="&H0000E6FF", outline_colour="&H00000000",
                 back="&H00000000", borderstyle=1, outline=6, shadow=0, marginv=220),
    # White with slim dark outline — general purpose.
    "clean": dict(fontsize=58, primary="&H00FFFFFF", outline_colour="&H00141414",
                  back="&H00000000", borderstyle=1, outline=3, shadow=1, marginv=180),
    # Small white on translucent box — documentary/minimal.
    "minimal": dict(fontsize=46, primary="&H00FFFFFF", outline_colour="&H00000000",
                    back="&H66000000", borderstyle=3, outline=0, shadow=0, marginv=150),
}


QUOTE_RE = re.compile(r'[「『"“]([^」』"”]{1,80})[」』"”]')

_NORM_RE = re.compile(r"[\s，。！？、,.!?…~～]")


def extract_script_lines(spec: dict | None) -> list[str]:
    """Pull quoted dialogue lines from a RenderSpec dict (prompt + multi_prompt)."""
    if not spec:
        return []
    texts = [spec.get("prompt") or ""]
    texts += [(p.get("prompt") or "") for p in spec.get("multi_prompt") or []]
    lines: list[str] = []
    for t in texts:
        for m in QUOTE_RE.findall(t):
            line = m.strip()
            if line and line not in lines:
                lines.append(line)
    return lines


def timed_script_lines(spec: dict | None) -> list[dict]:
    """[{'text': line, 'start': s, 'end': e}] from multi_prompt entries that
    contain a 「」 line.

    Windows are cumulative durations in entry order (the 1-based ``index``
    field if present, else list order). Entries without a quoted line still
    contribute their duration to the timeline but yield no line. Returns []
    when there is no multi_prompt or any entry lacks a positive duration —
    callers then fall back to untimed matching.
    """
    if not spec:
        return []
    entries = spec.get("multi_prompt") or []
    if not entries:
        return []
    if any(not isinstance(e.get("duration"), (int, float)) or e["duration"] <= 0 for e in entries):
        return []
    if all(isinstance(e.get("index"), int) for e in entries):
        entries = sorted(entries, key=lambda e: e["index"])
    lines: list[dict] = []
    t = 0.0
    for e in entries:
        start, t = t, t + float(e["duration"])
        m = QUOTE_RE.search(e.get("prompt") or "")
        if m:
            line = m.group(1).strip()
            if line:
                lines.append({"text": line, "start": start, "end": t})
    return lines


def _normalize(text: str) -> str:
    """Strip whitespace and CJK/ASCII punctuation for fuzzy matching."""
    return _NORM_RE.sub("", text)


def correct_segments(
    segments: list[CaptionSegment], script_lines: list[str], min_ratio: float = 0.5
) -> list[CaptionSegment]:
    """Replace each segment's text with the best-matching script line (timings kept).

    Monotonic alignment policy:
    - A cursor marks the earliest script line still eligible for matching.
    - For each segment (time-ordered), we score lines from cursor onward only;
      lines before the cursor are already consumed and cannot be re-matched.
    - On a tie the EARLIEST eligible line wins (cursor stays low → earlier speaker).
    - After matching line[i], we advance the cursor to i (not i+1) so the SAME
      line can be re-matched by the next segment (handles one script line split
      across multiple whisper segments). The cursor never moves backward.
    - A segment keeps its whisper text when no eligible line clears `min_ratio`.
    """
    if not script_lines:
        return segments

    norm_lines = [_normalize(line) for line in script_lines]
    cursor = 0  # first eligible script-line index
    result: list[CaptionSegment] = []

    for seg in segments:
        norm_seg = _normalize(seg.text)
        best_ratio = 0.0
        best_idx = cursor  # tie-break: prefer earliest eligible line
        # Score only lines at-or-after the cursor.
        for i in range(cursor, len(script_lines)):
            ratio = difflib.SequenceMatcher(None, norm_seg, norm_lines[i]).ratio()
            if ratio > best_ratio:  # strict > keeps earliest on a tie
                best_ratio = ratio
                best_idx = i
        if best_ratio >= min_ratio:
            result.append(dataclasses.replace(seg, text=script_lines[best_idx]))
            # Advance cursor past the matched line so the next segment cannot
            # re-match an earlier (already-consumed) line. This is the key
            # monotonic guarantee: once line[i] is matched, only line[i+1]…
            # are eligible for future segments. If a single long script line
            # spans multiple whisper segments, the script should have that line
            # appear once — the two-segment split will match consecutive lines.
            cursor = best_idx + 1
        else:
            result.append(seg)

    return result


def correct_segments_timed(
    segments: list[CaptionSegment], timed_lines: list[dict], min_ratio: float = 0.35
) -> list[CaptionSegment]:
    """Replace each segment's text with the best-matching script line among
    those whose shot window overlaps the segment in time (timings kept).

    Overlap semantics: ANY overlap — a line window [ws, we) is a candidate for
    segment [ss, se) when ``ws < se and ss < we``. This is deliberately more
    forgiving than midpoint-in-window because whisper timings (and rendered
    shot boundaries) drift by fractions of a second; a segment straddling a cut
    still sees both neighbouring lines and the fuzzy ratio picks the right one.

    Among overlapping lines the best fuzzy ratio wins (earliest window on a
    tie). Since time already disambiguates, the acceptance threshold (0.35) is
    lower than the pure-text matcher's 0.5. Segments with no overlapping line
    or below the threshold keep their whisper text.
    """
    if not timed_lines:
        return segments

    result: list[CaptionSegment] = []
    for seg in segments:
        norm_seg = _normalize(seg.text)
        best_text: str | None = None
        best_ratio = 0.0
        for line in timed_lines:
            if not (line["start"] < seg.end and seg.start < line["end"]):
                continue
            ratio = difflib.SequenceMatcher(None, norm_seg, _normalize(line["text"])).ratio()
            if ratio > best_ratio:  # strict > keeps the earliest window on a tie
                best_ratio = ratio
                best_text = line["text"]
        if best_text is not None and best_ratio >= min_ratio:
            result.append(dataclasses.replace(seg, text=best_text))
        else:
            result.append(seg)
    return result


def format_ass_time(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build_ass(
    segments: list[CaptionSegment],
    *,
    style: str = "kids",
    play_res: tuple[int, int] = (1080, 1920),
) -> str:
    if style not in STYLES:
        raise ValueError(f"unknown caption style '{style}' (have: {', '.join(STYLES)})")
    s = STYLES[style]
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_res[0]}\n"
        f"PlayResY: {play_res[1]}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Caption,{FONT_NAME},{s['fontsize']},{s['primary']},&H000000FF,"
        f"{s['outline_colour']},{s['back']},-1,0,0,0,100,100,0,0,"
        f"{s['borderstyle']},{s['outline']},{s['shadow']},2,40,40,{s['marginv']},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = [
        f"Dialogue: 0,{format_ass_time(seg.start)},{format_ass_time(seg.end)},"
        f"Caption,,0,0,0,,{seg.text.strip().replace(chr(10), chr(92) + 'N')}"
        for seg in segments
        if seg.text.strip()
    ]
    return header + "\n".join(lines) + "\n"


WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3"]

_models: dict[str, "WhisperModel"] = {}  # type: ignore[name-defined]


def _get_model(size: str):
    if size not in _models:
        from faster_whisper import WhisperModel

        logger.info("loading faster-whisper '%s' (first run downloads it)", size)
        _models[size] = WhisperModel(size, device="cpu", compute_type="int8")
    return _models[size]


async def transcribe(
    video_path: Path,
    language: str | None = None,
    model_size: str | None = None,
) -> list[CaptionSegment]:
    """Run faster-whisper on the video's audio track (blocking → thread)."""
    size = model_size or get_settings().whisper_model

    def _run() -> list[CaptionSegment]:
        model = _get_model(size)
        segments, _info = model.transcribe(
            str(video_path), language=language, vad_filter=True
        )
        return [
            CaptionSegment(start=seg.start, end=seg.end, text=seg.text.strip())
            for seg in segments
            if seg.text.strip()
        ]

    return await asyncio.to_thread(_run)


async def burn_subtitles(video_path: Path, ass_path: Path, dest: Path) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ProviderError("ffmpeg is required to burn captions")
    fonts_dir = get_settings().storage_root / "fonts"
    dest.parent.mkdir(parents=True, exist_ok=True)
    vf = f"ass={ass_path}:fontsdir={fonts_dir}"
    proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-y", "-i", str(video_path), "-vf", vf,
        "-c:a", "copy", str(dest),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 or not dest.exists():
        raise ProviderError(f"caption burn failed: {stderr.decode()[-300:]}")
    return dest


async def caption_output(
    session: Session,
    output_id: str,
    *,
    style: str = "kids",
    language: str | None = "zh",
    model: str | None = None,
) -> RenderOutput:
    """Transcribe an output's voice track and burn styled captions into a copy."""
    output = session.get(RenderOutput, output_id)
    if output is None:
        raise NotFoundError(f"render output {output_id} not found")
    if not output.video_path or not Path(output.video_path).exists():
        raise ValidationFailedError(f"output {output_id} has no video file")
    if style not in STYLES:
        raise ValidationFailedError(
            f"unknown caption style '{style}' (have: {', '.join(STYLES)})"
        )
    if model is not None and model not in WHISPER_MODELS:
        raise ValidationFailedError(
            f"unknown whisper model '{model}' (have: {', '.join(WHISPER_MODELS)})"
        )

    video_path = Path(output.video_path)
    segments = await transcribe(video_path, language=language, model_size=model)
    if not segments:
        raise ValidationFailedError("no speech detected in the video")

    job = session.get(RenderJob, output.render_job_id)
    request_json = job.request_json if job else None
    timed = timed_script_lines(request_json)
    if timed:
        # Shot durations give each script line a time window — align by time
        # first, fuzzy ratio as tiebreak/validation.
        segments = correct_segments_timed(segments, timed)
    else:
        script_lines = extract_script_lines(request_json)
        if script_lines:
            segments = correct_segments(segments, script_lines)

    base = video_path.with_suffix("")
    ass_path = Path(f"{base}.ass")
    ass_path.write_text(build_ass(segments, style=style), encoding="utf-8")
    captioned = Path(f"{base}_captioned.mp4")
    await burn_subtitles(video_path, ass_path, captioned)

    output.captioned_path = str(captioned)
    output.updated_at = utcnow()
    session.add(output)
    session.commit()
    session.refresh(output)

    # Mirror captioned_path onto the linked video asset so the Assets library
    # stays in sync. Linear scan is fine; table is small and SQLite JSON
    # columns aren't easily queryable.
    captioned_path_str = output.captioned_path
    for a in session.exec(select(Asset)).all():
        if a.metadata_json.get("render_output_id") == output_id:
            a.metadata_json = {**a.metadata_json, "captioned_path": captioned_path_str}
            session.add(a)
            session.commit()
            break

    # Re-attach output after the asset commit (SQLAlchemy expires objects on commit).
    session.refresh(output)
    logger.info("captioned %s (%d segments, style=%s)", output_id, len(segments), style)
    return output
