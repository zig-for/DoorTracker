"""The door randomizer's rules: the items it takes to go through a door or passage, or to collect a check.

Read when the tracker starts, out of the randomizer (gui/Doors/randomizer.py): Rules.py sets the rules, and
CollectionState in BaseClasses.py defines the tests they use, like can_lift_rocks. They are read as they are
written and not run. The randomizer only has rules once it has generated a whole seed, and by then one that holds
in every seed looks the same as one that depends on that seed's settings.

What holds in every seed is kept as it is. A rule set under an "if" depends on the seed. Where the map can say
whether the "if" holds, the rule is kept with it: a door the seed has made a trap door, one it has not made a way
in to the dungeon, and a room's boss. The others count as met, and so do key doors and dark rooms and events the
tracker cannot read, so a rule here never asks for more than the randomizer does. What beating each boss takes is
read from Bosses.py, for a room's boss once the player has picked it (gui/Doors/bosses.py).

A door that is only come in by, like the sanctuary's north door, has no rule in Rules.py: the randomizer has it as
blocked, in Doors.py. It is kept here as a way out that nothing opens.

Three settings can be told from the game: a standard seed is one where Zelda has not been delivered yet, a
swordless seed has its own mark where the sword is kept, and the ROM says whether the dam or the way in to the
swamp's palace is moved. The rules set for those seeds are kept as holding in them. The seed's logic is taken as
no-glitches.
"""

import ast
import types

from data.doors_data import regions_to_doors
from gui.Doors.checks import checks
from gui.Doors.logic import BLUE, EITHER, HEARTS, OPEN_FLOODGATE, ORANGE, READABLE, SWAMP_IN_PLACE, SWORDLESS, ZELDA_DELIVERED, Rule, combine, enough_magic, negated
from gui.Doors.randomizer import doors_and_portals, dungeon_regions, syntax

# After gui.Doors.randomizer, which makes the randomizer importable
from ALttPDoorRandomizer import Doors, Rules  # noqa: E402
from ALttPDoorRandomizer.BaseClasses import CollectionState  # noqa: E402
from ALttPDoorRandomizer.Bosses import boss_table  # noqa: E402
from ALttPDoorRandomizer.DoorShuffle import trap_door_exceptions  # noqa: E402
from ALttPDoorRandomizer.DungeonGenerator import special_big_key_doors  # noqa: E402
from ALttPDoorRandomizer.Regions import location_events  # noqa: E402  location -> the event it gives

# The randomizer's functions whose rules are read, in the order set_rules gets to them: a later rule can add to an
# earlier one, or take its place. With each, what holds in the seeds its rules are set in: True for every seed
FUNCTIONS: tuple[tuple[types.FunctionType, Rule], ...] = (
    (Rules.global_rules, True),
    (Rules.swordless_rules, SWORDLESS),
    (Rules.forbid_bomb_jump_requirements, True),  # set in no-glitches
    (Rules.standard_rules, ("not", ZELDA_DELIVERED)),
    (Rules.bomb_rules, True),
    (Rules.set_rules, True),  # the rules it sets itself, after the others
)
# An "if" about a setting of the seed that is read from the game, as the randomizer writes it -> what holds in the
# seeds that have it
SETTINGS: dict[str, Rule] = {"world.swamp_patch_required[player]": ("not", SWAMP_IN_PLACE)}
# Tests whose definition asks about the seed's settings: the item that stands for them
TESTS_BY_HAND = {
    "can_use_bombs": "Bombs",  # needs the bomb bag where there is one: read as room for bombs
    "can_shoot_arrows": "Bow",  # also needs arrows to buy, in retro
}
# Tests of a region, not of what is held: the crystal barriers that are down when it is reached
COLOURS = {"can_reach_blue": BLUE, "can_reach_orange": ORANGE}
# What a rule can be set under that the map can tell: ("trapped", door) for a door the seed has made a trap door,
# ("not entrance", door) for one it has not made a way in to the dungeon, and ("boss", region, boss) for the boss
# of the boss room a region is in
Condition = tuple[str, ...]


def called(node: ast.AST) -> str | None:
    """The name a call is made by: f(...) or anything.f(...)."""
    if not isinstance(node, ast.Call):
        return None
    if isinstance(node.func, ast.Name):
        return node.func.id
    return node.func.attr if isinstance(node.func, ast.Attribute) else None


def text(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


class Reader:
    """Turns what the randomizer writes for a rule into a Rule."""

    def __init__(self, events: set[str]) -> None:
        """events: what the randomizer counts as items that the tracker works out for itself; see read()."""
        self.events = events
        self.regions = {region.name for region in dungeon_regions()}  # the ones a rule can ask about
        # The tests of CollectionState, by name
        self.tests = {f.name: f for f in syntax(CollectionState).body if isinstance(f, ast.FunctionDef)}
        self.named: dict[str, Rule] = {}  # the rules the function being read keeps under a name, to set later

    def test(self, name: str) -> Rule:
        """A test as a rule: its body, when that is one expression."""
        if name in TESTS_BY_HAND:
            return TESTS_BY_HAND[name]
        body = [s for s in self.tests[name].body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
        if len(body) == 1 and isinstance(body[0], ast.Return) and body[0].value is not None:
            return self.rule(body[0].value)
        return True

    def rule(self, node: ast.AST) -> Rule:
        """A rule as Rules.py writes it, or an expression inside a test. Whatever is not understood is met."""
        if isinstance(node, ast.Name) and node.id in ("TRUE", "FALSE"):
            return node.id == "TRUE"
        if isinstance(node, ast.Name):
            return self.named.get(node.id, True)
        if isinstance(node, ast.BoolOp):
            return combine("all" if isinstance(node.op, ast.And) else "any", [self.rule(v) for v in node.values])
        name = called(node)
        if not isinstance(node, ast.Call) or name is None:
            return True
        if name in ("Has", "has"):
            item = text(node.args[0])
            # An item the tracker can neither read nor work out, or more than one of it, counts as held
            return item if item is not None and (item in READABLE or item in self.events) and len(node.args) == 2 else True
        if name in ("and_rule", "or_rule"):
            return combine("all" if name == "and_rule" else "any", [self.rule(a) for a in node.args])
        if name == "not_rule":
            inner = self.rule(node.args[0])
            # What is not understood is met, and the lack of it is met too
            return True if isinstance(inner, bool) else ("not", inner)
        if name == "Reach" and len(node.args) == 3 and text(node.args[1]) == "Region":
            region = text(node.args[0])
            return ("reached", region) if region in self.regions else True
        # Enough magic, asked for in two ways, each with how much after the player. Where no amount is given it
        # is 16, and one that is not written out as a number is not known, so met
        amounts = None
        if name == "Primitive" and text(node.args[0]) == "can_extend_magic":
            amounts = node.args[2:3]
        elif name == "can_extend_magic":
            amounts = node.args[1:2]
        if amounts is not None:
            if not amounts:
                return enough_magic(16)
            amount = amounts[0]
            return enough_magic(amount.value) if isinstance(amount, ast.Constant) and isinstance(amount.value, int) else True
        if name == "Primitive" and len(node.args) == 2:
            return self.test(str(text(node.args[0])))
        if name == "Primitive" and text(node.args[0]) == "has_hearts" and len(node.args) == 3:
            count = node.args[2]
            return HEARTS[count.value - 1] if isinstance(count, ast.Constant) and isinstance(count.value, int) else True
        if name == "Primitive" and text(node.args[0]) in COLOURS and len(node.args) == 3:
            # A region reached with the blue crystal barriers down, or the orange
            asked = node.args[1]
            region = text(asked.args[0]) if isinstance(asked, ast.Call) and called(asked) == "get_region" else None
            return ("down", region, COLOURS[str(text(node.args[0]))]) if region in self.regions else True
        # A test asked of the state: self inside CollectionState, state in a boss's rule
        on_state = isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id in ("self", "state")
        if on_state and name in self.tests and len(node.args) == 1:
            return self.test(name)
        return True

    def condition(self, test: ast.expr) -> Condition | None:
        """What an "if" in Rules.py asks of the seed, or None where the map cannot tell."""
        if called(test) == "is_trapped":
            assert isinstance(test, ast.Call)
            door = text(test.args[0])
            return ("trapped", door) if door else None
        if isinstance(test, ast.Attribute) and test.attr == "trapped" and isinstance(test.value, ast.Attribute) and test.value.attr == "door":
            # world.get_entrance(door, player).door.trapped, which is what is_trapped asks
            entrance = test.value.value
            door = text(entrance.args[0]) if isinstance(entrance, ast.Call) and called(entrance) == "get_entrance" else None
            return ("trapped", door) if door else None
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            asked = test.operand
            door = door_of(asked.value) if isinstance(asked, ast.Attribute) and asked.attr == "entranceFlag" else None
            return ("not entrance", door) if door else None
        if isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq):
            # world.get_region(region, player).dungeon.bosses[level].name == boss. Ganon's Tower is the dungeon
            # with a boss on each level, and there the region asked by is the boss's own room
            boss = text(test.comparators[0])
            asked = test.left
            if isinstance(asked, ast.Attribute) and asked.attr == "name" and isinstance(asked.value, ast.Subscript):
                bosses = asked.value.value
                if isinstance(bosses, ast.Attribute) and bosses.attr == "bosses" and isinstance(bosses.value, ast.Attribute):
                    region = bosses.value.value
                    name = text(region.args[0]) if isinstance(region, ast.Call) and called(region) == "get_region" else None
                    if boss is not None and boss in boss_table and name is not None and name in self.regions:
                        return ("boss", name, boss)
        return None

    def function(self, statements: list[ast.stmt]) -> Rule:
        """A rule written as a function's body: a returned expression, after any number of "if not this: return
        False" and "if this: return True"."""
        first, rest = statements[0], statements[1:]
        if isinstance(first, ast.Return) and first.value is not None:
            return self.rule(first.value)
        if isinstance(first, ast.If) and not first.orelse and len(first.body) == 1 and isinstance(first.body[0], ast.Return):
            gives, test = first.body[0].value, first.test
            if isinstance(gives, ast.Constant) and gives.value is False and isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
                return combine("all", [self.rule(test.operand), self.function(rest)])
            if isinstance(gives, ast.Constant) and gives.value is True and not isinstance(test, ast.UnaryOp):
                return combine("any", [self.rule(test), self.function(rest)])
        return True


def spot(node: ast.AST, loop: dict[str, list[str]]) -> list[tuple[str, str]]:
    """What a rule is set on: [(kind, name)] for world.get_entrance(name, player) or get_location."""
    kind = called(node)
    if not isinstance(node, ast.Call) or kind not in ("get_entrance", "get_location") or not node.args:
        return []
    named, literal = node.args[0], text(node.args[0])
    names = [literal] if literal else loop.get(named.id, []) if isinstance(named, ast.Name) else []
    return [(kind, name) for name in names]


def told(test: ast.expr) -> Rule | None:
    """What holds where an "if" about one of SETTINGS does, or where one that asks for the lack of it does. None
    for any other "if"."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        setting = SETTINGS.get(ast.unparse(test.operand))
        return None if setting is None else negated(setting)
    return SETTINGS.get(ast.unparse(test))


def read_rules(reader: Reader) ->tuple[dict[tuple[str, str], Rule], dict[tuple[str, str], dict[Condition, Rule]]]:
    """The rules the randomizer sets, by (kind, name): the rule set outright or in a loop over a list of names, and
    the rules set under an "if" the map can tell, by its condition."""
    found: dict[tuple[str, str], Rule] = {}
    sometimes: dict[tuple[str, str], dict[Condition, Rule]] = {}
    in_place: set[tuple[str, str]] = set()  # the ones a set_rule under an "if" is for
    lists: dict[str, list[str]] = {}

    def statement(node: ast.stmt, loop: dict[str, list[str]], under: Condition | None, given: Rule) -> None:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.List) and isinstance(node.targets[0], ast.Name):
            lists[node.targets[0].id] = [name for name in map(text, node.value.elts) if name]
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and under is None and not loop:
            reader.named[node.targets[0].id] = reader.rule(node.value)
        elif isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            over = node.iter
            names = lists.get(over.id, []) if isinstance(over, ast.Name) else [n for n in map(text, over.elts) if n] if isinstance(over, ast.List) else []
            for inner in node.body:
                statement(inner, {node.target.id: names}, under, given)
        elif isinstance(node, ast.If) and not node.orelse:
            setting = told(node.test)
            condition = reader.condition(node.test) if under is None else None
            if setting is not None:
                for inner in node.body:
                    statement(inner, loop, under, combine("all", [given, setting]))
            elif condition is not None:
                for inner in node.body:
                    statement(inner, loop, condition, given)
        elif isinstance(node, ast.Expr) and called(node.value) in ("set_rule", "add_rule"):
            assert isinstance(node.value, ast.Call)
            rule = reader.rule(node.value.args[1])
            replaces = called(node.value) == "set_rule"

            def now(had: Rule) -> Rule:
                """The rule after this one is set, in place of the one there was or added to it. In the seeds this
                is not set in, the one there was stays."""
                if replaces:
                    return combine("any", [combine("all", [given, rule]), combine("all", [negated(given), had])])
                return combine("all", [had, combine("any", [negated(given), rule])])

            for key in spot(node.value.args[0], loop):
                if under is None:
                    found[key] = now(found.get(key, True))
                else:
                    conditional = sometimes.setdefault(key, {})
                    conditional[under] = now(conditional.get(under, True))
                    if replaces:
                        in_place.add(key)

    for function, given in FUNCTIONS:
        reader.named = {}
        for node in syntax(function).body:
            statement(node, {}, None, given)
    # A rule under an "if" is kept as adding to the one set outright. None is set in place of one
    assert not in_place & set(found), in_place & set(found)
    return found, sometimes


def read() -> tuple[dict[str, Rule], dict[str, dict[Condition, Rule]], dict[str, Rule], dict[str, str], dict[str, tuple[str, Rule]]]:
    """(passage rules, the passage rules that depend on the seed, check rules, each check's region, events)."""
    # Each location in a dungeon -> its region
    where = {location.name: region.name for region in dungeon_regions() for location in region.locations}

    # The randomizer gives an "item" for doing something somewhere, like pulling the lever that drains the swamp.
    # The tracker cannot read those, but for the ones done in a dungeon it can work out whether the place can be
    # reached. Event -> where it is done
    gives = location_events
    done_at = {event: location for location, event in gives.items() if list(gives.values()).count(event) == 1 and location in where}
    # Whether Zelda has been delivered is read from the game
    del done_at[ZELDA_DELIVERED]

    # Whether the dam's lever has been pulled is read too
    reader = Reader({*done_at, ZELDA_DELIVERED, OPEN_FLOODGATE})
    found, sometimes = read_rules(reader)
    walked = {name for names in regions_to_doors.values() for name in names}
    passages = {name: rule for (kind, name), rule in found.items() if kind == "get_entrance" and name in walked and rule is not True}
    # The randomizer goes out by no door or passage it has as blocked (update_reachable_regions in BaseClasses.py),
    # and a seed only opens the trap doors among them. The others are no way out in any seed
    passages |= {door.name: False for door in doors_and_portals()[0] if door.blocked and not door.trapFlag and door.name in walked}
    # Every rule that depends on the seed is a passage's
    assert all(kind == "get_entrance" and name in walked for kind, name in sometimes)
    seeded = {name: rules for (_kind, name), rules in sometimes.items()}
    of_checks = {name: rule for (kind, name), rule in found.items() if kind == "get_location" and name in checks and rule is not True}
    regions = {name: where[name] for name in checks}
    happen = {event: (where[location], found.get(("get_location", location), True)) for event, location in done_at.items()}
    return passages, seeded, of_checks, regions, happen


def door_of(node: ast.expr) -> str | None:
    """The door a chain of calls is about: world.get_door(name, player).x() or create_door(player, name, kind).x().y()."""
    while isinstance(node, ast.Call):
        if called(node) == "get_door":
            return text(node.args[0])
        if called(node) == "create_door":
            return text(node.args[1])
        if not isinstance(node.func, ast.Attribute):
            return None
        node = node.func.value
    return None


def read_crystals() -> dict[str, int]:
    """Door or passage -> the crystal barriers that must be down to go through it, which are the ones down after:
    BLUE or ORANGE. EITHER for the way back from where a crystal switch is hit: after it, whichever the player
    likes."""
    names = {"Blue": BLUE, "Orange": ORANGE, "Either": EITHER}
    found = {}
    for node in ast.walk(syntax(Doors.create_doors)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("barrier", "c_switch"):
            door = door_of(node.func.value)
            assert door is not None
            if node.func.attr == "c_switch":
                found[door] = EITHER
            else:
                colour = node.args[0]
                assert isinstance(colour, ast.Attribute)
                found[door] = names[colour.attr]
    return found


def read_door_kinds() -> dict[str, Rule]:
    """Kind of door a seed can make a door, by DoorKind's name for it -> what going through one takes: as bomb_rules
    sets it on every door of that kind, in a seed with doors shuffled."""
    reader = Reader(set())
    found = {}
    for node in ast.walk(syntax(Rules.bomb_rules)):
        # if door.kind(world) in [DoorKind.Dashable]: add_rule(door.entrance, rule)
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and called(node.test.left) == "kind":
            (kinds,) = node.test.comparators
            first = node.body[0]
            assert isinstance(kinds, ast.List) and isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
            for kind in kinds.elts:
                assert isinstance(kind, ast.Attribute)
                found[kind.attr] = reader.rule(first.value.args[1])
    return found


def read_bosses() -> dict[str, tuple[Rule, Rule]]:
    """Boss -> what beating it takes, and what it takes on an icy floor."""
    reader = Reader(set())

    def rule(function) -> Rule:
        body = syntax(function).body
        return reader.function([s for s in body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))])

    return {boss: (rule(usual), rule(on_ice)) for boss, (_name, usual, on_ice) in boss_table.items()}


# What leaving a region through a door or passage takes; what it takes besides for what a seed can make of it, as
# {condition: rule}; what collecting a check takes, once in its region; the region each check is in; and
# event -> (the region it is done in, what doing it takes)
passage_rules, seeded_rules, check_rules, check_regions, events = read()
crystals = read_crystals()
door_kind_rules = read_door_kinds()
# A trap door is no way out, but for these, which are one with whatever their rules take: the ones the randomizer
# keeps as a way out when a seed makes them trap doors, and the original game's trap doors that are a way out
open_trap_doors = frozenset(trap_door_exceptions) | {door.name for door in doors_and_portals()[0] if door.trapFlag and not door.blocked}
boss_rules = read_bosses()
# The passages that take the big key of the dungeon they are in, in every seed: into Zelda's cell and into Blind's.
# The randomizer gives them the rule with a seed's big key doors, which is why Rules.py does not set it
big_key_passages = frozenset(special_big_key_doors)
