"""The map kept between launches."""

import yaml
from PySide6.QtTest import QTest

import DoorsTracker
from support import grow, positions

TAB = "Turtle_Rock"


def links(window):
    return [(x.door, x.linked_door) for x in window.pages[TAB].model.door_links]


def test_a_change_is_saved_and_the_next_window_gets_the_map_back(open_window, tmp_path, monkeypatch):
    monkeypatch.setattr(DoorsTracker, "SAVE_DELAY", 0)
    first = open_window()
    first.start_autosave(tmp_path, restore=True)
    first.seed_seen("0102030405")
    page = first.pages[TAB]
    grow(page.model, 3)
    page.model.toggle_expanded(page.model.nodes()[0])
    page.rebuild()
    QTest.qWait(50)

    # Saved by the change, before the window closes
    saved = yaml.safe_load((tmp_path / "autosave-0102030405.yaml").read_text())
    assert len(saved[TAB]["door_links"]) == 3

    second = open_window()
    second.start_autosave(tmp_path, restore=True)
    model = second.pages[TAB].model
    assert second.seed_hash == "0102030405"
    assert links(second) == links(first)
    assert model.kept_expanded == page.model.kept_expanded
    assert positions(model) == {node: (round(x, 1), round(y, 1)) for node, (x, y) in positions(page.model).items()}


def test_each_seed_keeps_its_own_map(window, tmp_path):
    window.start_autosave(tmp_path, restore=True)
    window.seed_seen("aaaaaaaaaa")
    grow(window.pages[TAB].model, 2)
    first_map = links(window)

    window.seed_seen("bbbbbbbbbb")
    assert links(window) == []
    grow(window.pages[TAB].model, 1)
    second_map = links(window)

    window.seed_seen("aaaaaaaaaa")
    assert links(window) == first_map
    window.seed_seen("bbbbbbbbbb")
    assert links(window) == second_map
