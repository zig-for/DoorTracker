"""What the player holds, and whether that meets one of the randomizer's rules (gui/Doors/rules.py)."""

from collections.abc import Mapping

from data.worlds_data import dungeon_worlds
from gui.Doors.randomizer import dungeon_name, tables_in

# After gui.Doors.randomizer, which makes the randomizer importable. The randomizer's name for a dungeon -> a
# tuple that ends in the game's number for the dungeon, -> its big key, and -> its small key
from ALttPDoorRandomizer.DoorShuffle import compass_data  # noqa: E402
from ALttPDoorRandomizer.Dungeons import dungeon_bigs, dungeon_keys  # noqa: E402
from ALttPDoorRandomizer.InitialSram import InitialSram  # noqa: E402

# An item's name, ("all", rule, ...), ("any", rule, ...), ("not", rule), or a bool. Or one of two that ask about
# a region and not about what is held: ("reached", region), and ("down", region, BLUE or ORANGE) for reached with
# those crystal barriers down
Rule = bool | str | tuple

# The part of the game's save data that holds the equipment, and after it how far the story has got
ITEMS_AT = 0x340
PROGRESS_AT = 0x3C5
ITEMS_LENGTH = PROGRESS_AT + 1 - ITEMS_AT
# Not an item: the randomizer's name for Zelda having been brought to the sanctuary. The game's progress is 2 from
# then on, and a seed that is not standard starts with it there (init_open_mode_sram in Rom.py)
ZELDA_DELIVERED = "Zelda Delivered"

# What the randomizer gives a starting item by: item -> (address in save data, value) for an item with a slot of
# its own, item -> (address, bit) for the big keys among others, and small key -> the addresses its count is kept
# at
_SLOTS, _FLAGS, _COUNTS = tables_in(InitialSram.set_starting_equipment, "set_table", "or_table", "keys")
# The tracker's names for the dungeons
DUNGEONS = [tab for tab in dungeon_worlds if dungeon_name(tab) in dungeon_bigs]

# item -> (address, least value that means it is held). The ones listed here InitialSram.py sets by other means
AT_LEAST = {
    **_SLOTS,
    "Bow": (0x340, 1),
    "Power Glove": (0x354, 1),
    "Titans Mitts": (0x354, 2),
    "Pegasus Boots": (0x355, 1),
    "Flippers": (0x356, 1),
    "Fighter Sword": (0x359, 1),
    "Master Sword": (0x359, 2),
    "Tempered Sword": (0x359, 3),
    "Golden Sword": (0x359, 4),
    "Blue Shield": (0x35A, 1),
    "Red Shield": (0x35A, 2),
    "Mirror Shield": (0x35A, 3),
    "Blue Mail": (0x35B, 1),
    "Red Mail": (0x35B, 2),
    "Magic Upgrade (1/2)": (0x37B, 1),
    "Magic Upgrade (1/4)": (0x37B, 2),
    # Not an item: room for bombs. It is none until the bomb bag is found, in seeds that have one
    "Bombs": (0x370, 1),
}
# Magic upgrade -> how much magic the bar holds with it, and how much it holds without one: as can_extend_magic
# in BaseClasses.py has them
MAGIC_BARS = {"Magic Upgrade (1/2)": 16, "Magic Upgrade (1/4)": 32}
MAGIC_BAR = 8
# item -> (address, bit). 0x38C is the randomizer's own record of the items that share a slot in the menu, where
# the slot itself only holds the one last picked up
BITS = {
    "Blue Boomerang": (0x38C, 0x80),
    "Red Boomerang": (0x38C, 0x40),
    "Mushroom": (0x38C, 0x20),
    "Magic Powder": (0x38C, 0x10),
    "Shovel": (0x38C, 0x04),
    "Ocarina": (0x38C, 0x03),  # working or not
    # The big keys, and with them the dungeons' maps and compasses
    **{item: where for item, where in _FLAGS.items() if item.startswith(("Big Key (", "Map (", "Compass ("))},
}
# The tracker's name for a dungeon -> its big key, and -> where its small keys are counted
BIG_KEYS = {tab: dungeon_bigs[dungeon_name(tab)] for tab in DUNGEONS}
SMALL_KEYS_AT = {tab: _COUNTS[dungeon_keys[dungeon_name(tab)]][0] for tab in DUNGEONS}
# The tracker's name for a dungeon -> its map, and -> its compass: the randomizer names them as it names the big keys
MAPS = {tab: key.replace("Big Key", "Map") for tab, key in BIG_KEYS.items()}
COMPASSES = {tab: key.replace("Big Key", "Compass") for tab, key in BIG_KEYS.items()}
# The game's number for a dungeon -> the tracker's name for it. The sewers have a number of their own
DUNGEON_NUMBERS = {0x00: "Hyrule_Castle"} | {compass_data[dungeon_name(tab)][4]: tab for tab in DUNGEONS}
KEYS_HERE_AT = 0x36F  # the small keys for the dungeon the player is in; 0xFF outside
BOTTLES_AT = range(0x35C, 0x360)  # what is in each of the four bottles; 0 for no bottle
# Bottles are held as these, one for each the player has, so a rule that asks for two asks for the second
BOTTLES = ["Bottle", "2 Bottles", "3 Bottles", "4 Bottles"]
READABLE = frozenset(AT_LEAST) | frozenset(BITS) | frozenset(BOTTLES)
SWORD = 0x359
NO_SWORDS = 0xFF  # what a swordless seed puts in the sword's byte
HEALTH_AT = 0x36C  # the most health the player can have, in eighths of a heart
# Hearts are held as these, one for each the player has, so a rule that asks for four asks for the fourth
HEARTS = [f"{count} Hearts" for count in range(1, 21)]
FIRST_HEARTS = 3  # what the game starts with


def hearts_held(items: frozenset[str]) -> int:
    return sum(1 for heart in HEARTS if heart in items)


def with_hearts(items: frozenset[str], count: int) -> frozenset[str]:
    """The items with this many hearts in place of however many they had."""
    return (items - frozenset(HEARTS)) | frozenset(HEARTS[:count])


# What is held on a new map. With no game to say, the seed is not taken as standard
STARTING_ITEMS = with_hearts(frozenset({ZELDA_DELIVERED}), FIRST_HEARTS)


def items_held(save: bytes) -> frozenset[str]:
    """The items held, from the ITEMS_LENGTH bytes of save data at ITEMS_AT."""

    def at(address: int) -> int:
        value = save[address - ITEMS_AT]
        return 0 if address == SWORD and value == NO_SWORDS else value

    held = {item for item, (address, least) in AT_LEAST.items() if at(address) >= least}
    held |= {item for item, (address, bit) in BITS.items() if at(address) & bit}
    held |= set(BOTTLES[: sum(1 for address in BOTTLES_AT if at(address))])
    if at(PROGRESS_AT) >= 2:
        held.add(ZELDA_DELIVERED)
    return with_hearts(frozenset(held), at(HEALTH_AT) // 8)


def small_keys(save: bytes, dungeon: int) -> dict[str, int]:
    """Small keys held for each dungeon, by the tracker's name for it.

    dungeon: the game's number for the dungeon the player is in. While they are in it the game counts its keys
    at KEYS_HERE_AT, and only writes the dungeon's own count when they leave.
    """
    keys = {name: save[address - ITEMS_AT] for name, address in SMALL_KEYS_AT.items()}
    here = save[KEYS_HERE_AT - ITEMS_AT]
    if here != 0xFF and dungeon in DUNGEON_NUMBERS:
        keys[DUNGEON_NUMBERS[dungeon]] = here
    return keys


# Which crystal barriers are down, as the randomizer counts it: a region can be reached with the blue ones down,
# the orange ones down, or both, which is EITHER. A dungeon is entered with the orange ones down
BLUE, ORANGE, EITHER = 1, 2, 3


def holds(rule: Rule, items: frozenset[str], reached: Mapping[str, int] | None = None) -> bool:
    """Whether a rule is met.

    items: what the player holds.
    reached: region -> the crystal barriers that can be down on getting there, for a rule that asks about a
    region. None when that is not known: what it asks of a region is then taken as met.
    """
    if isinstance(rule, bool):
        return rule
    if isinstance(rule, str):
        return rule in items
    kind, *parts = rule
    if kind == "reached":
        return reached is None or parts[0] in reached
    if kind == "down":
        return reached is None or bool(reached.get(parts[0], 0) & parts[1])
    if kind == "not":
        return not holds(parts[0], items, reached)
    return (all if kind == "all" else any)(holds(part, items, reached) for part in parts)


def combine(kind: str, parts: list[Rule]) -> Rule:
    """("all" | "any", rules) with the constants folded away and rules of the same kind merged in."""
    empty = kind == "all"  # an empty "all" is met, an empty "any" is not
    kept: list[Rule] = []
    for part in parts:
        if part is (not empty):
            return not empty
        for inner in part[1:] if isinstance(part, tuple) and part[0] == kind else [part]:
            if inner is not empty and inner not in kept:
                kept.append(inner)
    if not kept:
        return empty
    return kept[0] if len(kept) == 1 else (kind, *kept)


def enough_magic(needed: int) -> Rule:
    """What having this much magic takes, as can_extend_magic in BaseClasses.py has it: a bar that holds it, or
    bottles to fill the bar again from, each good for one bar more.

    The randomizer counts the bottles only where a shop that sells green or blue potion can be got to, and counts
    each for less in a hard seed. Neither is known: the shop is taken as got to, and the seed as not hard.
    """
    ways = []
    for upgrade, bar in ((None, MAGIC_BAR), *MAGIC_BARS.items()):
        bottles = -(-needed // bar) - 1
        if bottles <= len(BOTTLES):
            ways.append(combine("all", [*([upgrade] if upgrade else []), *([BOTTLES[bottles - 1]] if bottles > 0 else [])]))
    return combine("any", ways)
