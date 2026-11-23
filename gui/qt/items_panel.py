"""The items panel: the game's item menu with what the player holds lit, and each dungeon's keys. It floats over a
corner of the map, and its tab hides it."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPalette, QPixmap, QPolygonF
from PySide6.QtWidgets import QAbstractButton, QGridLayout, QHBoxLayout, QLabel, QLayout, QVBoxLayout, QWidget

from gui.Doors.logic import BIG_KEYS, BOTTLES, FIRST_HEARTS, HEARTS, MAGIC_BARS, STARTING_ITEMS, hearts_held, with_hearts
from gui.Doors.randomizer import FOLDER

PICTURES = FOLDER / "data" / "itemgfx"  # the randomizer's own, 32 pixels high
CELL = 32
KEY_CELL = 18  # width of a dungeon's column of keys
PANEL_COLOUR = "#16161a"  # near the black of the game's menu, which the pictures are drawn for
TEXT_COLOUR = "#f0f0f0"
CORNER = 6  # radius of the rounded corners
# item -> its picture's name, where that is not the item's
PICTURE_NAMES = {
    "Blue Boomerang": "Boomerang",
    "Bombs": "Bomb",
    "Bug Catching Net": "Bug Net",
    "Cane of Somaria": "Somaria",
    "Cane of Byrna": "Byrna",
    "Cape": "Magic Cape",
    "Titans Mitts": "Titans Mitt",
    "Red Shield": "Fire Shield",
    "Magic Upgrade (1/2)": "Half Magic",
    "Magic Upgrade (1/4)": "Quarter Magic",
    **dict.fromkeys(BOTTLES, "Bottle"),
}
BIG_KEY_PICTURE = "Big Key"


@dataclass(frozen=True)
class Slot:
    """One place in the grid, and the items that can be in it."""

    items: tuple[str, ...]
    together: bool = False  # the items share it; otherwise each takes the place of the one before
    start: str | None = None  # picture of what the player has in it from the start
    counted: bool = False  # each item is one more of the same thing, up to four: how many are held is put on it


def one(item: str) -> Slot:
    return Slot((item,))


# The grid of items in the game's menu, and what the menu shows apart from it: abilities and equipment
MENU = [
    [one("Bow"), Slot(("Blue Boomerang", "Red Boomerang"), together=True), one("Hookshot"), one("Bombs"), Slot(("Mushroom", "Magic Powder"), together=True)],
    [one("Fire Rod"), one("Ice Rod"), one("Bombos"), one("Ether"), one("Quake")],
    [one("Lamp"), one("Hammer"), Slot(("Shovel", "Ocarina"), together=True), one("Bug Catching Net"), one("Book of Mudora")],
    [Slot(tuple(BOTTLES), counted=True), one("Cane of Somaria"), one("Cane of Byrna"), one("Cape"), one("Magic Mirror")],
]
ABILITIES = [one("Pegasus Boots"), Slot(("Power Glove", "Titans Mitts")), one("Flippers"), one("Moon Pearl")]
UPGRADES = [Slot(tuple(MAGIC_BARS))]
EQUIPMENT = [
    Slot(("Fighter Sword", "Master Sword", "Tempered Sword", "Golden Sword")),
    Slot(("Blue Shield", "Red Shield", "Mirror Shield")),
    Slot(("Blue Mail", "Red Mail"), start="Green Mail"),
]
SLOTS = [slot for row in (*MENU, ABILITIES, EQUIPMENT, UPGRADES) for slot in row]
SWORDS = EQUIPMENT[0].items  # each one's picture has its level on it, 1 to 4
NUMBER_FROM = 18  # that number is right of this and below it, in a picture 32 across
NUMBER_EDGE = 2  # how far the edge put round it reaches: one of the picture's own pixels, which are doubled
# A counted slot's items are one item, however many of it
ITEMS = [item for slot in SLOTS for item in (*([slot.start] if slot.start else []), *(slot.items[:1] if slot.counted else slot.items))]
# The tracker's name for a dungeon -> what the keys strip calls it, in the order of the tabs
SHORT_NAMES = {
    "Hyrule_Castle": "HC",
    "Eastern_Palace": "EP",
    "Desert_Palace": "DP",
    "Tower_of_Hera": "TH",
    "Castle_Tower": "AT",
    "Palace_of_Darkness": "PD",
    "Swamp_Palace": "SP",
    "Skull_Woods": "SW",
    "Thieves_Town": "TT",
    "Ice_Palace": "IP",
    "Misery_Mire": "MM",
    "Turtle_Rock": "TR",
    "Ganons_Tower": "GT",
}


@cache
def picture(name: str) -> QPixmap:
    """One of the randomizer's item pictures. Read once: every tab's panel shows them, anew on each change."""
    return QPixmap(str(PICTURES / f"{name}.gif"))


def greyed(lit: QPixmap) -> QPixmap:
    """A picture as a placeholder: grey and faint."""
    faint = QPixmap(lit.size())
    faint.fill(Qt.GlobalColor.transparent)
    painter = QPainter(faint)
    painter.setOpacity(0.4)
    painter.drawImage(0, 0, lit.toImage().convertToFormat(QImage.Format.Format_Grayscale8))
    # The grey copy has lost what was see-through: cut it back to the picture's shape
    painter.setOpacity(1.0)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.drawPixmap(0, 0, lit)
    painter.end()
    return faint


def slot_picture(slot: Slot, held: frozenset[str]) -> QPixmap:
    """What a slot shows: greyed out, its first item, when none of its items is held and it starts empty."""
    mine = [item for item in slot.items if item in held]
    cell = QPixmap(CELL, CELL)
    cell.fill(Qt.GlobalColor.transparent)
    painter = QPainter(cell)
    if slot.together and len(mine) == 2:
        # Both: each at half size, which is the size the game draws them, in opposite corners
        for item, corner in zip(mine, (0, CELL // 2)):
            whole = picture(PICTURE_NAMES.get(item, item))
            half = whole.scaled(whole.width() // 2, whole.height() // 2, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
            painter.drawPixmap(corner + (CELL // 2 - half.width()) // 2, corner, half)
    else:
        item = mine[-1] if mine else slot.items[0]
        shown = picture(slot.start if slot.start and not mine else PICTURE_NAMES.get(item, item))
        painter.drawPixmap((CELL - shown.width()) // 2, 0, shown)
        if slot.counted and mine:
            painter.drawPixmap(0, 0, number(len(mine)))
    painter.end()
    return cell if mine or slot.start else greyed(cell)


@cache
def number(count: int) -> QPixmap:
    """A number from 1 to 4, where and as the picture of the sword of that level has it: in the bottom right
    corner, with a dark edge added all round it to read over another picture."""
    sword = picture(SWORDS[count - 1]).toImage()
    white, edge = QColor(248, 248, 248), QColor(40, 40, 40)
    # The corner has nothing of the sword in it but the number
    corner = [(x, y) for x in range(NUMBER_FROM, sword.width()) for y in range(NUMBER_FROM, sword.height())]
    marks = [(x, y) for x, y in corner if sword.pixelColor(x, y) == white]
    made = QImage(sword.size(), QImage.Format.Format_ARGB32)
    made.fill(Qt.GlobalColor.transparent)
    for x, y in marks:
        for near_x in range(max(0, x - NUMBER_EDGE), min(made.width(), x + NUMBER_EDGE + 1)):
            for near_y in range(max(0, y - NUMBER_EDGE), min(made.height(), y + NUMBER_EDGE + 1)):
                made.setPixelColor(near_x, near_y, edge)
    for x, y in marks:
        made.setPixelColor(x, y, white)
    return QPixmap.fromImage(made)


def hearts_picture(count: int) -> QPixmap:
    """A heart container with how many the player has written on it."""
    cell = QPixmap(CELL, CELL)
    cell.fill(Qt.GlobalColor.transparent)
    painter = QPainter(cell)
    heart = picture("Heart Container")
    painter.drawPixmap((CELL - heart.width()) // 2, 0, heart)
    font = QFont()
    font.setPixelSize(13)
    font.setBold(True)
    painter.setFont(font)
    # White on a black edge, to read over the red
    for dx, dy, colour in ((1, 1, "black"), (-1, -1, "black"), (1, -1, "black"), (-1, 1, "black"), (0, 0, "white")):
        painter.setPen(QColor(colour))
        painter.drawText(cell.rect().translated(dx, dy), Qt.AlignmentFlag.AlignCenter, str(count))
    painter.end()
    return cell


def states(slot: Slot) -> list[frozenset[str]]:
    """What can be held of a slot's items, in the order that clicking goes through."""
    if slot.together:
        first, second = slot.items
        return [frozenset(), frozenset({first}), frozenset({second}), frozenset({first, second})]
    # A better sword is held along with the lesser ones, as the game's own count has it
    return [frozenset(slot.items[:count]) for count in range(len(slot.items) + 1)]


def clicked(slot: Slot, held: frozenset[str], step: int) -> frozenset[str]:
    """What is held after a click on a slot (step 1) or a right click (step -1)."""
    choices = states(slot)
    mine = held & frozenset(slot.items)
    now = choices.index(mine) if mine in choices else 0
    return (held - mine) | choices[(now + step) % len(choices)]


class Cell(QLabel):
    """A picture or a number that a click or a right click adjusts."""

    def __init__(self, pressed: Callable[[object, int], None], what: object):
        """pressed(what, step): this was clicked (step 1) or right clicked (step -1)."""
        super().__init__()
        self.pressed = pressed
        self.what = what

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed(self.what, 1)
        elif event.button() == Qt.MouseButton.RightButton:
            self.pressed(self.what, -1)


def spread(columns: Sequence[QLayout]) -> QHBoxLayout:
    """A row with the columns spread evenly over its width."""
    row = QHBoxLayout()
    row.setSpacing(0)
    for place, column in enumerate(columns):
        if place:
            row.addStretch()
        row.addLayout(column)
    return row


def rounded(width: float, height: float) -> QPainterPath:
    """A rectangle with its top left corner rounded off: the one corner of the tab, and of the panel under it,
    that meets neither the other nor the edge of the map."""
    path = QPainterPath()
    path.moveTo(0, height)
    path.lineTo(0, CORNER)
    path.arcTo(0, 0, 2 * CORNER, 2 * CORNER, 180, -90)
    path.lineTo(width, 0)
    path.lineTo(width, height)
    path.closeSubpath()
    return path


class Tab(QAbstractButton):
    """The panel's tab, in the panel's colour: an arrow pointing the way a click moves the panel."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(36, 16)
        self.points_down = True

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillPath(rounded(self.width(), self.height()), QColor(PANEL_COLOUR))
        x, y, reach = self.width() / 2, self.height() / 2, 3.5 if self.points_down else -3.5
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(TEXT_COLOUR))
        painter.drawPolygon(QPolygonF([QPointF(x - 5, y - reach), QPointF(x + 5, y - reach), QPointF(x, y + reach)]))


class Body(QWidget):
    """What the tab opens and closes."""

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillPath(rounded(self.width(), self.height()), QColor(PANEL_COLOUR))


class ItemsPanel(QWidget):
    def __init__(self, parent: QWidget, toggled: Callable[[bool], None], changed: Callable[[frozenset[str], dict[str, int]], None]):
        """toggled(open): the tab was clicked, to open the panel or to close it.
        changed(items, small keys): a click in the panel changed what is held to this.
        """
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.toggled = toggled
        self.changed = changed
        self.items: frozenset[str] = frozenset()  # as last shown
        self.small_keys: dict[str, int] = {}
        self.tab = Tab()
        # A method, not a lambda: Qt would keep a lambda that holds this panel alive, and with it the window
        self.tab.clicked.connect(self._tab_clicked)
        column.addWidget(self.tab, alignment=Qt.AlignmentFlag.AlignRight)

        self.body = Body()
        palette = self.body.palette()
        palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT_COLOUR))
        self.body.setPalette(palette)
        self.faint = QPalette(palette)  # for a count of no keys
        self.faint.setColor(QPalette.ColorRole.WindowText, QColor("#6a6a72"))
        self.bright = palette
        column.addWidget(self.body)
        inside = QVBoxLayout(self.body)
        inside.setContentsMargins(9, 9, 9, 4)
        inside.setSpacing(4)

        self.slots: list[tuple[Slot, QLabel]] = []

        def cell(slot: Slot) -> QLabel:
            label = Cell(self._pressed, slot)
            label.setFixedSize(CELL, CELL)
            self.slots.append((slot, label))
            return label

        grid = QGridLayout()
        grid.setSpacing(2)
        inside.addLayout(grid)
        for row, slots in enumerate(MENU):
            for place, slot in enumerate(slots):
                grid.addWidget(cell(slot), row, place)
        # To the right of the menu's grid: a column of abilities, one of equipment and one of upgrades
        for place, slots in enumerate((ABILITIES, EQUIPMENT, UPGRADES)):
            for row, slot in enumerate(slots):
                grid.addWidget(cell(slot), row, len(MENU[0]) + place)
        # Under the equipment: how many hearts
        self.hearts = Cell(self._pressed, "hearts")
        self.hearts.setFixedSize(CELL, CELL)
        grid.addWidget(self.hearts, len(EQUIPMENT), len(MENU[0]) + 1)

        small = QFont(self.font())
        small.setPixelSize(10)
        self.counts: dict[str, QLabel] = {}  # small keys, by dungeon
        self.big_keys: dict[str, QLabel] = {}
        self.big_key = picture(BIG_KEY_PICTURE).scaled(CELL // 2, CELL // 2, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
        self.no_big_key = greyed(self.big_key)
        columns = []
        for dungeon, short in SHORT_NAMES.items():
            name, count, key = QLabel(short), Cell(self._pressed, ("small keys", dungeon)), Cell(self._pressed, ("big key", dungeon))
            name.setFont(small)
            column = QVBoxLayout()
            column.setSpacing(0)
            for label in (name, count, key):
                label.setFixedWidth(KEY_CELL)
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                label.setToolTip(dungeon.replace("_", " "))
                column.addWidget(label)
            columns.append(column)
            self.counts[dungeon], self.big_keys[dungeon] = count, key
        inside.addLayout(spread(columns))
        self.show_held(STARTING_ITEMS, {})

    def _tab_clicked(self) -> None:
        self.toggled(self.body.isHidden())

    def _pressed(self, what: object, step: int) -> None:
        """A slot, the hearts, a dungeon's small keys or its big key was clicked (step 1) or right clicked (step -1)."""
        items, small_keys = self.items, dict(self.small_keys)
        if isinstance(what, Slot):
            items = clicked(what, items, step)
        elif what == "hearts":
            items = with_hearts(items, min(len(HEARTS), max(FIRST_HEARTS, hearts_held(items) + step)))
        elif isinstance(what, tuple):
            kind, dungeon = what
            if kind == "big key":
                items = items ^ {BIG_KEYS[dungeon]}
            else:
                small_keys[dungeon] = max(0, small_keys.get(dungeon, 0) + step)
        self.changed(items, small_keys)

    def mousePressEvent(self, event):
        # A click between the pictures is not a click on the map under the panel
        event.accept()

    mouseReleaseEvent = mouseDoubleClickEvent = mousePressEvent

    def set_open(self, is_open: bool) -> None:
        """Show everything, or only the tab."""
        self.body.setVisible(is_open)
        self.tab.points_down = is_open
        self.tab.update()
        self.adjustSize()

    def show_held(self, items: frozenset[str], small_keys: Mapping[str, int]) -> None:
        """Light what is held."""
        self.items, self.small_keys = items, dict(small_keys)
        for slot, label in self.slots:
            mine = [item for item in slot.items if item in self.items]
            label.setPixmap(slot_picture(slot, self.items))
            label.setToolTip(", ".join(mine if slot.together else mine[-1:]) or slot.start or slot.items[0])
        hearts = hearts_held(self.items)
        self.hearts.setPixmap(hearts_picture(hearts))
        self.hearts.setToolTip(f"{hearts} hearts")
        for dungeon, count in self.counts.items():
            held = self.small_keys.get(dungeon, 0)
            count.setText(str(held))
            count.setPalette(self.bright if held else self.faint)
            self.big_keys[dungeon].setPixmap(self.big_key if BIG_KEYS[dungeon] in self.items else self.no_big_key)
