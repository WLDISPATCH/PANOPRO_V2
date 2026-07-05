from __future__ import annotations

from pathlib import Path

from pano_namer.desktop import _load_last_picker_dir, _save_last_picker_dir, _selection_directory


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
