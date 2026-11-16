"""The bosses a seed can put in a boss room, and the boss rooms: where each has its boss drawn, and the ways out
of it that take beating the boss.

A seed with bosses shuffled has any of them in any of these rooms. The game does not say which until the player
sees it, so the player picks. Until then the boss counts as beaten.
"""

from dataclasses import dataclass
from pathlib import Path

from gui.Doors.checks import checks
from gui.Doors.logic import Rule
from gui.Doors.rooms import DEFAULT_DOORS, Tile
from gui.Doors.rules import boss_rules, check_regions

SHEET_PATH = Path(__file__).parent.parent.parent / "data" / "Boss_Sheet.png"
ICON = 32  # the side of an icon on the sheet, which has them in a row in the order of BOSSES
# Agahnim is always in his own rooms
BOSSES = [boss for boss in boss_rules if not boss.startswith("Agahnim")]


@dataclass(frozen=True)
class BossRoom:
    x: float  # where its boss is drawn, in the supertile's picture, 0..512
    y: float
    ways: tuple[str, ...]  # the doors and passages out of it that take beating the boss, as Rules.py has them
    on_ice: bool = False  # the floor is ice, which some bosses take more to beat on


ABOVE_PRIZE = 46  # a boss's centre over its room's prize, to sit clear of it


def _rooms() -> dict[Tile, BossRoom]:
    found = {}
    for name, check in checks.items():
        if name.endswith("- Prize"):
            # The boss is between its room and the region its drops are in
            ways = tuple(way for way, region in DEFAULT_DOORS.items() if region == check_regions[name])
            found[check["tile"]] = BossRoom(check["x"], check["y"] - ABOVE_PRIZE, ways)
    # Ganon's Tower has three, with no prize: each is drawn where the original game's boss stands
    found[(12, 1)] = BossRoom(384, 360, ("GT Ice Armos NE", "GT Ice Armos WS"), on_ice=True)
    found[(12, 6)] = BossRoom(128, 384, ("GT Lanmolas 2 ES", "GT Lanmolas 2 NW"))
    found[(13, 4)] = BossRoom(256, 220, ("GT Moldorm Gap",))
    return found


BOSS_ROOMS = _rooms()


def beating(tile: Tile, boss: str, dungeon: str) -> Rule:
    """What going past a boss room's boss takes, in a dungeon by the tracker's name for it."""
    room = BOSS_ROOMS[tile]
    rule = boss_rules[boss][room.on_ice]
    # In Thieves' Town, Blind is only there once the maiden is unmasked: set_defeat_dungeon_boss_rule in Rules.py
    if boss == "Blind" and dungeon == "Thieves_Town" and "Thieves Town Boss" in room.ways:
        return ("all", rule, "Maiden Unmasked")
    return rule
