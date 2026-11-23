"""Helpers for building maps in tests. Maps are built from the door tables, not from tracker files."""

import copy

from PySide6.QtCore import QPointF

from data.doors_data import dark_tiles, default_door_connections, ladders, open_edges, regions_to_doors, spiral_staircases, straight_staircases
from data.worlds_data import dungeon_worlds
from gui.Doors import seed_map
from gui.Doors.checks import checks
from gui.Doors.graph_model import GraphModel
from gui.Doors.randomizer import doors_and_portals
from gui.Doors.rooms import DOORS, INTERIOR_DOORS, SPLIT, SUPERTILES, supertile
from gui.Doors.rules import check_regions

# After gui.Doors, which makes the randomizer importable
from ALttPDoorRandomizer.source.enemizer import Bossmizer  # noqa: E402
from ALttPDoorRandomizer.source.rom.DataTables import get_uw_enemy_table  # noqa: E402

OPPOSITE = {"No": "So", "So": "No", "Ea": "We", "We": "Ea"}
# The pairs of doors joined both ways in the original game
VANILLA = [*default_door_connections, *spiral_staircases, *straight_staircases, *open_edges, *ladders]


class Image:
    """Stands in for the randomizer's ROM, for its own code to write to."""

    def __init__(self):
        self.data = bytearray(0x200000)

    def write_byte(self, at, value):
        self.data[at] = value

    def write_bytes(self, at, values):
        self.data[at : at + len(values)] = bytes(values)


def a_rom(pairs, one_way=(), moved=None, bosses=None):
    """What the tracker reads of a ROM whose doors are joined in these pairs: written as the randomizer's Rom.py
    writes it. Every dungeon entrance is at its own door, but for those in moved: entrance -> the door it is at.
    Every boss room has its own boss, but for those in bosses: room -> the boss the seed put there."""
    doors, portals = doors_and_portals()
    named = {door.name: door for door in doors}
    rom = Image()
    image = rom.data

    # Every room's sprites, written by the randomizer's own code, with a boss changed as its Bossmizer.py does it
    sprites = get_uw_enemy_table()
    for room, boss in (bosses or {}).items():
        del sprites.room_map[room][: Bossmizer.boss_room_remove_data[room]]
        Bossmizer.boss_addition_table[boss][0](sprites.room_map[room], room)
    # The table of rooms is at 09:D62E in the game. Here the overworld's sprites are given as ending past that,
    # which has the randomizer's writer move the table and say where: as in DataTables.py's pointer_addresses
    table, ow_end = 0x09D62E, 0x09D72E
    sprites.write_sprite_data_to_rom(rom, {"ow_sprites": [ow_end, 0], "uw_sprites": [0x09D92E, None, table, seed_map.SPRITE_TABLE_AT]})

    for a, b in [*pairs, *((b, a) for a, b in pairs), *one_way]:
        data = named[b].getTarget(named[a])
        image[named[a].getAddress() : named[a].getAddress() + len(data)] = bytes(data)
    for portal in portals:
        if moved and portal.name in moved:
            portal = copy.copy(portal)
            portal.door = named[moved[portal.name]]
        image[seed_map.ENTRANCE_ROOMS + portal.ent_offset * 2] = portal.current_room()
        at = seed_map.ENTRANCE_SCROLLS + portal.ent_offset * 2
        image[at : at + 2] = bytes(portal.scroll_x())
    # Read as the tracker reads it: what is read first says where some of the rest is
    memory, reads = {}, seed_map.READS
    while reads:
        memory |= {name: bytes(image[address : address + size]) for name, (address, size) in reads.items()}
        reads = seed_map.next_reads(memory)
    return memory


def rom_reads(memory):
    """Where each part of a_rom's result was read from: name -> (address, length)."""
    found, reads = {}, seed_map.READS
    while reads:
        found |= reads
        reads = seed_map.next_reads({name: memory[name] for name in found})
    return found


def new_model(tab="Turtle_Rock", **flags):
    settings = {
        "hide_single_route_tiles": False,
        "prefer_fill_map": False,
        "decoupled_doors": False,
        "vanilla_drops": True,
        "trim_rooms": True,
        "split_rooms": True,
        "enemy_shuffle": False,
    }
    settings.update(flags)
    return GraphModel(dungeon_worlds[tab], settings)


def model_leading_to(name, tab):
    """A map of a check's supertile, with an entrance on a door of the region the check is in."""
    model = new_model(tab)
    model.add_tile(checks[name]["tile"], has_been_lit=True)
    model.add_lobby_door(next(door for door in regions_to_doors[check_regions[name]] if door in DOORS), tab)
    model.update()
    return model


class At:
    """Stands in for a mouse event at a point of the viewport."""

    def __init__(self, point):
        self.point = point

    def position(self):
        return QPointF(self.point)


def parts_shown(model, tile):
    return sorted(node.part for node in model.nodes() if node.tile == tile)


def point_in(model, tile, part):
    """A player position, 0..512, that the model places in this part of a split supertile."""
    for left, top, right, bottom in supertile(tile).areas[part]:
        x, y = (left + right) / 2, (top + bottom) / 2
        if model.player_node(tile, x, y).part == part:
            return x, y
    raise AssertionError(f"no point found in part {part} of {tile}")


def open_doors(model, tile):
    """Doors of a supertile that can take a link: not interior, not linked, not an entrance."""
    return [
        name
        for name in supertile(tile).doors
        if name not in INTERIOR_DOORS and not model.has_target(name) and name not in model.lobby_door_names()
    ]


def next_link(model: GraphModel) -> tuple[str, str]:
    """(door on the map, facing door of a supertile not on the map).

    The new supertile is lit and unsplit, and the one with the most doorways, so the map can keep growing.
    """

    def doorways(tile):
        return [d for d in open_doors(model, tile) if DOORS[d].facing in OPPOSITE]

    most, link = 0, None
    for tile in list(model.tiles):
        for door in doorways(tile):
            wanted = OPPOSITE[DOORS[door].facing or ""]
            for other in sorted(SUPERTILES):
                if other in model.tiles or other in dark_tiles or SPLIT.part_count(other) > 1:
                    continue
                for candidate in doorways(other):
                    if DOORS[candidate].facing == wanted:
                        if len(doorways(other)) > most:
                            most, link = len(doorways(other)), (door, candidate)
                        break
    if link is None:
        raise AssertionError("nothing left to link onto the map")
    return link


def grow(model, rooms):
    """Link new supertiles onto the map through facing doorways until it has this many more."""
    for _ in range(rooms):
        model.add_link(*next_link(model))
    return model


def positions(model):
    return {node: tuple(xy) for node, xy in model.pos.items()}


def joined_doors(model):
    return sorted((link.door, link.linked_door) for link in model.blocks.joined)
