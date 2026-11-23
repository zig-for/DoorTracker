"""Colours and sizes used to draw the map."""

from dataclasses import dataclass

from PIL import ImageColor

from gui.Doors.graph_model import CheckState, DoorState

DOOR_RADIUS = 5.5  # an unexplored door; linked and interior doors are drawn smaller

DUNGEON_COLOURS = {
    "Hyrule_Castle": "#566573",
    "Eastern_Palace": "#2e8b57",
    "Desert_Palace": "#b9892b",
    "Tower_of_Hera": "#b4532a",
    "Castle_Tower": "#8e5bb5",
    "Palace_of_Darkness": "#5b3f96",
    "Swamp_Palace": "#2878b5",
    "Skull_Woods": "#6b8e23",
    "Thieves_Town": "#8b5a2b",
    "Ice_Palace": "#3aa6c9",
    "Misery_Mire": "#8f8f2a",
    "Turtle_Rock": "#c0392b",
    "Ganons_Tower": "#2c2c34",
}
UNKNOWN_DUNGEON_COLOUR = "#666666"

BACKGROUND = "#eef0f3"
DOOR_OPEN = "#1fd655"
BLOCKED = "#e0262c"  # a door or a check the player's items do not let them get to
DOOR_LINKED = "#9aa0a6"
DOOR_INTERIOR = "#1b2a8a"
DOOR_SELECTED = "#ff9800"
PLAYER = "#e60000"
EDGE_FADED = "#c9cdd4"
WARP_COLOUR = "#7b4fc4"
DROP_COLOUR = "#4a4f57"
OUTLINE = "#111"  # around a door dot or a check


@dataclass(frozen=True)
class DoorStyle:
    fill: str
    scale: float  # of DOOR_RADIUS
    outline: float  # width
    edge: str = OUTLINE  # the outline's colour


# How a door dot is drawn, by its state
DOOR_STYLES = {
    DoorState.OPEN: DoorStyle(DOOR_OPEN, 1.0, 1.5),
    DoorState.BLOCKED: DoorStyle(BLOCKED, 1.0, 1.5),
    # Hollow, as a check the map does not lead to is
    DoorState.UNROUTED: DoorStyle(OUTLINE, 1.0, 2, DOOR_OPEN),
    DoorState.LINKED: DoorStyle(DOOR_LINKED, 0.7, 1),
    DoorState.INTERIOR: DoorStyle(DOOR_INTERIOR, 0.7, 1),
}


@dataclass(frozen=True)
class CheckStyle:
    fill: str
    outline: str


# How a check's square is drawn until it is collected; then it is the grey of a linked door
CHECK_STYLES = {
    CheckState.OPEN: CheckStyle(DOOR_OPEN, OUTLINE),
    CheckState.BLOCKED: CheckStyle(BLOCKED, OUTLINE),
    # Hollow: it may well be findable, but the map does not show the way yet
    CheckState.UNROUTED: CheckStyle(OUTLINE, DOOR_OPEN),
    CheckState.UNROUTED_BLOCKED: CheckStyle(OUTLINE, BLOCKED),
}
CHECK_COLLECTED = CheckStyle(DOOR_LINKED, OUTLINE)

# What a boss, or one of a kill room's enemies, is drawn on: light, as two kinds of enemy are all but black. Red
# while the player's items do not beat it, and grey for an enemy that need not be killed
PLATE = "#e4e7ec"
PLATE_BLOCKED = "#f2a3a6"
PLATE_NA = DOOR_LINKED


def dungeon_colour(dungeon: str | None) -> str:
    """Colour for the supertiles of a dungeon; grey when the dungeon is not known."""
    return DUNGEON_COLOURS.get(dungeon, UNKNOWN_DUNGEON_COLOUR) if dungeon else UNKNOWN_DUNGEON_COLOUR


def lighten(colour: str, amount: float) -> str:
    r, g, b = ImageColor.getrgb(colour)[:3]
    r, g, b = (int(c + (255 - c) * amount) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def link_colours(n: int) -> list[str]:
    """n distinct hues, dark enough to read on the light background."""
    colours = []
    for i in range(n):
        # Golden angle hue steps
        hue = (i * 137.508) % 360
        r, g, b = ImageColor.getrgb(f"hsl({hue:.0f}, 78%, {38 + (i % 3) * 6}%)")[:3]
        colours.append(f"#{r:02x}{g:02x}{b:02x}")
    return colours


