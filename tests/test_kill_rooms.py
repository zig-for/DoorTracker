"""Kill rooms: the rooms whose ways out, or whose chest, take killing the enemies in them."""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QToolButton

import DoorsTracker
from data.doors_sprite_data import REACHABLE
from gui.Doors import kill_rooms
from gui.Doors.graph_model import CheckState, DoorState
from gui.Doors.kill_rooms import KILL_ROOMS, NA, PICKS, clearing
from support import At, model_leading_to, new_model

# In the original game: a red mimic, which dies only to arrows, and two green ones
ROOM = "PoD Mimics 1"
RED = KILL_ROOMS[ROOM].enemies[0].number


def mimic_room(way_in):
    """A map of the room's supertile, with a way in at one of the room's doors."""
    model = new_model("Palace_of_Darkness")
    model.add_tile(KILL_ROOMS[ROOM].tile, has_been_lit=True)
    model.annotate(way_in, REACHABLE, [])
    return model


def test_everything_an_enemy_can_be_picked_as_has_a_picture():
    assert {file.stem for file in kill_rooms.PICTURES.glob("*.png")} == set(PICKS)


def test_a_kind_left_out_as_the_twin_of_another_takes_the_same_to_kill():
    room = "Ice Jelly Key"  # three enemies
    for twin, kind in kill_rooms.TWINS.items():
        assert clearing(room, (twin,) * 3) == clearing(room, (kind,) * 3)


def test_the_one_kind_is_drawn_as_a_mimic_in_a_mimic_room_and_as_an_eyegore_elsewhere():
    def drawn(room):
        model = new_model()
        model.add_tile(KILL_ROOMS[room].tile, has_been_lit=True)
        return [(spot.kind, spot.picture) for node in model.nodes() for spot in model.enemy_spots(node) if spot.room == room]

    assert drawn(ROOM) == [("RedEyegoreMimic", "RedMimic"), ("GreenEyegoreMimic", "GreenMimic"), ("GreenEyegoreMimic", "GreenMimic")]
    assert drawn("Eastern Single Eyegore")[0] == ("RedEyegoreMimic", "RedEyegoreMimic")


def test_killing_a_rooms_enemies_takes_what_the_randomizer_says_it_does():
    def original(room):
        return clearing(room, tuple(enemy.original for enemy in KILL_ROOMS[room].enemies))

    assert original(ROOM) == "Bow"
    # A Terrorpin has to be flipped with the hammer, and a Stalfos Knight bombed
    assert original("PoD Turtle Party") == "Hammer"
    assert original("Ice Stalfos Hint") == "Bombs"
    # Nothing in the tile room has to be killed: a seed with enemies shuffled can put something there that does
    assert original("GT Tile Room") is True
    assert clearing("GT Tile Room", ("Terrorpin", NA)) == "Hammer"


def test_a_kill_rooms_way_out_takes_killing_the_enemies_it_has():
    model = mimic_room("PoD Mimics 1 SW")
    way = "PoD Mimics 1 NW"
    model.set_items(frozenset({"Fighter Sword"}))
    assert model.door_state(way) is DoorState.BLOCKED
    model.set_items(frozenset({"Bow"}))
    assert model.door_state(way) is DoorState.OPEN
    # A seed with enemies shuffled has something else there: a Stalfos dies to the sword, as the green ones do
    model.set_items(frozenset({"Fighter Sword"}))
    model.set_enemy(ROOM, RED, "Stalfos")
    assert model.door_state(way) is DoorState.OPEN
    model.set_enemy(ROOM, RED, None)
    assert model.door_state(way) is DoorState.BLOCKED


def test_a_door_a_seed_can_make_a_trap_door_takes_killing_them_once_marked_as_one():
    way = "Eastern Single Eyegore ES"
    model = new_model("Eastern_Palace")
    model.add_tile(KILL_ROOMS["Eastern Single Eyegore"].tile, has_been_lit=True)
    model.annotate("Eastern Single Eyegore NE", REACHABLE, [])
    model.set_items(frozenset())
    assert model.door_state(way) is DoorState.OPEN
    model.annotate(way, "Trap Door", [])
    assert model.door_state(way) is DoorState.BLOCKED


def test_a_kill_rooms_chest_takes_killing_its_enemies():
    name = "Castle Tower - Room 03"
    model = model_leading_to(name, "Castle_Tower")
    model.set_items(frozenset())
    assert model.check_state(name) is CheckState.BLOCKED
    model.set_items(frozenset({"Fighter Sword"}))
    assert model.check_state(name) is CheckState.OPEN


def test_the_enemies_picked_are_saved_and_go_with_their_supertile():
    model = mimic_room("PoD Mimics 1 SW")
    model.set_enemy(ROOM, RED, "Stalfos")
    loaded = new_model("Palace_of_Darkness")
    loaded.load(model.save())
    assert loaded.enemies == {(ROOM, RED): "Stalfos"}
    assert loaded.remove_tile(KILL_ROOMS[ROOM].tile) is True
    assert loaded.enemies == {}


def test_an_enemy_is_named_on_hover_and_its_kind_picked_by_clicking(window, app, monkeypatch):
    window.select_dungeon("Palace_of_Darkness")
    page = window.pages["Palace_of_Darkness"]
    page.model.add_tile(KILL_ROOMS[ROOM].tile, has_been_lit=True)
    page.rebuild()
    page.fit_view()
    app.processEvents()
    node = next(n for n in page.model.nodes() if any(spot.room == ROOM for spot in page.model.enemy_spots(n)))
    spot = next(spot for spot in page.model.enemy_spots(node) if (spot.room, spot.number) == (ROOM, RED))
    x, y = page.model.pos[node]
    on_it = page.view.mapFromScene(QPointF(x + spot.x, y + spot.y))
    viewport = page.view.viewport()

    page.set_hover(page.hit_at(At(on_it)))
    assert page.status.text() == f"{ROOM}: RedEyegoreMimic"
    # A click picks its kind, and a right click goes back to the original game's
    monkeypatch.setattr(window, "pick_enemy", lambda: NA)
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=on_it)
    assert page.model.enemies == {(ROOM, RED): NA}
    page.set_hover(page.hit_at(At(on_it)))
    assert page.status.text() == f"{ROOM}: {NA}"
    QTest.mouseClick(viewport, Qt.MouseButton.RightButton, pos=on_it)
    assert page.model.enemies == {}


def test_the_enemy_picker_has_every_kind_and_na(window):
    picker = DoorsTracker.EnemyPicker(window, window.assets)
    buttons = {button.objectName(): button for button in picker.findChildren(QToolButton)}
    assert set(buttons) == {*PICKS, NA}
    assert not [pick for pick in PICKS if buttons[pick].icon().isNull()]
    buttons["Stalfos"].click()
    assert picker.choice == "Stalfos"
