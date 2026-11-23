"""What a seed did with the doors and the bosses, read out of its ROM: which door leads to which, which door each
dungeon entrance comes in by, and which boss is in each boss room.

The randomizer writes, for every door a seed can move, where it leads (Rom.py: door.getAddress() gets
door.dest.getTarget(door)), and for every dungeon entrance the room and door it comes in by. This reads those back
into door names, with the randomizer's own doors to say where each is kept. A boss is put first among its room's
sprites (Bossmizer.py), and is read back from there.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from gui.Doors.randomizer import doors_and_portals
from gui.Doors.rooms import tile_of

# After gui.Doors.randomizer, which makes the randomizer importable
from ALttPDoorRandomizer.BaseClasses import Direction, DoorType  # noqa: E402
from ALttPDoorRandomizer.DoorShuffle import default_one_way_connections  # noqa: E402
from ALttPDoorRandomizer.source.dungeon.EnemyList import SpriteType  # noqa: E402
from ALttPDoorRandomizer.source.dungeon.RoomList import boss_rooms, gt_boss_room  # noqa: E402
from ALttPDoorRandomizer.source.enemizer import Bossmizer  # noqa: E402
from ALttPDoorRandomizer.Utils import snes_to_pc  # noqa: E402

# Doors that are only come out of: nothing leads back through them
NO_WAY_BACK = {out for _into, out in default_one_way_connections}
# The kinds of door whose link a ROM holds
LINKED = (DoorType.Normal, DoorType.SpiralStairs, DoorType.Open, DoorType.StraightStairs, DoorType.Ladder)
OPPOSITE = {Direction.North: Direction.South, Direction.South: Direction.North, Direction.West: Direction.East, Direction.East: Direction.West}
# Two bytes for each entrance, by its number: the room it comes into, and how far the screen is scrolled across
# that room, which says which of the room's south doors it is
ENTRANCE_ROOMS, ENTRANCE_SCROLLS = 0x14577, 0x14AA9
# Where the game keeps the address of its table of each room's sprites, in bank 9, and the bank the randomizer puts
# every room's list of sprites in: DataTables.py's pointer_addresses["uw_sprites"], and EnemyList.py's
# write_sprite_data_to_rom
SPRITE_TABLE_AT, SPRITE_TABLE_BANK, SPRITE_BANK = 0x09C298, 0x090000, 0x280000


def _reads() -> dict[str, tuple[int, int]]:
    doors, portals = doors_and_portals()
    places = [door.getAddress() for door in doors if door.type in LINKED]
    numbers = [portal.ent_offset for portal in portals]
    entrances = (max(numbers) - min(numbers) + 1) * 2
    return {
        "links": (min(places), max(places) + 4 - min(places)),  # the longest link is four bytes
        "entrance_rooms": (ENTRANCE_ROOMS + min(numbers) * 2, entrances),
        "entrance_scrolls": (ENTRANCE_SCROLLS + min(numbers) * 2, entrances),
        # Where the table of each room's sprites is: the randomizer can move it
        "sprite_table_at": (snes_to_pc(SPRITE_TABLE_AT), 2),
    }


# What to read of a ROM first, by name: (address, length). See next_reads for the rest
READS = _reads()


def _boss_sprites() -> dict[int, str]:
    """Sprite -> the boss it is part of, from what the randomizer puts in a room for each boss."""
    found = {}
    for boss, (add, _sprite) in Bossmizer.boss_addition_table.items():
        added: list = []
        add(added, 0)
        found |= {int(sprite.kind): boss for sprite in added if sprite.sub_type != SpriteType.Overlord}
    return found


BOSS_SPRITES = _boss_sprites()
BOSS_ROOM_NUMBERS = sorted(room[0] for room in (*boss_rooms.values(), *gt_boss_room.values()))


def next_reads(memory: Mapping[str, bytes]) -> dict[str, tuple[int, int]]:
    """What to read of the ROM next, given what has been read; nothing when that is all.

    A room's sprites are found in two steps: the ROM says where its table of rooms is, and that says where each
    room's list is. A boss room's list starts with its boss: a byte, then the first sprite's two bytes of place
    and one of which sprite it is.
    """
    if "sprite_table" not in memory:
        table = SPRITE_TABLE_BANK | int.from_bytes(memory["sprite_table_at"], "little")
        first, last = BOSS_ROOM_NUMBERS[0], BOSS_ROOM_NUMBERS[-1]
        return {"sprite_table": (snes_to_pc(table + first * 2), (last - first + 1) * 2)}
    if f"sprites {BOSS_ROOM_NUMBERS[0]:#x}" not in memory:
        reads = {}
        for room in BOSS_ROOM_NUMBERS:
            at = (room - BOSS_ROOM_NUMBERS[0]) * 2
            reads[f"sprites {room:#x}"] = (snes_to_pc(SPRITE_BANK | int.from_bytes(memory["sprite_table"][at : at + 2], "little")), 4)
        return reads
    return {}


@dataclass(frozen=True)
class SeedMap:
    leads: dict[str, str]  # door -> the door going through it comes out of
    entrances: dict[str, str]  # dungeon entrance, as the randomizer names it -> the door it comes in by
    bosses: dict[tuple[int, int], str]  # boss room's supertile -> its boss

    def links(self, decoupled: bool) -> list[tuple[str, str]]:
        """The doors the seed joined, as (door, the door it leads to).

        Two that lead to each other are in it once. One that leads to a door that does not lead back is in it
        when that door never does, as into a boss's room. Any other is taken for a door the seed walled off, whose
        link is whatever was left there.

        decoupled: the seed has each door lead its own way, so every door is in it with where it leads.
        """
        if decoupled:
            return list(self.leads.items())
        return [(a, b) for a, b in self.leads.items() if (self.leads.get(b) == a and a <= b) or (self.leads.get(b) != a and b in NO_WAY_BACK)]


def _place(door) -> tuple:
    """What a link names a door by: how getTarget in the randomizer's BaseClasses.py writes it."""
    if door.type is DoorType.SpiralStairs:
        return ("spiral", door.roomIndex, door.quadrant, door.direction is Direction.Up, door.shiftX, door.shiftY)
    if door.type is DoorType.Open:
        return ("open", door.roomIndex, door.direction, door.edge_id)
    if door.type is DoorType.Ladder:
        return ("ladder", door.roomIndex, door.doorIndex)
    return ("door", door.roomIndex, door.direction, door.doorIndex)


def decode(memory: Mapping[str, bytes]) -> SeedMap:
    """memory: what was read of the ROM, by name in READS."""
    doors, portals = doors_and_portals()
    linked = [door for door in doors if door.type in LINKED]
    by_place = {_place(door): door for door in linked}
    table, start = memory["links"], READS["links"][0]
    leads = {}
    for door in linked:
        at = door.getAddress() - start
        room, flags = table[at], table[at + 1]
        if door.type is DoorType.SpiralStairs:
            place = ("spiral", room, flags & 0x03, bool(flags & 0x80), table[at + 2], table[at + 3])
        elif flags & 0x80:
            place = ("open", room, OPPOSITE[door.direction], flags & 0x0F)
        elif flags & 0x03 == 0x03:
            place = ("ladder", room, (flags >> 3) & 0x07)
        else:
            place = ("door", room, OPPOSITE[door.direction], flags & 0x03)
        # A door the seed walled off keeps whatever was there, which need not name a door
        if place in by_place:
            leads[door.name] = by_place[place].name

    first = min(portal.ent_offset for portal in portals)
    entrances = {}
    for portal in portals:
        at = (portal.ent_offset - first) * 2
        room, scroll = memory["entrance_rooms"][at], memory["entrance_scrolls"][at : at + 2]
        # As Portal.scroll_x writes it: the left door, the middle one, or the right
        index = 1 if scroll[0] == 0x80 else 0 if scroll[1] == (room & 0x0F) * 2 else 2
        door = by_place.get(("door", room, Direction.South, index))
        # An entrance the seed left alone is not written; if what is there is no door for an entrance, it is
        # the entrance's own
        entrances[portal.name] = door.name if door is not None and door.portalAble else portal.door.name

    bosses = {}
    for room in BOSS_ROOM_NUMBERS:
        boss = BOSS_SPRITES.get(memory[f"sprites {room:#x}"][3])
        if boss is not None:
            bosses[tile_of(room)] = boss
    return SeedMap(leads, entrances, bosses)
