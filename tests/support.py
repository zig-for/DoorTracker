"""Helpers for building maps in tests. Maps are built from the door tables, not from tracker files."""

from data.doors_data import dark_tiles, default_door_connections, ladders, open_edges, spiral_staircases, straight_staircases
from data.worlds_data import dungeon_worlds
from gui.Doors import seed_map
from gui.Doors.graph_model import GraphModel
from gui.Doors.randomizer import doors_and_portals
from gui.Doors.rooms import DOORS, INTERIOR_DOORS, SPLIT, SUPERTILES, supertile

OPPOSITE = {"No": "So", "So": "No", "Ea": "We", "We": "Ea"}
# The pairs of doors joined both ways in the original game
VANILLA = [*default_door_connections, *spiral_staircases, *straight_staircases, *open_edges, *ladders]


def a_rom(pairs, one_way=()):
    """What the tracker reads of a ROM whose doors are joined in these pairs: written as the randomizer's Rom.py
    writes it, with every dungeon entrance at its own door."""
    doors, portals = doors_and_portals()
    named = {door.name: door for door in doors}
    image = bytearray(0x200000)
    for a, b in [*pairs, *((b, a) for a, b in pairs), *one_way]:
        data = named[b].getTarget(named[a])
        image[named[a].getAddress() : named[a].getAddress() + len(data)] = bytes(data)
    for portal in portals:
        image[seed_map.ENTRANCE_ROOMS + portal.ent_offset * 2] = portal.current_room()
        at = seed_map.ENTRANCE_SCROLLS + portal.ent_offset * 2
        image[at : at + 2] = bytes(portal.scroll_x())
    return {name: bytes(image[address : address + size]) for name, (address, size) in seed_map.READS.items()}


def new_model(tab="Turtle_Rock", **flags):
    settings = {
        "hide_single_route_tiles": False,
        "prefer_fill_map": False,
        "decoupled_doors": False,
        "vanilla_drops": True,
        "trim_rooms": True,
        "split_rooms": True,
    }
    settings.update(flags)
    return GraphModel(dungeon_worlds[tab], settings)


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
