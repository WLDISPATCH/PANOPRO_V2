from __future__ import annotations

from pathlib import Path

import pytest

from pano_namer.desktop import (
    _load_last_picker_dir,
    _save_last_picker_dir,
    _selection_directory,
    configure_webengine,
    mark_render_clean_exit,
    resolve_render_mode,
)


def test_save_and_load_last_picker_dir(tmp_path):
    state_file = tmp_path / "desktop-state.json"
    folder = tmp_path / "photos"
    folder.mkdir()

    _save_last_picker_dir(folder, state_file)

    assert _load_last_picker_dir(state_file) == folder


def test_load_last_picker_dir_ignores_missing_or_invalid_state(tmp_path):
    state_file = tmp_path / "desktop-state.json"
    state_file.write_text("{not json}", encoding="utf-8")

    assert _load_last_picker_dir(state_file) is None


def test_selection_directory_uses_first_selected_file_parent(tmp_path):
    folder = tmp_path / "import"
    folder.mkdir()
    file_path = folder / "image.jpg"
    file_path.write_text("x", encoding="utf-8")

    assert _selection_directory([str(file_path)]) == folder
    assert _selection_directory([str(folder)]) == folder
    assert _selection_directory([]) is None


@pytest.fixture()
def render_state(tmp_path):
    return tmp_path / "render.json"


def test_render_mode_defaults_to_gpu_and_clears_on_clean_exit(render_state, monkeypatch):
    monkeypatch.delenv("PANOPRO_FORCE_GPU", raising=False)
    monkeypatch.delenv("PANOPRO_DISABLE_GPU", raising=False)
    assert resolve_render_mode(render_state) == "gpu"
    # A clean exit clears the sentinel so the next launch is still GPU.
    mark_render_clean_exit(render_state)
    assert resolve_render_mode(render_state) == "gpu"


def _crash_launch(state_file, ts):
    # A launch that then crashes: resolve runs, but no clean-exit is recorded.
    return resolve_render_mode(state_file, now_iso=ts)


def _clean_launch(state_file, ts):
    mode = resolve_render_mode(state_file, now_iso=ts)
    mark_render_clean_exit(state_file)
    return mode


def test_render_mode_tolerates_occasional_crashes(render_state, monkeypatch):
    monkeypatch.delenv("PANOPRO_FORCE_GPU", raising=False)
    monkeypatch.delenv("PANOPRO_DISABLE_GPU", raising=False)
    # Two crashes over time (below the 3-in-30-days threshold) stay on GPU.
    _crash_launch(render_state, "2026-07-01T00:00:00+00:00")
    assert _clean_launch(render_state, "2026-07-05T00:00:00+00:00") == "gpu"
    _crash_launch(render_state, "2026-07-05T01:00:00+00:00")
    assert _clean_launch(render_state, "2026-07-10T00:00:00+00:00") == "gpu"


def test_render_mode_falls_back_on_crashes_with_clean_runs_between(render_state, monkeypatch):
    # Regression for the FH-UAV-II field pattern (2026-07-15): crash, relaunch,
    # use it fine, close cleanly, crash again. The old "two consecutive" rule
    # never fired because the clean run wiped the counter each time.
    monkeypatch.delenv("PANOPRO_FORCE_GPU", raising=False)
    monkeypatch.delenv("PANOPRO_DISABLE_GPU", raising=False)
    _crash_launch(render_state, "2026-07-11T13:21:50+00:00")   # crash 1
    assert _clean_launch(render_state, "2026-07-11T13:25:34+00:00") == "gpu"
    _crash_launch(render_state, "2026-07-13T14:36:48+00:00")   # crash 2
    assert _clean_launch(render_state, "2026-07-13T15:05:13+00:00") == "gpu"
    _crash_launch(render_state, "2026-07-15T05:33:36+00:00")   # crash 3
    # The launch after the 3rd crash falls back and stays there.
    assert resolve_render_mode(render_state, now_iso="2026-07-15T06:00:00+00:00") == "software"
    assert resolve_render_mode(render_state, now_iso="2026-07-15T07:00:00+00:00") == "software"


def test_render_mode_prunes_crashes_outside_window(render_state, monkeypatch):
    monkeypatch.delenv("PANOPRO_FORCE_GPU", raising=False)
    monkeypatch.delenv("PANOPRO_DISABLE_GPU", raising=False)
    # Two crashes long ago should age out and not stack with a fresh one.
    _crash_launch(render_state, "2026-01-01T00:00:00+00:00")
    _clean_launch(render_state, "2026-01-02T00:00:00+00:00")
    _crash_launch(render_state, "2026-01-02T01:00:00+00:00")
    _clean_launch(render_state, "2026-01-03T00:00:00+00:00")
    # Months later a single crash must not trip the fallback.
    _crash_launch(render_state, "2026-07-01T00:00:00+00:00")
    assert resolve_render_mode(render_state, now_iso="2026-07-01T01:00:00+00:00") == "gpu"


def test_render_mode_reads_legacy_state_without_error(render_state, monkeypatch):
    monkeypatch.delenv("PANOPRO_FORCE_GPU", raising=False)
    monkeypatch.delenv("PANOPRO_DISABLE_GPU", raising=False)
    # Machines updating from 2.7.8 have the old int-counter format.
    render_state.write_text('{"running": true, "crashes": 1}', encoding="utf-8")
    assert resolve_render_mode(render_state, now_iso="2026-07-15T00:00:00+00:00") == "gpu"


def test_clean_exit_preserves_crash_history(render_state, monkeypatch):
    monkeypatch.delenv("PANOPRO_FORCE_GPU", raising=False)
    monkeypatch.delenv("PANOPRO_DISABLE_GPU", raising=False)
    _crash_launch(render_state, "2026-07-01T00:00:00+00:00")
    _clean_launch(render_state, "2026-07-02T00:00:00+00:00")  # records crash 1
    import json

    state = json.loads(render_state.read_text())
    assert len(state.get("crashes", [])) == 1
    assert "running" not in state  # clean exit cleared only the sentinel


def test_render_mode_env_overrides(render_state, monkeypatch):
    render_state.write_text('{"mode": "software"}', encoding="utf-8")
    monkeypatch.setenv("PANOPRO_FORCE_GPU", "1")
    assert resolve_render_mode(render_state) == "gpu"  # force wins over sticky software
    monkeypatch.delenv("PANOPRO_FORCE_GPU")
    monkeypatch.setenv("PANOPRO_DISABLE_GPU", "1")
    assert resolve_render_mode(render_state) == "software"


def test_configure_webengine_flags_per_mode(monkeypatch):
    monkeypatch.delenv("PANOPRO_CHROMIUM_FLAGS", raising=False)
    monkeypatch.delenv("QTWEBENGINE_CHROMIUM_FLAGS", raising=False)
    assert configure_webengine("gpu") == "--disable-gpu-sandbox --no-sandbox"
    monkeypatch.delenv("QTWEBENGINE_CHROMIUM_FLAGS", raising=False)
    assert "--disable-gpu" in configure_webengine("software")
