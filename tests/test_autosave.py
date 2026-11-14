"""The map kept between launches."""

import yaml
from PySide6.QtTest import QTest

import DoorsTracker
from support import grow, positions

TAB = "Turtle_Rock"


def test_a_change_is_saved_and_the_next_window_gets_the_map_back(open_window, tmp_path, monkeypatch):
    monkeypatch.setattr(DoorsTracker, "SAVE_DELAY", 0)
    file = tmp_path / "autosave.yaml"
    first = open_window()
    first.start_autosave(file, restore=True)
    page = first.pages[TAB]
    grow(page.model, 3)
    page.model.toggle_expanded(page.model.nodes()[0])
    page.rebuild()
    QTest.qWait(50)

    # Saved by the change, before the window closes
    assert len(yaml.safe_load(file.read_text())[TAB]["door_links"]) == 3

    second = open_window()
    second.start_autosave(file, restore=True)
    model = second.pages[TAB].model
    assert [(x.door, x.linked_door) for x in model.door_links] == [(x.door, x.linked_door) for x in page.model.door_links]
    assert model.kept_expanded == page.model.kept_expanded
    assert positions(model) == {node: (round(x, 1), round(y, 1)) for node, (x, y) in positions(page.model).items()}
