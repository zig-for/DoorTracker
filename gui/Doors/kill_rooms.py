"""The kill rooms: the rooms whose doors, or whose chest, the randomizer's logic has open once their enemies are
killed, and what killing them takes.

Which rooms, which of their enemies and which doors and chests are from Rules.py. What killing a room's enemies
takes is worked out by the randomizer's own defeat_rule_multiple, run on them.

A seed with enemies shuffled has other enemies in the same places. The game does not say which until the player
sees them, so the player picks. Until then each is the original game's.
"""

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from types import SimpleNamespace

from gui.Doors.checks import checks
from gui.Doors.logic import READABLE, Rule
from gui.Doors.rooms import SUPERTILES, Tile
from gui.Doors.rules import combine

# After gui.Doors.rooms, which goes by gui.Doors.randomizer: that makes these importable
from ALttPDoorRandomizer.Items import item_table  # noqa: E402
from ALttPDoorRandomizer.Rules import kill_chests, std_kill_rooms  # noqa: E402
from ALttPDoorRandomizer.source.dungeon.EnemyList import EnemySprite, SpriteType, init_enemy_stats  # noqa: E402
from ALttPDoorRandomizer.source.enemizer import EnemyLogic  # noqa: E402
from ALttPDoorRandomizer.source.enemizer.DamageTables import DamageTable  # noqa: E402
from ALttPDoorRandomizer.source.enemizer.SpriteSheets import init_sprite_requirements  # noqa: E402
from ALttPDoorRandomizer.source.logic.Rule import RuleType  # noqa: E402
from ALttPDoorRandomizer.source.rom.DataTables import get_uw_enemy_table  # noqa: E402

# One for each of PICKS, by its name. The game draws some kinds from either of two sheets of graphics, whichever
# the room has, and they look different on each: the picture of one of those is half of each look
PICTURES = Path(__file__).parent.parent.parent / "data" / "enemies"
# In place of a kind: anything that need not be killed, like a Beamos
NA = "N/A"

_STATS = init_enemy_stats()
_SPRITES = get_uw_enemy_table().room_map
_REQUIREMENTS = init_sprite_requirements()


def _kinds() -> list[str]:
    """The kinds of enemy that enemy shuffle can put in a kill room and that have to be killed there, by the
    randomizer's names for them, in the game's order."""
    found = set()
    for requirement in _REQUIREMENTS.values():
        # A dict is a kind that differs by room, which is not an enemy: the shopkeeper
        if isinstance(requirement, dict) or requirement.overlord or not requirement.good_for_shutter(set()):
            continue
        stats = _STATS.get(requirement.sprite)
        if stats is not None and not stats.ignore_for_kill_room:
            found.add(requirement.sprite)
    return [kind.name for kind in sorted(found, key=lambda kind: kind.value)]


KINDS = _kinds()
# A kind that looks the same as another and takes the same to kill -> the other, which is the one to pick
TWINS = {"Octorok4Way": "Octorok", "Popo2": "Popo"}
# What an enemy can be picked as
PICKS = [kind for kind in KINDS if kind not in TWINS]


@dataclass(frozen=True)
class Enemy:
    number: int  # its place in the room's list of sprites
    x: int  # where it stands in the supertile, 0..512
    y: int
    original: str  # its kind in the original game, or NA
    picture: str  # the kind whose picture shows it there


# The game has one kind for an Eyegore and a mimic, and draws it as a mimic in the rooms it has mimics in: those
# with these numbers. The randomizer names a mimic as a kind of its own, for enemy shuffle to place
MIMIC_ROOMS = {0x1B, 0x4B, 0x6B}
MIMICS = {"GreenEyegoreMimic": "GreenMimic", "RedEyegoreMimic": "RedMimic"}


@dataclass(frozen=True)
class KillRoom:
    tile: Tile
    enemies: tuple[Enemy, ...]  # the ones a seed can have to be killed
    ways: tuple[str, ...] = ()  # the doors out of it that take killing them
    trap_ways: tuple[str, ...] = ()  # and those that take it only in a seed that has made them trap doors
    checks: tuple[str, ...] = ()  # the checks that take it


def _shuffled(sprite) -> bool:
    """Whether enemy shuffle gives a sprite another kind: as get_randomize_able_sprites in Enemizer.py has it."""
    requirement = _REQUIREMENTS.get((sprite.kind, 0))
    if requirement is None or isinstance(requirement, dict):
        return False
    return not requirement.static and requirement.can_randomize and not sprite.static


def _rooms() -> dict[str, KillRoom]:
    listed = {name: (room, numbers, {"ways": tuple(ways), "trap_ways": tuple(traps)}) for name, (ways, traps, room, numbers) in std_kill_rooms.items()}
    listed |= {name: (room, numbers, {"checks": tuple(names)}) for name, (names, room, numbers) in kill_chests.items()}
    found = {}
    for name, (room, numbers, opens) in listed.items():
        tile = (room % 16, room // 16)
        enemies = []
        for number in numbers:
            sprite = _SPRITES[room][number]
            counts = not _STATS[sprite.kind].ignore_for_kill_room
            # One that neither counts nor can be changed never has to be killed: a statue that shoots
            if sprite.sub_type != SpriteType.Overlord and (counts or _shuffled(sprite)):
                original = sprite.kind.name if counts else NA
                picture = MIMICS.get(original, original) if room in MIMIC_ROOMS else TWINS.get(original, original)
                enemies.append(Enemy(number, sprite.tile_x * 16 + 8, sprite.tile_y * 16 + 8, original, picture))
        # Not the caves, and not a room with none: it is listed for a seed with enemies' health shuffled
        if tile in SUPERTILES and enemies:
            assert all(check in checks for check in opens.get("checks", ())), name
            found[name] = KillRoom(tile, tuple(enemies), **opens)
    return found


KILL_ROOMS = _rooms()
ROOMS_BY_TILE: dict[Tile, list[str]] = {}
for _name, _room in KILL_ROOMS.items():
    ROOMS_BY_TILE.setdefault(_room.tile, []).append(_name)
KILL_CHECKS = {check: name for name, room in KILL_ROOMS.items() for check in room.checks}  # check -> its kill room

# As much of a seed as the randomizer's kill rule asks of one. Not swordless, the bow takes no arrows bought, and
# bombs take room for them: a seed without a bomb bag starts with that
_WORLD = SimpleNamespace(
    damage_table={1: DamageTable()},
    data_tables={1: SimpleNamespace(enemy_stats=_STATS)},
    swords={1: "random"},
    bow_mode={1: "progressive"},
    bombbag={1: True},
    difficulty_adjustments={1: "normal"},
    shops={1: []},
)


class _Region:
    """A dungeon's region: in neither world, which some enemies' health goes by."""

    is_light_world = is_dark_world = False


_REGION = _Region()
BOMB_BAG = "Bomb Upgrade (+10)"


def _rule(rule) -> Rule:
    """One of the randomizer's rules, as built by its own code, as a Rule."""
    kind = rule.rule_type
    if kind in (RuleType.Conjunction, RuleType.Disjunction):
        # With nothing in it either is met, as the randomizer evaluates it
        return combine("all" if kind == RuleType.Conjunction else "any", [_rule(part) for part in rule.sub_rules]) if rule.sub_rules else True
    if kind == RuleType.Static:
        return bool(rule.principal)
    if kind == RuleType.Item:
        item = rule.principal
        if item == BOMB_BAG:
            return "Bombs"
        # The randomizer asks for a "Red_Boomerang", which is no item and so never held
        if item not in item_table:
            return False
        return item if item in READABLE else True
    # More magic than one bar holds, which takes a bottle and a potion shop: not known, so met
    return True


class _Choices:
    """Stands in for the randomizer's random numbers: makes the choices it is told to and then the first of each,
    and notes how many each choice was between."""

    def __init__(self, path: tuple[int, ...]) -> None:
        self.path = path
        self.sizes: list[int] = []

    def choice(self, options: list):
        at = len(self.sizes)
        self.sizes.append(len(options))
        return options[self.path[at] if at < len(self.path) else 0]


@cache
def clearing(name: str, kinds: tuple[str, ...]) -> Rule:
    """What killing a kill room's enemies takes.

    kinds: the kind of each of the room's enemies, in their order, or NA.
    Where the randomizer finds several ways as good as each other it picks one at random, which a seed does not
    record: any of them is taken as enough.
    """
    column, row = KILL_ROOMS[name].tile
    pairs = []
    for enemy, kind in zip(KILL_ROOMS[name].enemies, kinds, strict=True):
        if kind != NA:
            # As enemy shuffle leaves it: where it was, with another kind
            sprite = _SPRITES[row * 16 + column][enemy.number].copy()
            sprite.kind = EnemySprite[kind]
            pairs.append((sprite, _REGION))
    if not pairs:
        return True
    found = []
    paths: list[tuple[int, ...]] = [()]
    while paths:
        path = paths.pop()
        choices = _Choices(path)
        setattr(EnemyLogic, "random", choices)
        found.append(_rule(EnemyLogic.defeat_rule_multiple(_WORLD, 1, pairs)))
        # Every other choice it could have made after the ones it was told to
        for at in range(len(path), len(choices.sizes)):
            paths += [(*path, *[0] * (at - len(path)), other) for other in range(1, choices.sizes[at])]
    return combine("any", found)
