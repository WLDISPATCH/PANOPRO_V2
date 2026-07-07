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


def test_render_mode_tolerates_single_unclean_exit(render_state, monkeypatch):
    monkeypatch.delenv("PANOPRO_FORCE_GPU", raising=False)
    monkeypatch.delenv("PANOPRO_DISABLE_GPU", raising=False)
    resolve_render_mode(render_state)  # writes running sentinel
    # One unclean exit (sentinel left set) must NOT demote a healthy machine.
    assert resolve_render_mode(render_state) == "gpu"


def test_render_mode_falls_back_after_two_consecutive_crashes(render_state, monkeypatch):
    monkeypatch.delenv("PANOPRO_FORCE_GPU", raising=False)
    monkeypatch.delenv("PANOPRO_DISABLE_GPU", raising=False)
    resolve_render_mode(render_state)  # gpu, crashes=0
    resolve_render_mode(render_state)  # sentinel left -> gpu, crashes=1
    assert resolve_render_mode(render_state) == "software"  # crashes=2 -> sticky
    assert resolve_render_mode(render_state) == "software"


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
