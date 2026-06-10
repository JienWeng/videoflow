"""Auto-captions (CapCut-style): ASR on the rendered video's voice track via
faster-whisper (open source, local, word-accurate Mandarin), styled ASS
subtitles, FFmpeg/libass burn-in.

The .ass file is kept next to the captioned video so timings/text can be
hand-edited and re-burned. Styling is preset-based (STYLES); fonts are loaded
from storage/fonts (Noto Sans CJK SC ships there for Chinese).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session

from app.config import get_settings
from app.errors import NotFoundError, ProviderError, ValidationFailedError
from app.models import RenderOutput
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
    logger.info("captioned %s (%d segments, style=%s)", output_id, len(segments), style)
    return output
