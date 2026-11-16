"""The dungeon checks the tracker shows: where each is drawn, and the memory flag it sets when collected.

Built when the tracker starts. The flags come from the door randomizer's own tables (gui/Doors/randomizer.py).
So does where a key pot or key drop is drawn; chests, bosses and prizes are placed by data/new_location_data.py.

flags: (table, room, mask). The check is collected when any of them is set. Tables:
  "room"   the room's word of save data
  "pot"    the room's word of the randomizer's pot table
  "enemy"  the room's word of the randomizer's enemy drop table
  "prize"  the dungeon prizes word; room is unused

Chests, bosses and prizes set a bit in the room's save data. A key in a pot or dropped by an enemy sets a bit in
the randomizer's own pot or enemy table, numbered by the pot's or enemy's place in the room; the room's "key taken"
bit is listed for those as well, in case a version of the rom sets that instead.
"""

from types import SimpleNamespace
from typing import NamedTuple, TypedDict

from data.new_location_data import underworld_items
from gui.Doors.rooms import SUPERTILES

# After gui.Doors.rooms, which goes by gui.Doors.randomizer: that makes these importable
from ALttPDoorRandomizer import PotShuffle  # noqa: E402
from ALttPDoorRandomizer.BaseClasses import PotFlags, PotItem  # noqa: E402
from ALttPDoorRandomizer.MultiClient import location_table_boss, location_table_uw  # noqa: E402
from ALttPDoorRandomizer.source.dungeon.EnemyList import SpriteType, enemy_names, init_enemy_stats, valid_drop_location  # noqa: E402
from ALttPDoorRandomizer.source.rom.DataTables import get_uw_enemy_table  # noqa: E402

KINDS = ("chest", "prize")  # what is placed by data/new_location_data.py
# The keys dropped that are big keys: the rest are small
BIG_KEY_DROPS = {name for name, data in PotShuffle.key_drop_data.items() if str(data[3]).startswith("Big Key")}


class Check(TypedDict):
    tile: tuple[int, int]  # supertile
    x: int  # position in the supertile, 0..512
    y: int
    flags: list[tuple[str, int, int]]


def pot_place(pot) -> tuple[int, int]:
    """Where a pot is in its supertile, 0..512. The randomizer counts its place in half tiles across and two tiles
    down, with the odd row kept in x's top bit; a pot is two tiles wide."""
    return (pot.x & 0x7F) * 4 + 8, (pot.y * 2 + (pot.x >> 7)) * 8 + 8


def key_drops() -> dict[str, Check]:
    """The keys in pots and dropped by enemies: where the randomizer has the pot or enemy, and the bit it sets,
    worked out as the randomizer's client does."""
    enemies = get_uw_enemy_table().room_map
    found: dict[str, Check] = {}
    for name, data in PotShuffle.key_drop_data.items():
        where = data[1]
        if isinstance(where, int):
            # A pot: its room
            room = where
            (index,) = [k for k, pot in enumerate(PotShuffle.vanilla_pots[room]) if pot.item == PotItem.Key]
            x, y = pot_place(PotShuffle.vanilla_pots[room][index])
            flag = ("pot", room, 0x8000 >> index)
        else:
            # An enemy: (address, room, its place in the room's list)
            assert isinstance(where, tuple)
            _, room, index = where
            x, y = enemies[room][index].tile_x * 16 + 8, enemies[room][index].tile_y * 16 + 8
            # Overlords are in the enemy list but have no bit
            index -= sum(1 for sprite in enemies[room][:index] if sprite.sub_type == 0x07)
            flag = ("enemy", room, 0x8000 >> index)
        found[name] = {"tile": (room % 16, room // 16), "x": x, "y": y, "flags": [flag]}
    return found


class Drop(NamedTuple):
    """A pot, or an enemy, that a seed makes a check of when every one is: it has no name here, only its bit and
    its place."""

    kind: str  # "pot" or "enemy": the table its bit is in, as in a check's flags
    room: int
    mask: int
    x: int  # in the supertile, 0..512
    y: int
    name: str  # what it is, as the randomizer names it: an enemy's kind, or "Pot" or "Large Block"


def drops() -> dict[tuple[int, int], list[Drop]]:
    """The pots and the enemies in a dungeon that are checks in a seed with Pottery set to Dungeon Pots, or Enemy
    Drops to Underworld Enemies: by supertile. Not the ones with a key, which are checks with names. Each has its
    bit as the randomizer's client works it out, in init_lookups."""
    found: dict[tuple[int, int], list[Drop]] = {}

    def add(kind: str, room: int, place: int, x: int, y: int, name: str) -> None:
        tile = (room % 16, room // 16)
        if tile in SUPERTILES:
            found.setdefault(tile, []).append(Drop(kind, room, 0x8000 >> place, x, y, name))

    for room, pots in PotShuffle.vanilla_pots.items():
        for place, pot in enumerate(pots):
            # As create_pot_location in Regions.py has it. A pot over a switch is a check only with pots shuffled
            # too, which is not known here: it is left out, so a room's count can reach none
            if pot.item not in (PotItem.Key, PotItem.Hole, PotItem.Switch):
                add("pot", room, place, *pot_place(pot), "Large Block" if pot.flags & PotFlags.Block else "Pot")
    # The randomizer's own test of an enemy, asked of a seed with every enemy's drop shuffled
    seed = SimpleNamespace(dropshuffle={1: "underworld"}, data_tables={1: SimpleNamespace(enemy_stats=init_enemy_stats())})
    for room, sprites in get_uw_enemy_table().room_map.items():
        place = 0
        for index, sprite in enumerate(sprites):
            # Overlords are in the list but have no bit
            if sprite.sub_type != SpriteType.Overlord:
                if valid_drop_location(sprite, index, seed, 1):
                    add("enemy", room, place, sprite.tile_x * 16 + 8, sprite.tile_y * 16 + 8, enemy_names[sprite.kind])
                place += 1
    return found


def read() -> dict[str, Check]:
    # From the randomizer's client: check -> (room, mask in the room's save data), and dungeon prize -> mask in
    # the prizes word
    in_rooms, prizes = location_table_uw, location_table_boss
    found = key_drops()
    for name, check in found.items():
        if name in in_rooms:
            check["flags"].append(("room", *in_rooms[name]))
    for tile, spots in sorted(underworld_items.items()):
        room = tile[1] * 16 + tile[0]
        for name, spot in spots.items():
            if spot["loc_type"] not in KINDS:
                continue
            flags: list[tuple[str, int, int]] = []
            if name in in_rooms:
                assert in_rooms[name][0] == room, f"{name}: drawn in room {room:#x}, flagged in {in_rooms[name][0]:#x}"
                flags.append(("room", room, in_rooms[name][1]))
            if name in prizes:
                flags.append(("prize", 0, prizes[name]))
            if flags:
                found[name] = {"tile": tile, "x": int(spot["x"]), "y": int(spot["y"]), "flags": flags}
    return {name: check for name, check in found.items() if check["tile"] in SUPERTILES}


checks = read()
DROPS = drops()
