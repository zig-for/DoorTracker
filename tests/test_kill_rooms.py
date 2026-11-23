"""Kill rooms: the rooms whose ways out, or whose chest, take killing the enemies in them."""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QToolButton

import DoorsTracker
from data.doors_sprite_data import REACHABLE, dungeon_lobbies
from gui.Doors import kill_rooms
from gui.Doors.graph_model import CHECK_SIZE, ENEMY_SIZE, CheckState, DoorState
from gui.Doors.kill_rooms import KILL_ROOMS, NA, PICKS, ROOMS_BY_TILE, clearing
from gui.Doors.logic import holds
from gui.Doors.rules import boss_rules
from support import At, model_leading_to, new_model

# In the original game: a red mimic, which dies only to arrows, and two green ones
ROOM = "PoD Mimics 1"
RED = KILL_ROOMS[ROOM].enemies[0].number


def mimic_room(way_in, **flags):
    """A map of the room's supertile, with a way in at one of the room's doors."""
    model = new_model("Palace_of_Darkness", **flags)
    model.add_tile(KILL_ROOMS[ROOM].tile, has_been_lit=True)
    model.annotate(way_in, REACHABLE, [])
    return model


def test_everything_an_enemy_can_be_picked_as_has_a_picture():
    assert {file.stem for file in kill_rooms.PICTURES.glob("*.png")} == set(PICKS)


def test_a_kind_left_out_as_the_twin_of_another_takes_the_same_to_kill():
    room = "Ice Jelly Key"  # three enemies
    for twin, kind in kill_rooms.TWINS.items():
        assert clearing(room, (twin,) * 3) == clearing(room, (kind,) * 3)


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


def test_an_enemy_with_less_health_in_one_world_is_taken_as_having_the_less():
    # A dungeon's rooms are in whichever world the seed joins them to. Five Ravens take five bombs in the light
    # world and ten in the dark, where a room's are eight at the most
    assert holds(clearing("Desert Four Statues", ("Raven",) * 5), frozenset({"Bombs"}))


def test_a_kill_rooms_door_that_is_a_way_in_to_the_dungeon_takes_no_killing():
    model = new_model("Ganons_Tower")
    way = "GT DMs Room SW"
    model.add_tile(KILL_ROOMS["GT DMs Room"].tile, has_been_lit=True)
    model.set_items(frozenset())
    assert model.door_state(way) is DoorState.BLOCKED
    lobbies = dungeon_lobbies[model.tab_world]
    model.annotate(way, next(iter(lobbies)), lobbies)
    assert model.door_state(way) is DoorState.LINKED


def test_no_enemy_is_drawn_over_a_check():
    model = new_model("Ganons_Tower", enemy_shuffle=True)
    for tile in ROOMS_BY_TILE:
        model.add_tile(tile, has_been_lit=True)
    apart = (ENEMY_SIZE + CHECK_SIZE) / 2
    for node in model.nodes():
        for enemy in model.enemy_spots(node):
            for check in model.check_spots(node):
                assert abs(enemy.x - check.x) >= apart or abs(enemy.y - check.y) >= apart, (enemy.room, check.name)


def test_a_click_on_an_enemy_beside_a_check_is_on_the_enemy_however_far_out_the_view_is(window, app):
    room = "Hyrule Dungeon Armory Boomerang"  # its enemy is the one that drops a key
    window.select_dungeon("Hyrule_Castle")
    page = window.pages["Hyrule_Castle"]
    page.model.add_tile(KILL_ROOMS[room].tile, has_been_lit=True)
    window.set_option("enemy_shuffle", True)
    page.fit_view()
    app.processEvents()
    # Far out, a check is clicked from further off than its square reaches
    page.view.zoom_at(page.view.rect().center(), 0.5 / page.view.zoom())
    node, spot = next((n, s) for n in page.model.nodes() for s in page.model.enemy_spots(n) if s.room == room)
    x, y = page.model.pos[node]
    assert page.hit_at(At(page.view.mapFromScene(QPointF(x + spot.x, y + spot.y)))).enemy == (room, spot.number)


def test_a_way_of_killing_that_takes_more_magic_than_one_bar_takes_enough_magic():
    # Five Pengators: ten shots of the fire rod, where a bar is eight
    rule = clearing("Ice Pengator Trap", ("Pengator",) * 5)
    assert not holds(rule, frozenset({"Fire Rod"}))
    assert holds(rule, frozenset({"Fire Rod", "Bottle"}))
    assert holds(rule, frozenset({"Fire Rod", "Magic Upgrade (1/2)"}))
    # Four take eight
    assert holds(clearing("Ice Pengator Trap", ("Pengator",) * 4 + (NA,)), frozenset({"Fire Rod"}))


def test_a_boss_that_takes_more_magic_than_one_bar_takes_enough_magic():
    # With the fire rod alone: twenty shots of it
    usual, _on_ice = boss_rules["Kholdstare"]
    assert not holds(usual, frozenset({"Fire Rod", "Bottle"}))
    assert holds(usual, frozenset({"Fire Rod", "Bottle", "2 Bottles"}))
    assert holds(usual, frozenset({"Fire Rod", "Magic Upgrade (1/2)", "Magic Upgrade (1/4)"}))


def test_a_kill_rooms_way_out_takes_killing_the_enemies_it_has():
    model = mimic_room("PoD Mimics 1 SW")
    way = "PoD Mimics 1 NW"
    model.set_items(frozenset({"Fighter Sword"}))
    assert model.door_state(way) is DoorState.BLOCKED
    model.set_items(frozenset({"Bow"}))
    assert model.door_state(way) is DoorState.OPEN


def test_with_enemies_shuffled_a_kill_room_takes_killing_the_enemies_picked_for_it():
    model = mimic_room("PoD Mimics 1 SW", enemy_shuffle=True)
    way = "PoD Mimics 1 NW"
    model.set_items(frozenset({"Fighter Sword"}))
    # Nothing is known of its enemies yet
    assert model.door_state(way) is DoorState.OPEN
    model.set_enemy(ROOM, RED, "RedMimic")
    assert model.door_state(way) is DoorState.BLOCKED
    model.set_enemy(ROOM, RED, "Stalfos")
    assert model.door_state(way) is DoorState.OPEN
    # What was picked is for a seed with enemies shuffled
    model.settings["enemy_shuffle"] = False
    model.update()
    assert model.door_state(way) is DoorState.BLOCKED


def test_only_the_enemies_the_items_do_not_kill_are_marked():
    model = new_model("Castle_Tower", enemy_shuffle=True)
    room = "Tower Gold Knights"
    first, second = (enemy.number for enemy in KILL_ROOMS[room].enemies)
    model.set_items(frozenset({"Fighter Sword", "Ice Rod"}))
    model.set_enemy(room, first, "RedMimic")
    model.set_enemy(room, second, "Stalfos")
    assert model.unkilled(room) == {first}
    # Each of these dies to what is held, but the randomizer's rule for the two together asks for more
    model.set_enemy(room, first, "Raven")
    model.set_enemy(room, second, "Buzzblob")
    assert model.unkilled(room) == {first, second}
    model.set_items(frozenset({"Bow"}))
    assert model.unkilled(room) == set()


def test_a_kill_rooms_door_inside_its_supertile_is_drawn_as_blocked_while_its_enemies_cannot_be_killed():
    model = new_model("Eastern_Palace")
    model.add_tile(KILL_ROOMS["Eastern Single Eyegore"].tile, has_been_lit=True)
    way = "Eastern Single Eyegore NE"
    model.set_items(frozenset({"Fighter Sword"}))
    assert model.door_state(way) is DoorState.BLOCKED
    model.set_items(frozenset({"Bow"}))
    assert model.door_state(way) is DoorState.INTERIOR


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
    window.set_option("enemy_shuffle", True)
    page.fit_view()
    app.processEvents()
    node = next(n for n in page.model.nodes() if any(spot.room == ROOM for spot in page.model.enemy_spots(n)))
    spot = next(spot for spot in page.model.enemy_spots(node) if (spot.room, spot.number) == (ROOM, RED))
    x, y = page.model.pos[node]
    on_it = page.view.mapFromScene(QPointF(x + spot.x, y + spot.y))
    viewport = page.view.viewport()

    page.set_hover(page.hit_at(At(on_it)))
    assert page.status.text() == f"{ROOM}: ?"
    # A click picks its kind, and a right click goes back to not known
    monkeypatch.setattr(window, "pick_enemy", lambda: NA)
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=on_it)
    assert page.model.enemies == {(ROOM, RED): NA}
    page.set_hover(page.hit_at(At(on_it)))
    assert page.status.text() == f"{ROOM}: {NA}"
    QTest.mouseClick(viewport, Qt.MouseButton.RightButton, pos=on_it)
    assert page.model.enemies == {}

    # In any other seed the enemy there is the original game's, which no click changes
    page.model.set_enemy(ROOM, RED, "Stalfos")
    window.set_option("enemy_shuffle", False)
    page.set_hover(page.hit_at(At(on_it)))
    assert page.status.text() == f"{ROOM}: RedEyegoreMimic"
    asked = []
    monkeypatch.setattr(window, "pick_enemy", lambda: asked.append(True))
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=on_it)
    QTest.mouseClick(viewport, Qt.MouseButton.RightButton, pos=on_it)
    assert not asked and page.model.enemies == {(ROOM, RED): "Stalfos"}


def test_without_enemies_shuffled_the_original_enemies_that_cannot_be_killed_are_drawn():
    model = new_model("Palace_of_Darkness")
    model.add_tile(KILL_ROOMS[ROOM].tile, has_been_lit=True)

    def drawn():
        return [(spot.kind, spot.picture) for node in model.nodes() for spot in model.enemy_spots(node) if spot.room == ROOM]

    # The game draws the kind as a mimic in this room, and as an Eyegore in Eastern Palace
    model.set_items(frozenset({"Fighter Sword"}))
    assert drawn() == [("RedEyegoreMimic", "RedMimic")]
    model.set_items(frozenset())
    assert drawn() == [("RedEyegoreMimic", "RedMimic"), ("GreenEyegoreMimic", "GreenMimic"), ("GreenEyegoreMimic", "GreenMimic")]
    model.set_items(frozenset({"Bow"}))
    assert drawn() == []


def test_the_enemies_on_screen_change_when_the_items_held_do(window, app):
    window.select_dungeon("Palace_of_Darkness")
    page = window.pages["Palace_of_Darkness"]
    page.model.add_tile(KILL_ROOMS[ROOM].tile, has_been_lit=True)
    page.rebuild()
    app.processEvents()
    node = next(n for n in page.model.nodes() if page.model.enemy_spots(n))

    def on_screen():
        return [enemy.picture for enemy in page._doors[node].enemies]

    assert on_screen() == ["RedMimic", "GreenMimic", "GreenMimic"]
    window.set_held(frozenset({"Fighter Sword"}), {})
    assert on_screen() == ["RedMimic"]
    window.set_held(frozenset({"Fighter Sword", "Bow"}), {})
    assert on_screen() == []
    window.set_held(frozenset(), {})
    assert on_screen() == ["RedMimic", "GreenMimic", "GreenMimic"]


def test_the_enemy_picker_has_every_kind_and_na(window):
    picker = DoorsTracker.EnemyPicker(window, window.assets)
    buttons = {button.objectName(): button for button in picker.findChildren(QToolButton)}
    assert set(buttons) == {*PICKS, NA}
    assert not [pick for pick in PICKS if buttons[pick].icon().isNull()]
    buttons["Stalfos"].click()
    assert picker.choice == "Stalfos"
