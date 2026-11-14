"""Options kept between launches."""

import pytest
from PySide6.QtWidgets import QMessageBox

import DoorsTracker

TAB = "Turtle_Rock"


@pytest.mark.parametrize(
    "text", ["split_rooms: [not closed", "", "split_rooms: false\nsimulate: sometimes\n", "spacing: .nan\n", "spacing: .inf\n", "window: zz\n"]
)
def test_a_settings_file_that_cannot_be_used_is_reported_and_the_defaults_used(open_window, tmp_path, monkeypatch, text):
    file = tmp_path / "settings.yaml"
    file.write_text(text)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))

    window = open_window(file, size=None)
    assert window.settings == DoorsTracker.DEFAULT_SETTINGS | {"window": window.settings["window"]}
    # Hex that is no window geometry is not an error: the window takes its usual size
    assert len(warnings) == (0 if text.startswith("window") else 1)
    assert window.height() == DoorsTracker.WINDOW_SIZES["medium"][1]


def test_a_slider_value_outside_its_range_is_brought_into_it(open_window, tmp_path):
    file = tmp_path / "settings.yaml"
    file.write_text("spacing: 1.0e+300\ndead_end_pull: -7\n")
    window = open_window(file)
    assert (window.settings["spacing"], window.settings["dead_end_pull"]) == (200.0, 1.0)
    assert {(page.model.spacing, page.model.leaf_pull) for page in window.pages.values()} == {(200.0, 1.0)}


def test_options_changed_in_one_window_are_set_in_the_next(open_window, tmp_path):
    file = tmp_path / "settings.yaml"
    first = open_window(file)
    first.select_dungeon(TAB)
    first.boxes["follow_player"].click()
    first.boxes["auto_join"].click()
    first.sliders["spacing"].setValue(90)
    first.sliders["dead_end_pull"].setValue(15)
    first.set_option("split_rooms", False)
    first.resize(first.width(), 600)
    first.close()

    second = open_window(file, size=None)
    # Only the height: the test screen is narrower than the window can be, and Qt fits a restored window to the screen
    assert second.height() == 600
    assert second.current_dungeon() == TAB
    assert second.settings["split_rooms"] is False
    assert second.boxes["follow_player"].isChecked() and not second.boxes["auto_join"].isChecked()
    assert (second.sliders["spacing"].value(), second.sliders["dead_end_pull"].value()) == (90, 15)
    # The toolbar's settings are the same in every tab
    models = [page.model for page in second.pages.values()]
    assert {(model.auto_join, model.spacing, model.leaf_pull) for model in models} == {(False, 90.0, 1.5)}
