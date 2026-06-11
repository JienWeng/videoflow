"""Frame anchoring: previous-scene picker + last-frame extraction fallbacks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import Scene
from app.services.render_service import pick_previous_scene

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _scene(sid: str, *, script_id: str | None = None, minutes: int = 0) -> Scene:
    return Scene(id=sid, script_id=script_id, created_at=T0 + timedelta(minutes=minutes))


def test_previous_is_latest_earlier_scene_of_same_script():
    a = _scene("scene_a", script_id="script_1", minutes=0)
    b = _scene("scene_b", script_id="script_1", minutes=5)
    c = _scene("scene_c", script_id="script_1", minutes=10)
    other = _scene("scene_other", script_id="script_2", minutes=9)
    assert pick_previous_scene(c, [a, b, c, other]) is b
    assert pick_previous_scene(b, [a, b, c, other]) is a


def test_other_scripts_never_win_when_scene_has_a_script():
    cur = _scene("scene_cur", script_id="script_1", minutes=10)
    foreign = _scene("scene_foreign", script_id="script_2", minutes=5)
    loose = _scene("scene_loose", script_id=None, minutes=5)
    assert pick_previous_scene(cur, [foreign, loose, cur]) is None


def test_no_script_falls_back_to_all_scenes_by_created_at():
    cur = _scene("scene_cur", minutes=10)
    older = _scene("scene_older", script_id="script_2", minutes=3)
    newest_older = _scene("scene_newest_older", minutes=7)
    newer = _scene("scene_newer", minutes=12)
    assert pick_previous_scene(cur, [older, newest_older, newer, cur]) is newest_older


def test_first_or_loner_scene_has_no_previous():
    first = _scene("scene_first", script_id="script_1", minutes=0)
    later = _scene("scene_later", script_id="script_1", minutes=5)
    assert pick_previous_scene(first, [first, later]) is None
    loner = _scene("scene_loner")
    assert pick_previous_scene(loner, [loner]) is None


async def test_extract_last_frame_returns_none_without_ffmpeg(monkeypatch, tmp_path):
    from app.services import media

    monkeypatch.setattr(media, "_ffmpeg", lambda: None)
    result = await media.extract_last_frame(tmp_path / "v.mp4", tmp_path / "f.png")
    assert result is None
