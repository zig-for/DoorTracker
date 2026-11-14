"""Options kept between launches."""

TAB = "Turtle_Rock"


def test_options_changed_in_one_window_are_set_in_the_next(open_window, tmp_path):
    file = tmp_path / "settings.yaml"
    first = open_window(file)
    first.select_dungeon(TAB)
    first.pages[TAB].follow_box.click()
    first.pages[TAB].join_box.click()
    first.set_option("split_rooms", False)
    first.resize(first.width(), 600)

    # A toolbar checkbox is the same in every tab
    assert all(page.follow_box.isChecked() for page in first.pages.values())
    first.close()

    second = open_window(file, size=None)
    # Only the height: the test screen is narrower than the window can be, and Qt fits a restored window to the screen
    assert second.height() == 600
    assert second.current_dungeon() == TAB
    assert second.settings["split_rooms"] is False
    assert all(page.follow_box.isChecked() for page in second.pages.values())
    assert not any(page.join_box.isChecked() or page.model.auto_join for page in second.pages.values())
