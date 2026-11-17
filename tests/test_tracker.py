"""The tracking loop in sni_tracker.py, run against a fake SNI that plays back memory readings."""

import argparse
import asyncio

import grpc

import DoorsTracker
import sni_tracker
from data.doors_data import dark_tiles, default_one_way_connections, door_coordinates, doors_data
from gui.Doors import link_sprite
from gui.Doors.checks import DROPS
from gui.Doors.logic import BITS, COMPASSES, ITEMS_AT, MAPS, STARTING_ITEMS
from gui.Doors.rooms import INTERIOR_DOORS, SUPERTILES
from support import VANILLA, a_rom, rom_reads

DUNGEON, TAB = "0c", "Palace_of_Darkness"
DARK_ROOM = (10, 11)


def door_facing(facing, avoid=None):
    """(supertile, door table entry) of a lit Palace of Darkness door facing this way, on layer 00."""
    for tile, entries in sorted(door_coordinates.items()):
        if tile in dark_tiles or tile == avoid:
            continue
        for entry in entries:
            name = entry["name"]
            if name.startswith("PoD") and name not in INTERIOR_DOORS and doors_data[name][1:3] == (facing, "00"):
                return tile, entry
    raise AssertionError(f"no {facing} door")


def reading(tile, x, y, lamp=True, transitioning=False, indoors=True, seed="0102030405", falling=False, dungeon=DUNGEON):
    """What the tracker reads from memory with the player at pixel (x, y) of a supertile."""

    def coordinate(supertile, pixel):
        half = 1 if pixel > 255 else 0
        return f"{pixel - half * 255:02x}{supertile * 2 + half:02x}"

    return {
        "race": "00",
        "seed_hash": seed,
        "gamemode": "07",
        "indoors": "01" if indoors else "00",
        "link_y": coordinate(tile[1], y),
        "link_x": coordinate(tile[0], x),
        "falling": "02" if falling else "00",
        "mirror": "00",
        "transitioning": "01" if transitioning else "00",
        "layer": "00",
        "dead": "00",
        "dungeon": dungeon,
        "lampcone": "01" if lamp else "00",
        "torches": "00",
        "dungeon_room": f"{tile[1] * 16 + tile[0]:02x}",
    }


class Reply:
    def __init__(self, **fields):
        self.__dict__.update(fields)


class PlaybackOver(grpc.aio.AioRpcError):
    def __init__(self):
        pass


def play(window, app, monkeypatch, steps, collected=(), equipment=None, rom=None, during_check_read=None, sprite=None):
    """Feed the readings to the real loop. Returns the map's state as it was before each labelled reading, and at the end.

    collected: (table, room, mask) flags the game has set, for the tracker's reads of what has been collected.
    equipment: {address in save data: byte} for the items held.
    rom: what the ROM holds of the seed's map, as support.a_rom gives it.
    sprite: what the ROM holds of the player's sprite, by name in link_sprite.READS. All zeros for what is not given.
    during_check_read: called while the tracker waits for its read of what has been collected.
    """
    model = window.pages[TAB].model
    seen = {}
    tables = {name: bytearray(size) for name, (_, size) in sni_tracker.check_addresses.items()}
    for table, room, mask in collected:
        word = int.from_bytes(tables[table][room * 2 : room * 2 + 2], "little") | mask
        tables[table][room * 2 : room * 2 + 2] = word.to_bytes(2, "little")
    for address, value in (equipment or {}).items():
        tables["items"][address - ITEMS_AT] = value

    def state():
        return {
            "player": model.player and model.player.node.tile,
            "links": [(link.door, link.linked_door) for link in model.door_links],
            "entrances": [lobby.door for lobby in model.lobby_doors],
            "dark room lit": DARK_ROOM in model.tiles and model.tiles[DARK_ROOM].has_been_lit,
            "dark room hidden": model.is_hidden_dark(DARK_ROOM),
        }

    class Devices:
        def __init__(self, channel):
            pass

        async def ListDevices(self, request):
            return Reply(devices=[Reply(uri="fake://snes")])

    class Memory:
        def __init__(self, channel):
            self.served = 0

        async def MappingDetect(self, request):
            return Reply(memoryMapping=0)

        async def MultiRead(self, request):
            if request.requests[0].requestAddress == sni_tracker.check_addresses["room"][0]:
                if during_check_read is not None:
                    during_check_read()
                return Reply(responses=[Reply(data=bytes(tables[name])) for name in sni_tracker.check_addresses])
            for name, (address, size) in link_sprite.READS.items():
                if request.requests[0].requestAddress == address:
                    return Reply(responses=[Reply(data=(sprite or {}).get(name, bytes(size)))])
            if rom is not None:
                for name, (address, size) in rom_reads(rom).items():
                    if address <= request.requests[0].requestAddress < address + size:
                        pieces = [(piece.requestAddress - address, piece.size) for piece in request.requests]
                        return Reply(responses=[Reply(data=rom[name][at : at + length]) for at, length in pieces])
            app.processEvents()
            if self.served == len(steps):
                seen["end"] = state()
                raise PlaybackOver()
            label, values = steps[self.served]
            seen[label] = state()
            self.served += 1
            return Reply(responses=[Reply(data=bytes.fromhex(values[name])) for name in sni_tracker.mem_addresses])

    monkeypatch.setattr(sni_tracker.sni, "DevicesStub", Devices)
    monkeypatch.setattr(sni_tracker.sni, "DeviceMemoryStub", Memory)

    async def session():
        try:
            await sni_tracker._sni_session(window, argparse.Namespace(debug=False), None, False, None, {"in_dungeon": False})
        except PlaybackOver:
            pass

    asyncio.run(asyncio.wait_for(session(), 30))
    return seen


def test_walking_through_a_door_and_into_a_dark_room(window, app, monkeypatch):
    first, north_door = door_facing("No")
    second, south_door = door_facing("So", avoid=first)
    at_first = (first, north_door["x"], north_door["y"])
    at_second = (second, south_door["x"], south_door["y"])
    in_dark = (DARK_ROOM, 250, 250)

    seen = play(
        window,
        app,
        monkeypatch,
        [
            ("start", reading(*at_first)),
            ("in the first room", reading(*at_first)),
            ("through the door", reading(*at_first, transitioning=True)),
            ("arriving", reading(*at_second)),
            ("arrived", reading(*at_second)),
            ("standing there", reading(*at_second)),
            ("leaving", reading(*at_second, transitioning=True)),
            ("entering the dark", reading(*in_dark, lamp=False)),
            ("in the dark", reading(*in_dark, lamp=False)),
            ("still in the dark", reading(*in_dark, lamp=False)),
            ("lamp lit", reading(*in_dark)),
            ("looking around", reading(*in_dark)),
        ],
    )

    link = (north_door["name"], south_door["name"])
    assert seen["through the door"]["player"] == first
    assert link not in seen["through the door"]["links"]
    assert seen["leaving"]["player"] == second
    assert link in seen["leaving"]["links"]
    # Dark with no lamp: on the map but hidden, and the player is not drawn
    assert seen["lamp lit"] == {**seen["lamp lit"], "player": None, "dark room lit": False, "dark room hidden": True}
    assert seen["end"] == {**seen["end"], "player": DARK_ROOM, "dark room lit": True, "dark room hidden": False}


def test_the_tracker_stops_when_the_window_says_to_disconnect(window, app, monkeypatch):
    monkeypatch.setattr(window, "seed_seen", lambda seed_hash: False)
    tile, door = door_facing("No")
    seen = play(window, app, monkeypatch, [(f"reading {k}", reading(tile, door["x"], door["y"])) for k in range(3)])

    # It stopped at the first reading, before putting the player on the map
    assert list(seen) == ["reading 0"]
    assert window.pages[TAB].model.player is None
    assert "disconnected" in window.windowTitle()


def test_checks_the_game_has_flagged_are_collected(window, app, monkeypatch):
    tile, door = door_facing("No")
    in_game = reading(tile, door["x"], door["y"])
    flagged = {
        "Eastern Palace - Compass Chest": ("room", 0xA8, 0x10),
        "Eastern Palace - Boss": ("room", 0xC8, 0x800),
        "Eastern Palace - Prize": ("prize", 0, 0x2000),
        # A key under a pot and one dropped by an enemy are flagged in the randomizer's own tables
        "Eastern Palace - Dark Square Pot Key": ("pot", 0xBA, 0x8000 >> 4),
        "Eastern Palace - Dark Eyegore Key Drop": ("enemy", 0x99, 0x8000 >> 3),
        # or, as a fallback, by the room's "key taken" bit
        "Hyrule Castle - Key Rat Key Drop": ("room", 0x21, 0x400),
        # A pot emptied and an enemy's drop taken are collected too, under the names the randomizer gives them
        "Eastern Dark Pots Pot #6": ("pot", 0xBA, 0x8000 >> 5),
        "Eastern Darkness Enemy #3": ("enemy", 0x99, 0x8000 >> 2),
    }
    # A chest's neighbour bit belongs to no check, and marks nothing
    noise = [("room", 0xA8, 0x8000)]

    play(window, app, monkeypatch, [("one", in_game), ("two", in_game)], collected=list(flagged.values()) + noise)
    assert window.collected == set(flagged)


def test_the_items_the_game_holds_reach_every_tab(window, app, monkeypatch):
    tile, door = door_facing("No")
    in_game = reading(tile, door["x"], door["y"])
    assert window.pages[TAB].model.items == STARTING_ITEMS

    # The hammer, and the mitts, which also lift what the glove lifts
    play(window, app, monkeypatch, [("one", in_game), ("two", in_game)], equipment={0x34B: 1, 0x354: 2})
    for page in window.pages.values():
        assert page.model.items == {"Hammer", "Power Glove", "Titans Mitts"}


def test_items_are_read_with_the_menu_up_and_not_with_no_file_loaded(window, app, monkeypatch):
    tile, door = door_facing("No")
    # The game's mode for the file select, a byte that is no mode of the game's, and its mode for its menu and
    # text boxes
    for mode, read in (("01", False), ("55", False), ("0e", True)):
        paused = reading(tile, door["x"], door["y"]) | {"gamemode": mode}
        play(window, app, monkeypatch, [("one", paused), ("two", paused)], equipment={0x34B: 1})
        model = window.pages[TAB].model
        assert ("Hammer" in model.items) is read, mode
        # The player is not followed in either
        assert model.player is None, mode


def test_the_player_is_drawn_with_the_head_of_the_games_own_sprite(window, app, monkeypatch):
    tile, door = door_facing("No")
    here = reading(tile, door["x"], door["y"])
    told = []
    tell = window.player_sprite_read
    monkeypatch.setattr(window, "player_sprite_read", lambda heads: (told.append(heads), tell(heads)))

    # No game read, and then one whose sprite has nothing for a head: a cross
    assert window.player_head() is None
    play(window, app, monkeypatch, [("one", here), ("two", here), ("three", here)])
    assert window.player_head() is None
    # It is read once for a game
    assert len(told) == 1

    # A head of two pixels. Top left, in colour 1: the first bit of the first row's first bit plane, in the first
    # tile. Bottom right, in colour 8: the last bit of the last row's fourth bit plane, in the fourth tile
    top, bottom = bytearray(0x40), bytearray(0x40)
    top[0] = 0x80
    bottom[0x20 + 2 * 7 + 17] = 0x01
    # Colour 1 is red in the green mail, green in the blue, blue in the red. Colour 8 is white in the green mail
    palettes = bytearray(90)
    palettes[0:2], palettes[30:32], palettes[60:62] = b"\x1f\x00", b"\xe0\x03", b"\x00\x7c"
    palettes[14:16] = b"\xff\x7f"
    sprite = {"head top": bytes(top), "head bottom": bytes(bottom), "palettes": bytes(palettes)}
    play(window, app, monkeypatch, [("one", here), ("two", here)], sprite=sprite)

    def pixel(x, y):
        return window.player_head().toImage().pixelColor(x, y).getRgb()

    assert (pixel(0, 0), pixel(15, 15), pixel(1, 0)) == ((248, 0, 0, 255), (248, 248, 248, 255), (0, 0, 0, 0))
    window.set_held(frozenset({"Blue Mail"}), {})
    assert pixel(0, 0) == (0, 248, 0, 255)
    window.set_held(frozenset({"Blue Mail", "Red Mail"}), {})
    assert pixel(0, 0) == (0, 0, 248, 255)


def test_falling_into_a_dungeon_by_a_drop_makes_the_drop_a_way_in(window, app, monkeypatch):
    castle = window.pages["Hyrule_Castle"].model
    assert castle.assumed("Sewer Drop")
    # The sewer drop's supertile, in the castle's dungeon, at about where the drop lands
    landing = dict(tile=(1, 1), x=400, y=290, dungeon="00")
    steps = [("falling", reading(**landing, falling=True))] + [(f"landed {k}", reading(**landing)) for k in range(3)]

    play(window, app, monkeypatch, steps)
    assert not castle.assumed("Sewer Drop")


def test_leaving_a_dungeon_before_a_position_is_read_adds_no_entrance(window, app, monkeypatch):
    tile, doors = supertile_with_doors_facing("So")
    at_door = (tile, doors["So"]["x"], doors["So"]["y"])
    inside, outside = reading(*at_door), reading(*at_door, indoors=False)
    # Back in, and out again while still in the doorway: no position is read on this visit
    in_the_doorway = reading(*at_door, transitioning=True)

    seen = play(
        window,
        app,
        monkeypatch,
        [("in", inside), ("in still", inside), ("out", outside), ("back in", in_the_doorway), ("out again", outside), ("outside", outside)],
    )
    assert seen["end"]["entrances"] == seen["back in"]["entrances"] == [doors["So"]["name"]]


def test_loading_another_seed_mid_dungeon_adds_nothing_from_the_old_game(window, app, monkeypatch):
    # The connection survives a change of ROM, so the tracker still remembers the old game's room
    monkeypatch.setattr(window, "_ask", lambda *args: DoorsTracker.NEW_MAP)
    first, north_door = door_facing("No")
    second, south_door = door_facing("So", avoid=first)
    old_game = reading(first, north_door["x"], north_door["y"], seed="aaaaaaaaaa")
    new_game = reading(second, south_door["x"], south_door["y"], seed="bbbbbbbbbb")

    seen = play(window, app, monkeypatch, [(f"old {k}", old_game) for k in range(3)] + [(f"new {k}", new_game) for k in range(3)])
    assert window.seed_hash == "bbbbbbbbbb"
    assert (seen["end"]["links"], seen["end"]["entrances"]) == ([], [])


def test_a_map_opened_while_the_tracker_waits_for_a_read_gets_nothing_from_that_reading(window, app, monkeypatch):
    # The user opens another seed's map during the first reading, then says to leave it as it is
    monkeypatch.setattr(window, "_ask", lambda *args: DoorsTracker.DISCONNECT)
    tile, door = door_facing("No")
    in_game = reading(tile, door["x"], door["y"])
    emptied = DROPS[(12, 8)][0]

    play(
        window,
        app,
        monkeypatch,
        [("one", in_game), ("two", in_game)],
        collected=[(emptied.kind, emptied.room, emptied.mask)],
        equipment={0x34B: 1},
        during_check_read=lambda: window.load_data({"seed_hash": "eeeeeeeeee"}),
    )
    assert window.seed_hash == "eeeeeeeeee"
    model = window.pages[TAB].model
    assert tile not in model.tiles and model.player is None and window.collected == set() and model.items == STARTING_ITEMS


def supertile_with_doors_facing(*facings):
    """(supertile, door table entry by facing) of a lit Palace of Darkness supertile with a door facing each way."""
    for tile, entries in sorted(door_coordinates.items()):
        doors = {}
        for entry in entries:
            name = entry["name"]
            if name.startswith("PoD") and name not in INTERIOR_DOORS and doors_data[name][2] == "00":
                doors.setdefault(doors_data[name][1], entry)
        if tile not in dark_tiles and all(facing in doors for facing in facings):
            return tile, doors
    raise AssertionError(f"no supertile with doors facing {facings}")


def test_leaving_a_dungeon_makes_the_door_left_by_an_entrance(window, app, monkeypatch):
    # Come in by a north door, which is not an entrance, and leave by a south door
    tile, doors = supertile_with_doors_facing("No", "So")
    at_north = (tile, doors["No"]["x"], doors["No"]["y"])
    at_south = (tile, doors["So"]["x"], doors["So"]["y"])

    seen = play(
        window,
        app,
        monkeypatch,
        [
            ("came in", reading(*at_north)),
            ("walked across", reading(*at_south)),
            ("at the south door", reading(*at_south)),
            ("outside", reading(*at_south, indoors=False)),
            ("still outside", reading(*at_south, indoors=False)),
        ],
    )

    assert doors["So"]["name"] not in seen["outside"]["entrances"]
    assert doors["So"]["name"] in seen["end"]["entrances"]


def test_the_cheat_reads_the_seeds_map_out_of_the_rom(window, app, monkeypatch):
    tile, door = door_facing("No")
    here = (tile, door["x"], door["y"])
    # As the menu leaves it once the tracker is connected
    window.cheat_wanted = True
    play(window, app, monkeypatch, [("in a room", reading(*here)), ("still there", reading(*here))], rom=a_rom(VANILLA, default_one_way_connections))

    assert not window.seed_map_wanted and not window.cheat_wanted
    assert window.pages["Eastern_Palace"].model.bosses == {(8, 12): "Armos Knights"}
    # The ROM has the doors as in the original game: a tab the player has not been in has its dungeon's rooms
    assert set(window.pages["Eastern_Palace"].model.tiles) == {tile for tile, record in SUPERTILES.items() if record.dungeon == "Eastern_Palace"}
    assert ("Eastern Cannonball S", "Eastern Lobby Bridge N") in [(link.door, link.linked_door) for link in window.pages["Eastern_Palace"].model.door_links]


def test_a_race_seed_gets_its_own_map_and_nothing_more_is_read_of_it(window, app, monkeypatch):
    def read():
        raise AssertionError("read past the first reading")

    async def read_rom(*args):
        read()

    monkeypatch.setattr(window, "race_rom_warning", lambda: None)
    monkeypatch.setattr(sni_tracker, "read_rom", read_rom)
    window.cheat_wanted = True  # asked for before the race seed was loaded
    tile, door = door_facing("No")
    race = {**reading(tile, door["x"], door["y"]), "race": "01"}

    play(window, app, monkeypatch, [("one", race), ("two", race)], during_check_read=read)
    assert window.seed_hash == race["seed_hash"]
    assert tile not in window.pages[TAB].model.tiles


def test_a_rooms_pots_are_counted_down_as_they_are_emptied(window, app, monkeypatch):
    tile, door = door_facing("No")
    here = (tile, door["x"], door["y"])
    room = (12, 8)
    pots = [drop for drop in DROPS[room] if drop.kind == "pot"]
    window.set_option("pottery", True)
    assert window.drops_left(room) == pots
    play(window, app, monkeypatch, [("in a room", reading(*here)), ("still there", reading(*here))], collected=[("pot", pots[0].room, pots[0].mask)])
    # The room's enemies are not counted: that takes the other box
    assert window.drops_left(room) == pots[1:]
    # A pot emptied is collected like any check, so it is kept with the map and gone with it
    assert pots[0].name in window.tracker_data()["collected"]
    window._clear_map()
    assert window.drops_left(room) == pots


def test_a_compass_alone_puts_the_seeds_boss_in_a_boss_room_already_on_the_map(window, app, monkeypatch):
    window.set_option("compass_reveals", True)
    tile, door = door_facing("No")
    here = (tile, door["x"], door["y"])
    eastern = window.pages["Eastern_Palace"].model
    boss_room = (8, 12)
    eastern.add_tile(boss_room, has_been_lit=True)
    eastern.set_boss(boss_room, "Mothula")  # the player's guess, and wrong
    mapped = set(eastern.tiles)
    compasses_at, compass = BITS[COMPASSES["Eastern_Palace"]]
    given, give = [], window.seed_map_read
    monkeypatch.setattr(window, "seed_map_read", lambda seed: given.append(seed) or give(seed))
    # Long enough for what is held to be read three times
    steps = [(f"reading {k}", reading(*here)) for k in range(25)]
    play(window, app, monkeypatch, steps, equipment={compasses_at: compass}, rom=a_rom(VANILLA, default_one_way_connections))

    assert eastern.bosses == {boss_room: "Armos Knights"}
    # The rooms are as the player mapped them: that takes the map
    assert set(eastern.tiles) == mapped and not eastern.revealed
    # The seed's map was handed over once: the room has had its boss
    assert len(given) == 1 and not window.seed_map_wanted
    # A boss room that comes onto the map later has not: here one of Ganon's Tower's, as a seed can join them
    eastern.add_tile((12, 1), has_been_lit=True)
    assert window.seed_map_wanted
    # Not with the box unticked
    window.set_option("compass_reveals", False)
    assert not window.seed_map_wanted


def test_a_dungeons_map_reveals_its_rooms_and_its_compass_its_boss(window, app, monkeypatch):
    def rooms_of(dungeon):
        return {tile for tile, record in SUPERTILES.items() if record.dungeon == dungeon}

    window.set_option("map_reveals", True)
    window.set_option("compass_reveals", True)
    tile, door = door_facing("No")
    here = (tile, door["x"], door["y"])
    # The player holds Eastern Palace's map and compass, and Desert Palace's map alone
    (maps_at, eastern_map), (also_maps_at, desert_map) = BITS[MAPS["Eastern_Palace"]], BITS[MAPS["Desert_Palace"]]
    compasses_at, eastern_compass = BITS[COMPASSES["Eastern_Palace"]]
    assert maps_at == also_maps_at
    held = {maps_at: eastern_map | desert_map, compasses_at: eastern_compass}
    play(window, app, monkeypatch, [("in a room", reading(*here)), ("still there", reading(*here))], equipment=held, rom=a_rom(VANILLA, default_one_way_connections))

    eastern, desert, hera = (window.pages[name].model for name in ("Eastern_Palace", "Desert_Palace", "Tower_of_Hera"))
    assert set(eastern.tiles) == rooms_of("Eastern_Palace") and eastern.bosses == {(8, 12): "Armos Knights"}
    # A map alone does not say which boss is where
    assert set(desert.tiles) == rooms_of("Desert_Palace") and desert.bosses == {}
    # And a dungeon with neither is as the player has mapped it
    assert set(hera.tiles) < rooms_of("Tower_of_Hera") and not hera.revealed
