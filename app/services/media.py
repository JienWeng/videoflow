"""Media helpers: download generated outputs, extract thumbnails/frames (FFmpeg)."""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

import httpx

logger = logging.getLogger("videoflow.media")


async def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with dest.open("wb") as fh:
                async for chunk in resp.aiter_bytes():
                    fh.write(chunk)
    return dest


def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


async def make_thumbnail(video_path: Path, dest: Path, *, at_seconds: float = 1.0) -> Path | None:
    """Grab a single frame as a thumbnail. Returns None if FFmpeg is absent."""
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        logger.warning("ffmpeg not found; skipping thumbnail for %s", video_path)
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-y", "-ss", str(at_seconds), "-i", str(video_path),
        "-frames:v", "1", "-q:v", "3", str(dest),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.communicate()
    return dest if dest.exists() else None


async def extract_last_frame(video_path: Path, dest: Path) -> Path | None:
    """Grab the FINAL frame of a video (the anchor that steers the next scene's
    render). Returns None if FFmpeg is absent.

    `-sseof -3` seeks 3s before the end; `-update 1` keeps overwriting `dest`
    with each decoded frame, so the last write is the video's last frame."""
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        logger.warning("ffmpeg not found; skipping last-frame extraction for %s", video_path)
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-y", "-sseof", "-3", "-i", str(video_path),
        "-update", "1", "-q:v", "2", str(dest),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.communicate()
    return dest if dest.exists() else None


async def extract_frames(video_path: Path, dest_dir: Path, *, fps: float = 0.5, max_frames: int = 6) -> list[Path]:
    """Extract sample frames for QA. Returns [] if FFmpeg is absent."""
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        logger.warning("ffmpeg not found; skipping frame extraction")
        return []
    dest_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(dest_dir / "frame_%02d.jpg")
    proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-y", "-i", str(video_path),
        "-vf", f"fps={fps}", "-frames:v", str(max_frames), "-q:v", "3", pattern,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.communicate()
    return sorted(dest_dir.glob("frame_*.jpg"))
