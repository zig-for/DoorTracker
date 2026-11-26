"""Checks drawn on the cards."""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from data.doors_data import regions_to_doors
from data.doors_sprite_data import REACHABLE
from gui.Doors.checks import checks
from gui.Doors.graph_model import CHECKS_BY_TILE, CheckState, DoorState
from gui.Doors.logic import HEARTS, ITEMS_AT, ITEMS_LENGTH, ORANGE, READABLE, holds, items_held, with_hearts
from gui.Doors.rooms import DOORS, SPLIT, Node
from gui.Doors.rules import check_regions, check_rules, passage_rules
from gui.qt.style import BLOCKED, DOOR_OPEN
from support import At, model_leading_to, new_model


def test_every_check_is_drawn_on_exactly_one_part_of_its_supertile():
    model = new_model()
    for tile, names in CHECKS_BY_TILE.items():
        drawn = [spot.name for part in range(SPLIT.part_count(tile)) for spot in model.check_spots(Node(*tile, part))]
        assert sorted(drawn) == sorted(names), tile


def test_a_check_is_drawn_on_the_part_its_region_is_in():
    model = new_model()
    for name, check in checks.items():
        doors = [door for door in regions_to_doors.get(check_regions[name], ()) if door in DOORS and DOORS[door].tile == check["tile"]]
        if doors:
            assert name in [spot.name for spot in model.check_spots(SPLIT.node(doors[0]))], name


def test_a_passage_that_takes_a_lever_opens_once_the_lever_can_be_reached():
    # The chests are down a ladder that is under water until the swamp is drained
    name = "Swamp Palace - Flooded Room - Left"
    model = new_model("Swamp_Palace")
    model.add_tile(checks[name]["tile"], has_been_lit=True)
    model.add_lobby_door("Swamp Flooded Room Up Stairs", "Swamp_Palace")
    model.update()
    model.set_items(frozenset({"Flippers", "Hookshot", "Hammer"}))
    assert model.check_state(name) is CheckState.BLOCKED
    # A way to the part of the room with the lever
    model.add_lobby_door("Swamp Drain Right Up Stairs", "Swamp_Palace")
    model.update()
    assert model.check_state(name) is CheckState.OPEN


def test_items_are_read_from_the_save_data():
    save = bytearray(ITEMS_LENGTH)
    # Hammer, mitts, a swordless seed's sword byte, the red shield, red boomerang, something in the second bottle,
    # bombs, five hearts, and the big keys of Thieves' Town and Turtle Rock
    equipment = {0x34B: 1, 0x354: 2, 0x359: 0xFF, 0x35A: 2, 0x38C: 0x40, 0x35D: 3, 0x370: 10, 0x36C: 0x28, 0x366: 0x18}
    for address, value in equipment.items():
        save[address - ITEMS_AT] = value
    held = {"Hammer", "Power Glove", "Titans Mitts", "Blue Shield", "Red Shield", "Red Boomerang", "Bottle", "Bombs"}
    assert items_held(bytes(save)) == held | {"Big Key (Thieves Town)", "Big Key (Turtle Rock)"} | set(HEARTS[:5])
    # The game's progress, at what it is once Zelda is in the sanctuary
    save[0x3C5 - ITEMS_AT] = 2
    assert "Zelda Delivered" in items_held(bytes(save))


def test_a_check_is_blocked_until_the_item_its_rule_names_is_held():
    name = "Thieves' Town - Big Chest"
    model = model_leading_to(name, "Thieves_Town")
    model.set_items(frozenset({"Big Key (Thieves Town)"}))
    assert model.check_state(name) is CheckState.BLOCKED
    model.set_items(frozenset({"Big Key (Thieves Town)", "Hammer"}))
    assert model.check_state(name) is CheckState.OPEN


def test_a_check_can_take_a_number_of_hearts():
    # The chest is across spikes: four hearts to walk them, or something that keeps the player from harm
    name = "Misery Mire - Spike Chest"
    model = model_leading_to(name, "Misery_Mire")
    model.set_items(with_hearts(frozenset(), 3))
    assert model.check_state(name) is CheckState.BLOCKED
    model.set_items(with_hearts(frozenset(), 4))
    assert model.check_state(name) is CheckState.OPEN
    model.set_items(frozenset({"Cape"}))
    assert model.check_state(name) is CheckState.OPEN


def test_a_big_chest_takes_the_big_key_of_the_tab_it_is_on():
    name = "Eastern Palace - Big Chest"
    for tab, key in (("Eastern_Palace", "Big Key (Eastern Palace)"), ("Hyrule_Castle", "Big Key (Escape)")):
        model = model_leading_to(name, tab)
        model.set_items(frozenset({"Big Key (Desert Palace)"}))
        assert model.check_state(name) is CheckState.BLOCKED, tab
        model.set_items(frozenset({key}))
        assert model.check_state(name) is CheckState.OPEN, tab


def test_a_check_past_a_door_marked_as_a_big_key_door_is_blocked_until_the_big_key_is_held():
    # The chest is down the stairs from the lobby
    name = "Tower of Hera - Big Key Chest"
    model = new_model("Tower_of_Hera")
    model.add_tile(checks[name]["tile"], has_been_lit=True)
    model.add_lobby_door("Hera Lobby S", "Tower_of_Hera")
    model.add_link("Hera Lobby Key Stairs", "Hera Tile Room Up Stairs")
    without = frozenset(READABLE - {"Big Key (Tower of Hera)"})
    model.set_items(without)
    assert model.check_state(name) is CheckState.OPEN
    model.annotate("Hera Lobby Key Stairs", "Big Key Door", [])
    assert model.check_state(name) is CheckState.BLOCKED
    model.set_items(without | {"Big Key (Tower of Hera)"})
    assert model.check_state(name) is CheckState.OPEN
    # The mark is for its own side of the door
    model.set_items(without)
    model.remove_annotation("Hera Lobby Key Stairs")
    model.annotate("Hera Tile Room Up Stairs", "Big Key Door", [])
    assert model.check_state(name) is CheckState.OPEN


def test_the_switch_rooms_door_takes_the_cane_or_the_block_dropped_from_above():
    door = "Ice Switch Room SE"
    model = new_model("Ice_Palace")
    for name in (door, "Ice Crystal Right ES", "Ice Refill WS"):
        model.add_tile(DOORS[name].tile, has_been_lit=True)
    model.add_lobby_door("Ice Switch Room ES", "Ice_Palace")
    model.update()
    model.set_items(frozenset())
    assert model.door_state(door) is DoorState.BLOCKED
    model.set_items(frozenset({"Cane of Somaria"}))
    assert model.door_state(door) is DoorState.OPEN
    # A way to the room the block is pushed down from, which is behind its blue barrier, and on to a crystal switch
    # with something to hit it
    model.set_items(frozenset({"Hookshot"}))
    model.add_lobby_door("Ice Crystal Right ES", "Ice_Palace_2")
    model.update()
    assert model.door_state(door) is DoorState.BLOCKED
    model.add_link("Ice Crystal Left WS", "Ice Refill WS")
    assert model.door_state(door) is DoorState.OPEN


def test_a_door_marked_as_a_trap_door_takes_what_the_randomizer_has_for_it_as_one():
    door = "Ice Switch Room ES"
    model = new_model("Ice_Palace")
    model.add_tile(DOORS[door].tile, has_been_lit=True)
    model.add_lobby_door("Ice Switch Room SE", "Ice_Palace")
    model.update()
    model.set_items(frozenset())
    assert model.door_state(door) is DoorState.OPEN
    model.annotate(door, "Trap Door", [])
    assert model.door_state(door) is DoorState.BLOCKED
    model.set_items(frozenset({"Cane of Somaria"}))
    assert model.door_state(door) is DoorState.OPEN


def test_a_door_marked_as_a_trap_door_is_no_way_out_unless_it_is_one_in_the_randomizer():
    model = new_model("Eastern_Palace")
    model.add_tile(DOORS["Eastern Cannonball N"].tile, has_been_lit=True)
    model.add_lobby_door("Eastern Cannonball S", "Eastern_Palace")
    model.update()
    model.set_items(frozenset(READABLE))
    model.annotate("Eastern Cannonball N", "Trap Door", [])
    assert model.door_state("Eastern Cannonball N") is DoorState.BLOCKED
    # One of the original game's trap doors, which opens
    model = new_model("Eastern_Palace")
    model.add_tile(DOORS["Eastern Lobby Bridge N"].tile, has_been_lit=True)
    model.add_lobby_door("Eastern Lobby Bridge S", "Eastern_Palace")
    model.update()
    model.set_items(frozenset(READABLE))
    model.annotate("Eastern Lobby Bridge N", "Trap Door", [])
    assert model.door_state("Eastern Lobby Bridge N") is DoorState.OPEN


def test_a_door_marked_as_a_bomb_or_dash_door_takes_what_opens_one():
    door = "Eastern Cannonball N"
    model = new_model("Eastern_Palace")
    model.add_tile(DOORS[door].tile, has_been_lit=True)
    model.add_lobby_door("Eastern Cannonball S", "Eastern_Palace")
    model.update()
    for mark, opened_by in (("Bomb Door", [{"Bombs"}]), ("Dash Door", [{"Bombs"}, {"Pegasus Boots"}])):
        model.annotate(door, mark, [])
        model.set_items(frozenset())
        assert model.door_state(door) is DoorState.BLOCKED, mark
        for items in opened_by:
            model.set_items(frozenset(items))
            assert model.door_state(door) is DoorState.OPEN, (mark, items)


def test_the_way_past_ganons_towers_middle_boss_takes_the_cape_when_it_is_trinexx():
    # The supertile's rooms are in a row, joined by doors inside it: GT Quad Pot SW leads to the boss, and past the
    # boss is the room this door is in
    past = "GT Beam Dash ES"
    model = new_model("Ganons_Tower")
    model.add_tile(DOORS[past].tile, has_been_lit=True)
    model.add_lobby_door("GT Quad Pot Up Stairs", "Ganons_Tower")
    model.update()
    without = frozenset(READABLE - {"Cape"})
    model.set_items(without)
    assert model.door_state(past) is DoorState.OPEN
    model.set_boss(DOORS[past].tile, "Trinexx")
    assert model.door_state(past) is DoorState.BLOCKED
    model.set_items(without | {"Cape"})
    assert model.door_state(past) is DoorState.OPEN


def test_the_chests_in_the_two_cells_take_the_big_key():
    cells = (
        ("Thieves' Town - Blind's Cell", "Thieves_Town", "Thieves Blind's Cell WS", "Big Key (Thieves Town)"),
        ("Hyrule Castle - Zelda's Chest", "Hyrule_Castle", "Hyrule Dungeon Cellblock Up Stairs", "Big Key (Escape)"),
    )
    for name, tab, way_in, key in cells:
        model = new_model(tab)
        model.add_tile(checks[name]["tile"], has_been_lit=True)
        model.add_lobby_door(way_in, tab)
        model.update()
        assert model.check_state(name) is CheckState.BLOCKED, name
        model.set_items(frozenset({key}))
        assert model.check_state(name) is CheckState.OPEN, name


def test_the_throne_rooms_tapestry_is_closed_in_a_standard_seed_until_zelda_can_be_fetched():
    behind = "Hyrule Castle Throne Room N"
    model = new_model("Hyrule_Castle")
    model.add_tile(DOORS[behind].tile, has_been_lit=True)
    model.add_lobby_door("Hyrule Castle Throne Room South Stairs", "Hyrule_Castle")
    model.update()
    # No game has been read: the seed is not taken as standard
    assert model.door_state(behind) is DoorState.OPEN
    # A standard seed's game, before Zelda is delivered
    model.set_items(frozenset())
    assert model.door_state(behind) is DoorState.BLOCKED
    # A way to her cell, and then the big key that opens it
    model.add_tile(checks["Hyrule Castle - Zelda's Chest"]["tile"], has_been_lit=True)
    model.add_lobby_door("Hyrule Dungeon Cellblock Up Stairs", "Hyrule_Castle")
    model.update()
    assert model.door_state(behind) is DoorState.BLOCKED
    model.set_items(frozenset({"Big Key (Escape)"}))
    assert model.door_state(behind) is DoorState.OPEN


def test_an_unlinked_door_is_unrouted_until_the_map_leads_to_it_and_blocked_until_the_player_can_go_out_by_it():
    # Every way out of the hub is by the cane's platform
    door = "TR Hub NE"
    model = new_model("Turtle_Rock")
    model.add_tile(DOORS[door].tile, has_been_lit=True)
    model.update()
    # Nothing leads to the room yet
    assert model.door_state(door) is DoorState.UNROUTED
    model.add_lobby_door("TR Hub SW", "Turtle_Rock")
    model.update()
    assert model.door_state(door) is DoorState.BLOCKED
    model.set_items(frozenset({"Cane of Somaria"}))
    assert model.door_state(door) is DoorState.OPEN


def test_a_door_on_screen_changes_colour_when_the_items_held_do(window, app):
    door = "TR Hub NE"
    window.select_dungeon("Turtle_Rock")
    page = window.pages["Turtle_Rock"]
    page.model.add_tile(DOORS[door].tile, has_been_lit=True)
    page.model.add_lobby_door("TR Hub SW", "Turtle Rock Main")
    page.model.update()
    page.rebuild()
    page.fit_view()
    app.processEvents()

    def colour():
        middle = page.view.mapFromScene(QPointF(*page.model.port(door)))
        return page.view.grab().toImage().pixelColor(middle).name()

    assert colour() == BLOCKED
    window.set_held(frozenset({"Cane of Somaria"}), {})
    assert colour() == DOOR_OPEN


def test_a_check_past_a_passage_is_blocked_until_the_item_for_the_passage_is_held():
    # The chest is across the moat from the lobby
    name = "Swamp Palace - Entrance"
    model = new_model("Swamp_Palace")
    model.add_tile(checks[name]["tile"], has_been_lit=True)
    model.add_lobby_door("Swamp Lobby S", "Swamp_Palace")
    model.update()
    # The sword is for the enemies by the chest, which it takes killing
    model.set_items(frozenset({"Fighter Sword"}))
    assert model.check_state(name) is CheckState.BLOCKED
    model.set_items(frozenset({"Fighter Sword", "Flippers"}))
    assert model.check_state(name) is CheckState.OPEN


def test_a_check_the_map_does_not_lead_to_is_unrouted():
    name = "Ganons Tower - Validation Chest"
    model = new_model("Ganons_Tower")
    model.add_tile(checks[name]["tile"], has_been_lit=True)
    model.update()
    # A room being on the map is no way to it
    assert model.check_state(name) is CheckState.UNROUTED
    # Nor is this door, the way out of the chest's room: the chest is only reached across the gap from Moldorm
    model.add_lobby_door("GT Validation WS", "Ganons_Tower")
    model.update()
    assert model.check_state(name) is CheckState.UNROUTED


def test_a_door_marked_as_somewhere_the_player_can_get_to_is_a_way_in():
    name = "Swamp Palace - Entrance"
    model = new_model("Swamp_Palace")
    model.add_tile(checks[name]["tile"], has_been_lit=True)
    model.update()
    # For the enemies by the chest, which it takes killing
    model.set_items(frozenset({"Fighter Sword"}))
    assert model.check_state(name) is CheckState.UNROUTED
    model.annotate(next(door for door in regions_to_doors[check_regions[name]] if door in DOORS), REACHABLE, [])
    assert model.check_state(name) is CheckState.OPEN


def test_a_boss_rooms_drops_take_beating_the_boss_picked_for_it():
    name = "Eastern Palace - Boss"
    tile = checks[name]["tile"]
    model = new_model("Eastern_Palace")
    model.add_tile(tile, has_been_lit=True)
    model.add_lobby_door(next(door for door in regions_to_doors["Eastern Boss"] if door in DOORS), "Eastern")
    model.update()
    model.set_items(frozenset())
    # A boss not picked counts as beaten
    assert model.check_state(name) is CheckState.OPEN and model.can_beat_boss(tile)
    model.set_boss(tile, "Moldorm")
    assert model.check_state(name) is CheckState.BLOCKED and not model.can_beat_boss(tile)
    model.set_items(frozenset({"Hammer"}))
    assert model.check_state(name) is CheckState.OPEN and model.can_beat_boss(tile)


def test_blind_in_thieves_town_is_only_there_once_the_maiden_is_unmasked():
    name = "Thieves' Town - Boss"
    tile = checks[name]["tile"]
    model = new_model("Thieves_Town")
    model.add_tile(tile, has_been_lit=True)
    model.add_lobby_door(next(door for door in regions_to_doors["Thieves Boss"] if door in DOORS), "Thieves Town")
    model.update()
    # A weapon that beats him, and no way to have unmasked the maiden: that is done elsewhere in the dungeon
    model.set_items(frozenset({"Hammer"}))
    model.set_boss(tile, "Blind")
    assert model.check_state(name) is CheckState.BLOCKED
    # Any other boss is just fought
    model.set_boss(tile, "Moldorm")
    assert model.check_state(name) is CheckState.OPEN


def test_a_check_the_map_does_not_lead_to_that_takes_an_item_not_held_is_both():
    name = "Thieves' Town - Big Chest"
    model = new_model("Thieves_Town")
    model.add_tile(checks[name]["tile"], has_been_lit=True)
    model.update()
    model.set_items(frozenset())
    assert model.check_state(name) is CheckState.UNROUTED_BLOCKED


def test_a_fall_is_not_a_way_back_up():
    # The chest is in the room with the hole; the entrance is in the room the hole lands in
    name = "Ice Palace - Freezor Chest"
    for fall in (("Ice Freezors Hole", "Ice Big Chest View Drop Entrance"), ("Ice Big Chest View Drop Entrance", "Ice Freezors Hole")):
        model = new_model("Ice_Palace")
        model.add_tile(checks[name]["tile"], has_been_lit=True)
        model.add_lobby_door("Ice Big Chest View ES", "Ice_Palace")
        model.set_items(frozenset({"Fire Rod"}))  # to melt the freezor
        # A fall the tracker saw is kept as a link, either way round
        model.add_link(*fall)
        assert model.check_state(name) is CheckState.UNROUTED, fall


def test_a_hole_leads_where_it_did_only_when_drops_are_not_shuffled():
    # The chest is where the pit room's freefall lands in the original game
    name = "Palace of Darkness - Stalfos Basement"
    for as_they_were, state in ((True, CheckState.OPEN), (False, CheckState.UNROUTED)):
        model = new_model("Palace_of_Darkness", vanilla_drops=as_they_were)
        model.add_tile(checks[name]["tile"], has_been_lit=True)
        model.add_lobby_door("PoD Pit Room NE", "Palace_of_Darkness")
        model.update()
        assert model.check_state(name) is state, as_they_were


def test_a_crystal_barrier_is_passed_once_its_switch_can_be_hit():
    # The chest is past pegs that are up when a dungeon is entered; the switch is in the same room
    name = "Tower of Hera - Map Chest"
    model = new_model("Tower_of_Hera")
    model.add_tile(checks[name]["tile"], has_been_lit=True)
    model.add_lobby_door("Hera Lobby S", "Tower_of_Hera")
    model.update()
    model.set_items(frozenset())
    assert model.check_state(name) is CheckState.BLOCKED
    model.set_items(frozenset({"Fighter Sword"}))
    assert model.check_state(name) is CheckState.OPEN


def test_how_the_crystal_barriers_are_left_is_carried_into_the_next_room():
    # The way to the chest in the basement is past pegs whose switch is in the lobby above
    name = "Tower of Hera - Big Key Chest"
    alone = new_model("Tower_of_Hera")
    alone.add_tile(checks[name]["tile"], has_been_lit=True)
    alone.add_lobby_door("Hera Tile Room Up Stairs", "Tower_of_Hera")
    alone.update()
    alone.set_items(frozenset(READABLE))
    assert alone.check_state(name) is CheckState.BLOCKED

    below_the_lobby = new_model("Tower_of_Hera")
    below_the_lobby.add_tile(checks[name]["tile"], has_been_lit=True)
    below_the_lobby.add_lobby_door("Hera Lobby S", "Tower_of_Hera")
    below_the_lobby.add_link("Hera Lobby Key Stairs", "Hera Tile Room Up Stairs")
    below_the_lobby.set_items(frozenset(READABLE))
    assert below_the_lobby.check_state(name) is CheckState.OPEN


def test_a_rule_can_ask_for_a_region_reached_or_for_something_not_done():
    # The dry way through the trench is there until it is filled, or with a way to hit the crystal switch
    dry = passage_rules["Swamp Trench 2 Pots Dry"]
    assert holds(dry, frozenset())
    assert not holds(dry, frozenset({"Trench 2 Filled"}))
    # The chain chomps' chest is hit from below, which takes having got to the room above it
    chomps = check_rules["Turtle Rock - Chain Chomps"]
    assert not holds(chomps, frozenset({"Bombs"}), {})
    assert holds(chomps, frozenset({"Bombs"}), {"TR Chain Chomps Top": ORANGE})


def test_a_drop_is_no_way_in_until_the_player_has_used_it_or_says_so():
    # The secret room's chests, in the room the sewer drop lands in, with no other way to it on the map
    name = "Sewers - Secret Room - Left"
    model = new_model("Hyrule_Castle")
    assert model.assumed("Sewer Drop")
    assert model.check_state(name) is CheckState.UNROUTED

    model.set_entrance_used("Sewer Drop", True)
    assert model.check_state(name) is CheckState.OPEN
    model.set_entrance_used("Sewer Drop", False)
    assert model.check_state(name) is CheckState.UNROUTED

    # Being seen in the drop's supertile is not using the drop, nor is coming in by the stairs at its top, behind
    # blocks that only push the other way
    tile = checks[name]["tile"]
    model.move_player(tile, 400, 290)
    model.arrive("Sewers Secret Room Up Stairs")
    assert model.assumed("Sewer Drop")
    # Falling into the dungeon there is
    model.dropped_in(tile, 400, 290)
    assert not model.assumed("Sewer Drop")
    assert model.check_state(name) is CheckState.OPEN
    # and that is kept with the map
    reloaded = new_model("Hyrule_Castle")
    reloaded.load(model.save())
    assert reloaded.check_state(name) is CheckState.OPEN


def test_clicking_a_drops_marker_says_the_player_can_use_it(window, app):
    window.select_dungeon("Hyrule_Castle")
    page = window.pages["Hyrule_Castle"]
    page.fit_view()
    app.processEvents()
    model = page.model
    x, y = model.port("Sewer Drop")
    marker = page.view.mapFromScene(QPointF(x, y))
    assert page.hit_at(At(marker)).icon == "Sewer Drop"

    # A click says it can be used, a right click takes that back; a second click changes nothing
    viewport = page.view.viewport()
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=marker)
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=marker)
    assert not model.assumed("Sewer Drop")
    QTest.mouseClick(viewport, Qt.MouseButton.RightButton, pos=marker)
    assert model.assumed("Sewer Drop")


def test_a_check_is_named_on_hover_and_collected_by_clicking(window, app):
    name = "Eastern Palace - Compass Chest"
    tile = checks[name]["tile"]
    window.select_dungeon("Eastern_Palace")
    page = window.pages["Eastern_Palace"]
    page.model.add_tile(tile, has_been_lit=True)
    page.rebuild()
    page.fit_view()
    app.processEvents()
    node = next(n for n in page.model.nodes() if any(spot.name == name for spot in page.model.check_spots(n)))
    spot = next(spot for spot in page.model.check_spots(node) if spot.name == name)
    x, y = page.model.pos[node]
    on_it = page.view.mapFromScene(QPointF(x + spot.x, y + spot.y))
    viewport = page.view.viewport()

    page.set_hover(page.hit_at(At(on_it)))
    assert page.status.text() == name
    # A click collects it, a right click takes that back; a second click changes nothing
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=on_it)
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=on_it)
    assert window.collected == {name}
    page.set_hover(page.hit_at(At(on_it)))
    assert page.status.text() == f"{name}   (collected)"
    QTest.mouseClick(viewport, Qt.MouseButton.RightButton, pos=on_it)
    assert window.collected == set()
