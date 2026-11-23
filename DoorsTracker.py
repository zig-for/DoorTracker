"""Janker Door Tracker: auto-tracks ALttP door randomizer dungeon layouts through SNI. Qt entry point."""

import argparse
import asyncio
import math
import signal
import sys
import traceback
from collections.abc import Container, Mapping
from pathlib import Path
from typing import Any

import yaml
from PIL import Image
from PySide6.QtCore import QByteArray, QPointF, QSize, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QKeySequence, QPainter, QPalette, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSlider,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import data.doors_sprite_data as sprites
from data.doors_data import dungeon_lobbies, eg_tile_multiuse
from data.vanilla_data import vanilla_layout_optimized
from data.worlds_data import World, dungeon_worlds
from gui import files
from gui.Doors import link_sprite, rooms, seed_map
from gui.Doors.bosses import BOSSES
from gui.Doors.checks import DROPS, Drop, checks
from gui.Doors.kill_rooms import NA, PICKS
from gui.Doors.layout import REPEL_RANGE
from gui.Doors.logic import COMPASSES, MAPS, STARTING_ITEMS, items_held, small_keys
from gui.qt.graph_page import Assets, GraphPage

WINDOW_SIZES = {"small": (1064, 632), "medium": (1588, 888), "large": (2088, 1144)}
TITLE = "Janker Door Tracker"
# The map is autosaved this long after its last change, in ms
SAVE_DELAY = 1000
# and once more this long after that if Simulate is on, as the cards keep moving
DRIFT_SAVE_DELAY = 10_000
# Holds the name of the autosave written last
LATEST = "latest.txt"
# Answers to the questions asked about a map
NEW_MAP, KEEP_MAP, USE_SAVED, DISCONNECT, CANCEL = "Start a new map", "Keep this map", "Use the saved map", "Disconnect", "Cancel"
# What is kept between launches, and its value on a first launch. A saved setting not listed here is ignored
DEFAULT_SETTINGS: dict[str, Any] = {
    "autosave": True,
    "tab": None,  # dungeon of the selected tab
    "window": None,  # QWidget.saveGeometry(), as hex
    # View and Experimental menus
    "show_all_doors": False,
    "show_checks": True,
    "show_fps": False,
    "show_items": True,  # the items panel is open; its tab changes this
    "hide_single_route_tiles": False,
    "decoupled_doors": False,
    "vanilla_drops": True,
    "trim_rooms": True,
    "split_rooms": True,
    # Toolbar
    "auto_join": True,
    "spacing": float(REPEL_RANGE),
    "dead_end_pull": 2.5,
    "circle_repulsion": False,
    "show_repulsion": False,
    "simulate": False,
    "follow_player": False,
    "labels": True,
    "map_reveals": False,
    "compass_reveals": False,
    "pottery": False,
    "enemy_drops": False,
}


def read_settings(file: Path) -> dict[str, Any]:
    """The settings a file holds. Raises if it cannot be read as settings, or a value is of the wrong kind."""
    saved = yaml.safe_load(file.read_text())
    if not isinstance(saved, dict):
        raise ValueError("not a list of settings")
    settings = {}
    for name, value in saved.items():
        if name not in DEFAULT_SETTINGS:
            continue
        default = DEFAULT_SETTINGS[name]
        if isinstance(default, bool):
            right_kind = isinstance(value, bool)
        elif isinstance(default, float):
            # yaml also reads .nan and .inf as numbers
            right_kind = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        else:
            # A setting with no default is text, once it has a value
            right_kind = value is None or isinstance(value, str)
        if not right_kind:
            raise ValueError(f"{name}: {value!r}")
        settings[name] = value
    return settings


def read_autosave(file: Path) -> dict[str, Any]:
    """The map an autosave holds. Raises if the file is not a whole autosave."""
    text = file.read_text()
    if not text.endswith("...\n"):
        raise ValueError("the file is cut short")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("not a tracker file")
    return data


# What a room counts down, by the save data's table of them -> the toolbar box that says to
COUNTED = {"pot": "pottery", "enemy": "enemy_drops"}
# The items and small keys held on a new map
NOTHING_HELD: tuple[frozenset[str], dict[str, int]] = (STARTING_ITEMS, {})
TAB_ARROW = QSize(8, 10)  # the arrow on the tab of the dungeon the player is in
# What the Help menu shows
AI_DISCLOSURE = "<p>This tracker was written with Claude. Sorry about that.</p>"
CREDITS = (
    "<p>Based on Muffins' Jank (Auto)Door Tracker.</p>"
    "<p>Logic from aerinon's <a href='https://github.com/aerinon/ALttPDoorRandomizer'>ALttP Door Randomizer</a> "
    "(<a href='https://github.com/aurabot24/ALttPDoorRandomizer'>aurabot24's fork</a>).</p>"
    "<p>Auto-tracking is through <a href='https://github.com/alttpo/sni'>SNI</a>.</p>"
    "<p>Enemy pictures from StripesOO7's "
    "<a href='https://github.com/StripesOO7/alttp-ap-poptracker-pack'>ALttP PopTracker pack</a>.</p>"
    "<p>The pictures from The Legend of Zelda: A Link to the Past are copyright Nintendo.</p>"
)


def tab_arrows(colour: QColor) -> tuple[QIcon, QIcon]:
    """The arrow for a tab, and the same space with nothing in it."""
    # Drawn larger than it is shown, which keeps its edges smooth on a dense screen
    scale = 4
    wide, tall = TAB_ARROW.width() * scale, TAB_ARROW.height() * scale
    blank = QPixmap(wide, tall)
    blank.fill(Qt.GlobalColor.transparent)
    arrow = QPixmap(blank)
    painter = QPainter(arrow)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colour)
    painter.drawPolygon(QPolygonF([QPointF(0, 0), QPointF(wide, tall / 2), QPointF(0, tall)]))
    painter.end()
    return QIcon(arrow), QIcon(blank)


def autosave_name(seed_hash: str | None) -> str:
    """Each seed's map has its own file. A map not yet seen in a game has no seed."""
    return f"autosave-{seed_hash}.yaml" if seed_hash else "autosave.yaml"


class Picker(QDialog):
    """A dialog of buttons, each named for what it picks: choice is the name of the one clicked."""

    def __init__(self, parent, title):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.choice = None

    def _pick(self):
        self.choice = self.sender().objectName()
        self.accept()


class IconPicker(Picker):
    """The icons to put on a door: rows of marks, items and equipment, then the ways in. Those are this dungeon's
    entrances, in the same four places for every dungeon, and a place the player can get to."""

    # The marks; the items, with the two keys; the equipment. The sheet's slash mark is not here: it is the first sword
    ROWS = (
        ("Bomb Door", "Dash Door", "Trap Door", "Skull", "Checkmark", "Crossmark", "Peg Switch", "Blue Peg", "Orange Peg", "Drop"),
        ("Bow", "Blue Boomerang", "Red Boomerang", "Hookshot", "Bombs", "Mushroom", "Magic Powder", "Fire Rod", "Ice Rod", "Lamp"),
        ("Bombos", "Ether", "Quake", "Hammer", "Shovel", "Ocarina", "Bug Catching Net", "Book of Mudora", "Bottle", "Magic Mirror"),
        ("Cane of Somaria", "Cane of Byrna", "Cape", "Pegasus Boots", "Power Glove", "Titans Mitts", "Flippers", "Moon Pearl", "Key Door", "Big Key Door"),
        ("Fighter Sword", "Master Sword", "Tempered Sword", "Golden Sword", "Blue Shield", "Red Shield", "Mirror Shield", "Green Mail", "Blue Mail", "Red Mail"),
    )
    ENTRANCES = 4  # the most a dungeon has

    def __init__(self, parent, assets, world, taken):
        """taken: the entrances the map already has, which are greyed out."""
        super().__init__(parent, "Annotate door")
        grid = QGridLayout(self)
        grid.setSpacing(2)
        for row, names in enumerate(self.ROWS):
            for column, name in enumerate(names):
                grid.addWidget(self._button(name, assets, False), row, column)
        grid.setRowMinimumHeight(len(self.ROWS), 8)  # a gap above the ways in
        for column, name in enumerate(sprites.dungeon_lobbies[world]):
            grid.addWidget(self._button(name, assets, name in taken), len(self.ROWS) + 1, column)
        grid.addWidget(self._button(sprites.REACHABLE, assets, False), len(self.ROWS) + 1, self.ENTRANCES)
        grid.addWidget(self._button(sprites.CHICKEN, assets, False), len(self.ROWS) + 1, len(self.ROWS[0]) - 1)

    def _button(self, name, assets, taken):
        button = QToolButton()
        picture = assets.icon(name).scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
        icon = QIcon(picture)
        if taken:
            # Dark, where Qt's own greying of a button that cannot be pressed is pale
            painter = QPainter(picture)
            painter.fillRect(picture.rect(), QColor(0, 0, 0, 190))
            painter.end()
            icon.addPixmap(picture, QIcon.Mode.Disabled)
        button.setIcon(icon)
        button.setIconSize(QSize(32, 32))
        button.setToolTip(name.replace("_", " "))
        button.setEnabled(not taken)
        # Signals go to methods, never lambdas: Qt keeps a lambda that holds a widget alive, and the widget with it
        button.setObjectName(name)
        button.clicked.connect(self._pick)
        return button


class BossPicker(Picker):
    """The bosses a boss room can have, to pick the one it has."""

    ACROSS = 5

    def __init__(self, parent, assets):
        super().__init__(parent, "Boss")
        grid = QGridLayout(self)
        grid.setSpacing(2)
        for place, boss in enumerate(BOSSES):
            button = QToolButton()
            button.setIcon(QIcon(assets.boss(boss).scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)))
            button.setIconSize(QSize(64, 64))
            button.setToolTip(boss)
            button.setObjectName(boss)
            button.clicked.connect(self._pick)
            grid.addWidget(button, place // self.ACROSS, place % self.ACROSS)


class EnemyPicker(Picker):
    """The kinds one of a kill room's enemies can be, to pick the one it is."""

    ACROSS = 10
    SIDE = 48

    def __init__(self, parent, assets):
        super().__init__(parent, "Enemy")
        grid = QGridLayout(self)
        grid.setSpacing(2)
        for place, kind in enumerate([*PICKS, NA]):
            button = QToolButton()
            if kind == NA:
                button.setText(NA)
            else:
                side = self.SIDE - 8
                button.setIcon(QIcon(assets.enemy(kind).scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)))
                button.setIconSize(QSize(side, side))
                button.setToolTip(kind)
            button.setFixedSize(self.SIDE, self.SIDE)
            button.setObjectName(kind)
            button.clicked.connect(self._pick)
            grid.addWidget(button, place // self.ACROSS, place % self.ACROSS)


class EgPicker(QDialog):
    """Pick a supertile to add. Each dungeon's tab is its vanilla layout, with its other supertiles underneath."""

    def __init__(self, parent, assets, unavailable):
        super().__init__(parent)
        self.setWindowTitle("Add supertile")
        self.choice = None
        self.buttons = {}  # by supertile
        tabs = QTabWidget()
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)

        # Supertiles the vanilla layouts leave out, by dungeon
        laid_out = {tile for layout_data in vanilla_layout_optimized.values() for tile in layout_data["tiles"]}
        left_out = {}
        for tile in sorted(rooms.SUPERTILES):
            if tile not in laid_out:
                left_out.setdefault(rooms.SUPERTILES[tile].dungeon, []).append(tile)

        for name, layout_data in vanilla_layout_optimized.items():
            tiles = layout_data["tiles"]
            if not tiles:
                continue
            page = QWidget()
            grid = QGridLayout(page)
            grid.setSpacing(3)
            columns = [t["map_tile"][0] for t in tiles.values()]
            rows = [t["map_tile"][1] for t in tiles.values()]
            for tile, placement in tiles.items():
                button = self._button(tile, assets, unavailable)
                grid.addWidget(button, placement["map_tile"][1] - min(rows), placement["map_tile"][0] - min(columns))
            # A gap, then the rest in rows as wide as the layout
            width = max(columns) - min(columns) + 1
            below = max(rows) - min(rows) + 1
            grid.setRowMinimumHeight(below, 12)
            for index, tile in enumerate(left_out.get(name, [])):
                grid.addWidget(self._button(tile, assets, unavailable), below + 1 + index // width, index % width)

            tabs.addTab(page, "Other Lobby Tiles" if name == "Lobbyable_Tiles" else name.replace("_", " "))
            if name == parent.current_dungeon():
                tabs.setCurrentWidget(page)

    def _button(self, tile, assets, unavailable):
        button = QToolButton()
        button.setIcon(QIcon(assets.thumbnail(tile, 96)))
        button.setIconSize(QSize(96, 96))
        button.setToolTip(rooms.WHOLE.title(rooms.Node(*tile)))
        # Disabled if already on the map or used up
        button.setEnabled(tile not in unavailable)
        button.clicked.connect(self._pick)
        self.buttons[tile] = button
        return button

    def _pick(self):
        self.choice = next(tile for tile, button in self.buttons.items() if button is self.sender())
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self, args: argparse.Namespace, settings_file: Path | None = None):
        """settings_file: where the options are kept between launches. None to not keep them."""
        super().__init__()
        self.args = args
        self.settings_file = settings_file
        # Shared with every page's model
        self.settings: dict[str, Any] = dict(DEFAULT_SETTINGS)
        if settings_file is not None and settings_file.exists():
            try:
                self.settings.update(read_settings(settings_file))
            except Exception as error:
                traceback.print_exc()
                QMessageBox.warning(
                    self,
                    "Settings not loaded",
                    f"{settings_file}\n\n{error!r}\n\nThe default settings are used. The file is replaced the next "
                    "time a setting changes, or when the tracker closes.",
                )
        self.autosave: Path | None = None  # folder; see start_autosave
        self._latest: str | None = None  # autosave file the next launch loads, as LATEST says
        self.autosave_on: bool = self.settings["autosave"]  # File -> Autosave, for this run
        self.seed_hash: str | None = None  # of the game the map was made on, once known; kept in the tracker file
        # Checks collected, with pots emptied and enemy drops taken, by name in gui/Doors/checks.py; kept in the
        # tracker file
        self.collected: set[str] = set()
        self._held: tuple[frozenset[str], dict[str, int]] = NOTHING_HELD  # the items and small keys: read, clicked, or loaded with the map
        self._player_heads: list[QPixmap] = []  # see player_sprite_read
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_after_change)
        self._drift_timer = QTimer(self)
        self._drift_timer.setSingleShot(True)
        self._drift_timer.timeout.connect(self._write_autosave)
        self.setWindowTitle(TITLE)
        geometry = None if args.size else self.settings["window"]
        # restoreGeometry returns False for bytes that are not a geometry
        if not (geometry and self.restoreGeometry(QByteArray.fromHex(geometry.encode()))):
            self.resize(*WINDOW_SIZES[args.size or "medium"])
        self.device: str | None = None
        self._connected = False
        self._game_seed: str | None = None  # the seed of the game being read, once the auto-tracker has said
        self.cheat_wanted = False  # the cheat was asked for, and has not been done yet
        self._adopt_seed = False  # see new_map
        self.sni_task: asyncio.Task | None = None
        self.loop: asyncio.AbstractEventLoop | None = None

        eg_map = Path(__file__).parent / "data" / "maps" / "egmap.png"
        self.assets = Assets(Image.open(eg_map))

        self.tabs = QTabWidget()
        # The toolbar is above the tabs: what it sets is the same in every tab
        central = QWidget()
        column = QVBoxLayout(central)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._build_toolbar())
        column.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        self.pages: dict[str, GraphPage] = {}  # by dungeon, in tab order
        for dungeon, world in dungeon_worlds.items():
            if dungeon in ("Overworld", "Underworld"):
                continue
            page = GraphPage(self, world, self.assets, use_gl=not args.no_gl)
            self.pages[dungeon] = page
            self.tabs.addTab(page, dungeon.replace("_", " "))
        # The tab of the dungeon the player is in has an arrow. Every other tab has the arrow's space, so that no
        # tab moves when the arrow does
        self.tabs.setIconSize(TAB_ARROW)
        self._tab_arrow, self._no_tab_arrow = tab_arrows(self.tabs.palette().color(QPalette.ColorRole.WindowText))
        self.highlight_dungeon(None)
        if self.settings["tab"] in self.pages:
            self.select_dungeon(self.settings["tab"])
        self.tabs.currentChanged.connect(self._tab_changed)
        self._build_menus()

    # -------------------------------------------------------------------- menus

    def _build_menus(self):
        bar = self.menuBar()
        file_menu = bar.addMenu("File")
        file_menu.addAction("New", self.new_map).setShortcut(QKeySequence.StandardKey.New)
        file_menu.addAction("Open Tracker Data", self._open).setShortcut(QKeySequence.StandardKey.Open)
        file_menu.addAction("Save Tracker Data", self.save_file).setShortcut(QKeySequence.StandardKey.Save)
        self.autosave_action = QAction("Autosave", self, checkable=True)
        self.autosave_action.setChecked(self.autosave_on)
        self.autosave_action.toggled.connect(self._set_autosave)
        file_menu.addAction(self.autosave_action)
        file_menu.addSeparator()
        file_menu.addAction("Stop Auto-tracking", self.stop_tracking)
        file_menu.addAction("Reconnect to SNI", self._reconnect)
        self.devices_menu = file_menu.addMenu("Devices")
        self.set_devices([])
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)

        view_menu = bar.addMenu("View")
        view_menu.addAction("Fit to window", self._fit)
        view_menu.addAction("Re-layout", self._relayout)
        experimental = bar.addMenu("Experimental")
        for menu, label, name in (
            (view_menu, "Show All Doors", "show_all_doors"),
            (view_menu, "Show Checks", "show_checks"),
            (view_menu, "Show FPS", "show_fps"),
            (experimental, "Hide Single Route Tiles", "hide_single_route_tiles"),
            (experimental, "Enable Decoupled Support", "decoupled_doors"),
            (experimental, "Drops Are Not Shuffled", "vanilla_drops"),
            (experimental, "Trim Rooms", "trim_rooms"),
            (experimental, "Split Partitioned Rooms", "split_rooms"),
        ):
            action = QAction(label, self, checkable=True)
            action.setChecked(self.settings[name])
            action.setObjectName(name)
            action.toggled.connect(self._option_toggled)
            menu.addAction(action)
        experimental.addSeparator()
        experimental.addAction("Cheat: Reveal All Tiles", self._reveal_all)
        help_menu = bar.addMenu("Help")
        help_menu.addAction("AI Disclosure", self._ai_disclosure)
        help_menu.addAction("Credits", self._credits)

    # What the menus and the toolbar call. Signals go to methods, never lambdas: Qt keeps a lambda that holds the
    # window alive, and the window with it after it has closed

    def _tab_changed(self) -> None:
        self.set_setting("tab", self.current_dungeon())

    @property
    def connected(self) -> bool:
        """The auto-tracker is reading from a device."""
        return self._connected

    @connected.setter
    def connected(self, connected: bool) -> None:
        self._connected = connected
        if not connected:
            self._game_seed = None  # the next game read need not be the same one

    def _open(self) -> None:
        self.load_file()

    def _ai_disclosure(self) -> None:
        QMessageBox.about(self, "AI Disclosure", AI_DISCLOSURE)

    def _credits(self) -> None:
        QMessageBox.about(self, "Credits", CREDITS)

    def _reconnect(self) -> None:
        self.start_tracking()

    def _fit(self) -> None:
        self.current_page().fit_view()

    def _relayout(self) -> None:
        self.current_page().relayout()

    def _reveal_all(self) -> None:
        """The cheat: every tab gets its dungeon from the seed's own map; see seed_map_wanted."""
        if not self.connected:
            QMessageBox.information(self, "Reveal All Tiles", "SNI connection required to cheat.")
            return
        answer = QMessageBox.question(
            self,
            "Reveal All Tiles",
            "This will spoil the dungeon layouts. Are you sure?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.cheat_wanted = True

    def _tabs_holding(self, option: str, items: Mapping[str, str]) -> set[str]:
        """The tabs whose dungeon's map, or compass, is held, if the option that has it reveal anything is on.

        items: MAPS or COMPASSES.
        """
        return {tab for tab, item in items.items() if item in self._held[0]} if self.settings[option] else set()

    def _rooms_for(self) -> list[GraphPage]:
        """The tabs to give their dungeon's rooms from the seed's own map: every tab for the cheat, and a tab
        whose dungeon's map is held, until it has them."""
        with_map = self._tabs_holding("map_reveals", MAPS)
        return [page for name, page in self.pages.items() if self.cheat_wanted or (name in with_map and not page.model.revealed)]

    def _bosses_for(self) -> list[GraphPage]:
        """The tabs to give their boss rooms' bosses from the seed's own map: every tab for the cheat, and a tab
        whose dungeon's compass is held, while it has a boss room that has not had its boss."""
        with_compass = self._tabs_holding("compass_reveals", COMPASSES)
        return [page for name, page in self.pages.items() if self.cheat_wanted or (name in with_compass and page.model.bosses_to_reveal())]

    @property
    def seed_map_wanted(self) -> bool:
        """Whether any of the seed's own map is still to be shown. The auto-tracker looks at each reading: it has
        the map from the game's ROM, and hands it to seed_map_read."""
        return bool(self._rooms_for() or self._bosses_for())

    def seed_map_read(self, seed: seed_map.SeedMap) -> None:
        """The seed's own map, from the auto-tracker, which saw it was wanted. It is used and not kept: the tracker
        has it for as long as it is reading that game. Nothing of it is wanted after."""
        rooms_for = self._rooms_for()
        if rooms_for:
            links = seed.links(self.settings["decoupled_doors"])
            for page in rooms_for:
                page.show_seed(links, {name: door for name, door in seed.entrances.items() if name in dungeon_lobbies[page.tab_world]})
        # After the rooms, which may have put a boss room on the map
        for page in self._bosses_for():
            page.reveal_bosses(seed.bosses)
        self.cheat_wanted = False

    def _option_toggled(self, checked: bool) -> None:
        """A menu option or a toolbar box, named after its setting, was toggled."""
        self.set_option(self.sender().objectName(), checked)

    def _slider_moved(self, value: int) -> None:
        name = self.sender().objectName()
        self.set_option(name, value / self._slider_steps[name])

    def _device_picked(self) -> None:
        self.start_tracking(device=self.sender().objectName())

    def _force_tracking(self) -> None:
        self.start_tracking(forced=True, device=self.device)

    def _build_toolbar(self) -> QWidget:
        toolbar = QWidget()
        row = QHBoxLayout(toolbar)
        row.setContentsMargins(6, 3, 6, 3)

        self.boxes: dict[str, QCheckBox] = {}  # by setting

        def add_box(name: str, label: str, tip: str = "") -> None:
            box = QCheckBox(label)
            box.setToolTip(tip)
            box.setChecked(self.settings[name])
            box.setObjectName(name)
            box.toggled.connect(self._option_toggled)
            row.addWidget(box)
            self.boxes[name] = box

        self.sliders: dict[str, QSlider] = {}  # by setting
        self._slider_steps: dict[str, int] = {}  # slider steps per unit of its setting

        def add_slider(name: str, label: str, low: int, high: int, width: int, steps_per_unit: int) -> None:
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(low, high)
            # A saved value outside the range is brought into it
            slider.setValue(round(min(max(self.settings[name] * steps_per_unit, low), high)))
            self.settings[name] = slider.value() / steps_per_unit
            slider.setFixedWidth(width)
            slider.setObjectName(name)
            self._slider_steps[name] = steps_per_unit
            slider.valueChanged.connect(self._slider_moved)
            row.addWidget(QLabel(label))
            row.addWidget(slider)
            self.sliders[name] = slider

        add_box("auto_join", "Join fitting rooms")
        add_slider("spacing", "Spacing", 10, 200, 120, 1)
        add_slider("dead_end_pull", "Dead-end pull", 10, 40, 80, 10)
        add_box("circle_repulsion", "Circle repulsion", "Experiment: each block repels as one circle around all its rooms")
        add_box(
            "show_repulsion",
            "Show repulsion",
            "Draw what pushes blocks apart. Two blocks push when the same kind of outline overlaps.\n"
            "Solid: the push between rooms, which reaches as far as the Spacing slider says.\n"
            "With Circle repulsion the dashed circles carry the slider's reach, and the rooms only push at close range.\n"
            "Hatched: a pinned block, which pushes but is not moved.",
        )
        add_box("simulate", "Simulate")
        add_box("follow_player", "Follow player")
        add_box("labels", "Labels")
        add_box("map_reveals", "Map reveals rooms", "Once a dungeon's map is held, its tab gets its rooms, links and entrances from the game")
        add_box("compass_reveals", "Compass reveals bosses", "Once a dungeon's compass is held, each boss room on its tab shows its boss")
        # Named as the randomizer names the settings they are for
        add_box("pottery", "Pottery", "For a seed with Pottery set to Dungeon Pots or Lottery: each room counts down its pots not yet emptied")
        add_box("enemy_drops", "Enemy Drops", "For a seed with Enemy Drops set to Underworld Enemies: each room counts down its enemies' drops not yet taken")
        self.status = QLabel("")  # what the mouse is over
        self.status.setMinimumWidth(50)
        row.addWidget(self.status, 1)
        # View -> Show FPS: frames the tab in view drew in the last second, and how long the last one took
        self.fps_label = QLabel("")
        self.fps_label.setMinimumWidth(self.fps_label.fontMetrics().horizontalAdvance("000 fps  00.0 ms") + 8)
        self.fps_label.setVisible(self.settings["show_fps"])
        row.addWidget(self.fps_label)
        return toolbar

    def set_setting(self, name: str, value: Any) -> None:
        """Change a setting and keep it for the next launch."""
        self.settings[name] = value
        if self.settings_file is not None:
            try:
                files.write_text(self.settings_file, yaml.dump(self.settings))
            except OSError as error:
                traceback.print_exc()
                # Said once: no more writes are tried this run
                file, self.settings_file = self.settings_file, None
                QMessageBox.warning(
                    self, "Settings not saved", f"{file}\n\n{error!r}\n\nSettings changed from now on are not kept."
                )

    def set_option(self, name: str, value: bool | float) -> None:
        """Change a setting the pages act on, in every tab."""
        self.set_setting(name, value)
        if name == "show_fps":
            self.fps_label.setVisible(bool(value))
        for page in self.pages.values():
            page.option_changed(name)
        if name in COUNTED.values():
            for page in self.pages.values():
                page.scene.update()

    def current_page(self) -> GraphPage:
        return list(self.pages.values())[self.tabs.currentIndex()]

    def current_dungeon(self) -> str:
        return self.current_page().dungeon_name

    # -------------------------------------------------------------------- files

    def load_file(self, file: str | None = None) -> None:
        if file is None:
            file, _ = QFileDialog.getOpenFileName(self, "Open Tracker Data", ".", "Yaml Files (*.yaml *.yml);;All Files (*)")
        if not file:
            return
        with open(file, mode="r") as fh:
            try:
                data: dict[str, Any] = yaml.safe_load(fh)
            except Exception:
                from SpoilerToYaml import parse_dr_spoiler

                data = parse_dr_spoiler(fh)
        seed = data.get("seed_hash")
        if seed is not None and self._game_seed is not None and seed != self._game_seed:
            # Left to the tracker, the map would be put away again at the next reading, for the game's own
            answer = self._ask(
                "Different seed",
                "This map is for a different seed from the game being tracked.\n\n"
                "Disconnecting opens it and stops auto-tracking. File -> Reconnect to SNI starts tracking again, "
                "and brings back the game's own map.",
                DISCONNECT,
                CANCEL,
            )
            if answer != DISCONNECT:
                return
            self.stop_tracking()
        if self._save_timer.isActive():
            # The map on screen is about to be replaced: its last changes go to its autosave first
            self._write_autosave()
        self.load_data(data)

    def load_data(self, data: dict[str, Any]) -> None:
        """Show the map a tracker file holds."""
        if "Agahnims_Tower" in data:
            data["Castle_Tower"] = data.pop("Agahnims_Tower")
        # All of these are read before any is kept: one that cannot be leaves the window as it was
        seed_hash = data.pop("seed_hash", None)
        collected = set(data.pop("collected", None) or [])
        # A file from before these were saved has neither
        items, keys = data.pop("items", None), data.pop("small_keys", None)
        held = NOTHING_HELD if items is None else (frozenset(items), dict(keys or {}))
        self.seed_hash, self.collected = seed_hash, collected
        self._forget_game(held)
        self._adopt_seed = False
        # A spoiler lists lobbies apart from the dungeons: file each under the dungeon that owns it
        for lobby, door in (data.pop("lobbies", None) or {}).items():
            if not isinstance(door, str):
                continue  # the parser's entry also has its empty default fields
            if door not in rooms.DOORS:
                door = door.rsplit(" (", 1)[0]
            dungeon = next((d for d, world in dungeon_worlds.items() if lobby in dungeon_lobbies.get(world, ())), None)
            if dungeon is None or door not in rooms.DOORS:
                print(f"Spoiler lobby not recognised: {lobby}: {door}")
                continue
            data[dungeon].setdefault("lobby_doors", []).append({"door": door, "lobby": lobby})
            data[dungeon].setdefault("special_doors", {})[door] = lobby
        for dungeon, dungeon_data in data.items():
            if dungeon in self.pages:
                self.pages[dungeon].load_yaml(dungeon_data)

    def save_file(self) -> None:
        file, _ = QFileDialog.getSaveFileName(self, "Save Tracker Data", ".", "Yaml Files (*.yaml *.yml);;All Files (*)")
        if not file:
            return
        if not file.endswith((".yaml", ".yml")):
            file += ".yaml"
        try:
            files.write_text(Path(file), yaml.dump(self.tracker_data()))
        except OSError as error:
            traceback.print_exc()
            QMessageBox.warning(self, "Tracker data not saved", f"{file}\n\n{error!r}")

    def tracker_data(self) -> dict[str, Any]:
        """Everything a tracker file holds."""
        data: dict[str, Any] = {dungeon: page.return_connections() for dungeon, page in self.pages.items()}
        if self.seed_hash is not None:
            data["seed_hash"] = self.seed_hash
        data["collected"] = sorted(self.collected)
        items, keys = self._held
        data["items"], data["small_keys"] = sorted(items), dict(keys)
        return data

    # ----------------------------------------------------------------- autosave

    def start_autosave(self, folder: Path, restore: bool) -> None:
        """Keep the map in this folder from here on. restore: first load the map the last run left there.

        Nothing is saved before this is called, so a new window cannot save its empty map over a file.
        """
        latest = folder / LATEST
        if restore and self.autosave_on and latest.exists():
            try:
                self._latest = latest.read_text().strip()
            except (OSError, ValueError) as error:  # not readable, or not text
                self._stop_autosave(
                    "Autosave not loaded",
                    f"{latest}\n\n{error!r}\n\nThe saved maps have been left as they are, and File -> Autosave has "
                    "been turned off.",
                )
            else:
                self._load_autosave(folder / self._latest)
        self.autosave = folder
        if not restore:
            self.map_changed()

    def _load_autosave(self, file: Path) -> bool:
        """Show the map an autosave holds. False if it could not be read: the file is then left alone."""
        try:
            self.load_data(read_autosave(file))
        except Exception as error:
            # Saving now would overwrite the file that failed to load
            self._stop_autosave(
                "Autosave not loaded",
                f"{file}\n\n{error!r}\n\nThe file has been left as it is, and File -> Autosave has been turned off. "
                "Turning it on again will save over the file.",
            )
            return False
        return True

    def _stop_autosave(self, title: str, text: str) -> None:
        """Turn autosave off after a failure, and say why. For this run only: the setting is kept."""
        traceback.print_exc()
        self.autosave_on = False
        self._save_timer.stop()
        self._drift_timer.stop()
        self.autosave_action.blockSignals(True)
        self.autosave_action.setChecked(False)
        self.autosave_action.blockSignals(False)
        QMessageBox.warning(self, title, text)

    def _set_autosave(self, checked: bool) -> None:
        self.autosave_on = checked
        self.set_setting("autosave", checked)
        if checked:
            self.map_changed()
        else:
            self._save_timer.stop()
            self._drift_timer.stop()

    def map_changed(self) -> None:
        """A page's saved state changed. The map is saved once the changes stop."""
        if self.autosave is not None and self.autosave_on:
            self._save_timer.start(SAVE_DELAY)

    def _save_after_change(self) -> None:
        self._write_autosave()
        if self.settings["simulate"]:
            self._drift_timer.start(DRIFT_SAVE_DELAY)

    def _write_autosave(self) -> bool:
        """Save the map to its seed's file. False if it was not saved: autosave is off, or the write failed."""
        if self.autosave is None or not self.autosave_on:
            return False
        name = autosave_name(self.seed_hash)
        try:
            # The end marker shows the file is whole when it is read back
            files.write_text(self.autosave / name, yaml.dump(self.tracker_data(), explicit_end=True))
            if name != self._latest:
                files.write_text(self.autosave / LATEST, name)
                self._latest = name
        except OSError as error:
            self._stop_autosave(
                "Autosave failed",
                f"{self.autosave / name}\n\n{error!r}\n\nFile -> Autosave has been turned off. Turn it on again to retry.",
            )
            return False
        return True

    def seed_seen(self, seed_hash: str) -> bool:
        """The auto-tracker is in a game with this hash. Each seed has its own autosave: a new seed swaps maps.

        Returns False if the user chose to disconnect and leave the map as it is: tracking must stop.

        The map on screen is only given another seed's hash once it has been swapped for that seed's map, or
        the user has said what to do with it. Otherwise one seed's map could be saved over another's.
        """
        self._game_seed = seed_hash
        if seed_hash == self.seed_hash:
            return True
        saved = self.autosave / autosave_name(seed_hash) if self.autosave is not None and self.autosave_on else None
        if self.seed_hash is None:
            adopt, self._adopt_seed = self._adopt_seed, False
            # The map on screen has not been seen in a game. It is this seed's, unless this seed has a map already
            if saved is not None and saved.exists() and not adopt:
                answer = self._ask(
                    "Saved map found",
                    "This seed already has a saved map.\n\nKeeping the map on screen will save it over that one.\n"
                    "Disconnecting leaves both maps as they are.",
                    USE_SAVED,
                    KEEP_MAP,
                    DISCONNECT,
                )
                if answer == DISCONNECT:
                    return False
                if answer == USE_SAVED:
                    self._swap_to(saved)
        elif not self._swap_to(saved):
            answer = self._ask(
                "Different seed",
                "The game is a different seed from this map, and the map could not be put away in its autosave.\n\n"
                "Keeping it will add the new seed's rooms to it.\nDisconnecting leaves it as it is.",
                NEW_MAP,
                KEEP_MAP,
                DISCONNECT,
            )
            if answer == DISCONNECT:
                return False
            if answer == NEW_MAP:
                self._clear_map()
            else:
                self._forget_game()  # the map is kept, for another game
        self.seed_hash = seed_hash
        self.map_changed()
        return True

    def _swap_to(self, saved: Path | None) -> bool:
        """Put the map on screen away in its autosave and show the saved one, or an empty map if there is none.

        saved: the autosave to show, or None if autosave is off. False if the map on screen could not be put
        away: it is then left on screen.
        """
        if saved is None or not self._write_autosave():
            return False
        if not (saved.exists() and self._load_autosave(saved)):
            self._clear_map()
        return True

    def _ask(self, title: str, text: str, *answers: str, warning: bool = False) -> str:
        """Ask a question with named answers; returns the one picked. Closing the dialog picks the last.

        warning: the text is html, and the last answer is the default.
        """
        box = QMessageBox(QMessageBox.Icon.Warning if warning else QMessageBox.Icon.Question, title, text, parent=self)
        buttons = {box.addButton(answer, QMessageBox.ButtonRole.ActionRole): answer for answer in answers}
        last = list(buttons)[-1]
        box.setEscapeButton(last)
        if warning:
            box.setTextFormat(Qt.TextFormat.RichText)
            box.setDefaultButton(last)
        box.exec()
        return buttons.get(box.clickedButton(), answers[-1])

    def _clear_map(self) -> None:
        self.collected = set()
        for page in self.pages.values():
            page.init_page()
        self._forget_game()

    def _forget_game(self, held: tuple[frozenset[str], dict[str, int]] = NOTHING_HELD) -> None:
        """The map on screen is another one now, or another game's. What was read from the game before, and what
        was asked of it, is not for this one.

        held: the items and small keys the map now on screen was saved with.
        """
        self.cheat_wanted = False
        if self._held != held:
            self._show_held(*held)

    def player_sprite_read(self, heads: list[bytes]) -> None:
        """The player's head in each mail's colours, as the auto-tracker read it from the game's ROM: see
        link_sprite.decode. It is kept until another is read: it is the game's, not the map's."""
        size = link_sprite.SIZE
        # A sprite can have nothing for a head, where it is drawn all in its body: the player stays a cross
        solid = any(heads[0][3::4])
        self._player_heads = [QPixmap.fromImage(QImage(head, size, size, QImage.Format.Format_RGBA8888)) for head in heads] if solid else []
        for page in self.pages.values():
            page.scene.update()

    def player_head(self) -> QPixmap | None:
        """The picture to draw the player with, in the mail they wear. None for a cross."""
        if not self._player_heads:
            return None
        items = self._held[0]
        return self._player_heads[2 if "Red Mail" in items else 1 if "Blue Mail" in items else 0]

    def checks_read(self, memory: Mapping[str, bytes]) -> None:
        """The game's tables of what has been collected and the items held, as the auto-tracker just read them."""

        def word(table: str, room: int) -> int:
            return int.from_bytes(memory[table][room * 2 : room * 2 + 2], "little")

        collected = {name for name, check in checks.items() if any(word(table, room) & mask for table, room, mask in check["flags"])}
        # A pot emptied or an enemy's drop taken is collected like any check
        collected |= {drop.name for drops in DROPS.values() for drop in drops if word(drop.kind, drop.room) & drop.mask}
        if collected != self.collected:
            # This also puts back any check clicked on the map that the game does not agree with
            self._set_collected(collected)
        held = items_held(memory["items"]), small_keys(memory["items"], memory["dungeon"][0])
        if held != self._held:
            # This also puts back anything clicked in the items panel that the game does not agree with
            self.set_held(*held)

    def drops_left(self, tile: rooms.Tile) -> list[Drop]:
        """The pots, and the enemies, of a supertile still to be had, of the kinds the toolbar says this seed makes
        checks of.

        Which ones a seed made checks of is not read from the game: that would say where they are. So this is
        right for a seed where every dungeon pot is a check, or every enemy.
        """
        counted = {kind for kind, option in COUNTED.items() if self.settings[option]}
        return [drop for drop in DROPS.get(tile, ()) if drop.kind in counted and drop.name not in self.collected]

    def set_collected(self, check: str, collected: bool) -> None:
        """A check was clicked on the map to collect it, or right clicked to take that back."""
        if (check in self.collected) != collected:
            self._set_collected(self.collected ^ {check})

    def _set_collected(self, collected: set[str]) -> None:
        self.collected = collected
        for page in self.pages.values():
            page.scene.update()
        self.map_changed()

    def set_held(self, items: frozenset[str], small_keys: dict[str, int]) -> None:
        """What the player holds: as read from the game, or as clicked in the items panel. It is saved with the map."""
        self._show_held(items, small_keys)
        self.map_changed()

    def _show_held(self, items: frozenset[str], small_keys: dict[str, int]) -> None:
        self._held = items, small_keys
        for page in self.pages.values():
            page.set_items(items, small_keys)

    def new_map(self) -> None:
        """File -> New: an empty map that belongs to no seed."""
        if self.connected:
            answer = self._ask(
                "Connected to a game",
                "<h1>YOU ARE CONNECTED TO A GAME</h1>"
                "<p style='font-size: 13pt'>The new map will be attached to that game's seed as soon as the tracker "
                "next reads it, and will <b>REPLACE THE MAP SAVED FOR THAT SEED</b>.</p>"
                "<p style='font-size: 13pt'>That map cannot be brought back.</p>",
                NEW_MAP,
                CANCEL,
                warning=True,
            )
            if answer != NEW_MAP:
                return
            # Chosen knowing that: the new map takes the game's seed without a second question
            self._adopt_seed = True
        elif not all(page.model.untouched() for page in self.pages.values()):
            # Not connected. A map with a seed stays in that seed's autosave; any other has nowhere to go
            kept = self.seed_hash is not None and self.autosave is not None and self.autosave_on
            if not kept:
                answer = self._ask(
                    "Start a new map?",
                    "<p>The map on screen will be discarded.</p><p>"
                    + (
                        "It belongs to no seed, so the new map takes its place in the autosave."
                        if self.seed_hash is None
                        else "Autosave is off, so it is not saved anywhere."
                    )
                    + "</p>",
                    NEW_MAP,
                    CANCEL,
                    warning=True,
                )
                if answer != NEW_MAP:
                    return
        if self._save_timer.isActive():
            # The map on screen goes to its own autosave first
            self._write_autosave()
        self._clear_map()
        self.seed_hash = None
        self.map_changed()

    # ------------------------------------------------------------------ pickers

    def pick_icon(self, world: World, taken: Container[str]) -> str | None:
        """taken: the entrances the map already has."""
        dialog = IconPicker(self, self.assets, world, taken)
        return dialog.choice if dialog.exec() else None

    def pick_boss(self) -> str | None:
        dialog = BossPicker(self, self.assets)
        return dialog.choice if dialog.exec() else None

    def pick_enemy(self) -> str | None:
        dialog = EnemyPicker(self, self.assets)
        return dialog.choice if dialog.exec() else None

    def pick_eg_tile(self, page: GraphPage) -> rooms.Tile | None:
        used: dict[rooms.Tile, int] = {}
        for other in self.pages.values():
            for tile in other.model.tiles:
                used[tile] = used.get(tile, 0) + 1
        unavailable = {tile for tile, count in used.items() if count >= eg_tile_multiuse.get(tile, 1)}
        unavailable |= set(page.model.tiles)
        dialog = EgPicker(self, self.assets, unavailable)
        return dialog.choice if dialog.exec() else None

    # ------------------------------------------------------- called by the tracker

    def set_title(self, text: str) -> None:
        self.setWindowTitle(text)

    def set_devices(self, uris: list[str]) -> None:
        self.devices_menu.clear()
        if not uris:
            self.devices_menu.addAction("No Devices...").setEnabled(False)
        for uri in uris:
            action = self.devices_menu.addAction(uri)
            action.setObjectName(uri)
            action.triggered.connect(self._device_picked)

    def race_rom_warning(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Warning - Race Rom Detected")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(
            "A Race Rom has been detected, auto-tracking has been automatically disabled.\n\n"
            "When auto-tracking is enabled, this tracker does not abide by the current auto-tracking rules set by "
            "the racing council.\nYou can continue to use this tracker, but you will need to manually track layouts.\n\n"
            "If you would like to continue using auto-tracking, you can force it to be enabled by clicking the "
            "button below."
        )
        box.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
        force = box.addButton("Force Auto-Tracking", QMessageBox.ButtonRole.DestructiveRole)
        box.exec()
        if box.clickedButton() is force:
            # Deferred: this runs inside the task being restarted
            QTimer.singleShot(0, self._force_tracking)

    def highlight_dungeon(self, name: str | None) -> None:
        for dungeon, page in self.pages.items():
            self.tabs.setTabIcon(self.tabs.indexOf(page), self._tab_arrow if dungeon == name else self._no_tab_arrow)

    def select_dungeon(self, name: str) -> None:
        self.tabs.setCurrentWidget(self.pages[name])

    # ---------------------------------------------------------------------- SNI

    def start_tracking(self, forced: bool = False, device: str | None = None) -> None:
        from sni_tracker import sni_probe

        self.stop_tracking()
        if self.loop is None:
            self.loop = asyncio.new_event_loop()
            self._pump = QTimer(self)
            self._pump.setInterval(10)
            self._pump.timeout.connect(self._pump_asyncio)
            self._pump.start()
        self.sni_task = self.loop.create_task(sni_probe(self, self.args, forced_autotrack=forced, device=device))

    def stop_tracking(self) -> None:
        if self.sni_task is not None:
            self.sni_task.cancel()
            self.sni_task = None
            self.connected = False
            self.setWindowTitle(f"{TITLE} - Auto-tracking disabled")

    def _pump_asyncio(self):
        """Run pending asyncio callbacks once, from the Qt timer."""
        loop = self.loop
        # Already running while a dialog opened from the tracker is up: the dialog's event loop fires this timer too
        if loop is None or loop.is_running():
            return
        loop.call_soon(loop.stop)
        loop.run_forever()
        if self.sni_task is not None and self.sni_task.done() and not self.sni_task.cancelled():
            error = self.sni_task.exception()
            self.sni_task = None
            if error is not None:
                print(f"Auto-tracking stopped: {error!r}")
                self.setWindowTitle(f"{TITLE} - Auto-tracking stopped (is SNI running?)")

    def closeEvent(self, event):
        if self.sni_task is not None:
            self.sni_task.cancel()
        self._save_timer.stop()
        self._drift_timer.stop()
        self._write_autosave()
        self.set_setting("window", bytes(self.saveGeometry().toHex().data()).decode())
        super().closeEvent(event)


def install_interrupt_handler(app, window):
    """Close the window on Ctrl+C.

    Python signal handlers only run when the interpreter does, so a no-op timer wakes it while Qt's
    event loop is running.
    """
    signal.signal(signal.SIGINT, lambda signum, frame: window.close())
    wake = QTimer(app)
    wake.timeout.connect(lambda: None)
    wake.start(150)
    app._interrupt_wake = wake


def main():
    parser = argparse.ArgumentParser(description="Auto-tracker for dungeon layouts in the ALttP door randomizer")
    parser.add_argument("tracker_file", nargs="?", default=None, help="Tracker data (yaml) or spoiler to load on startup")
    parser.add_argument("--size", choices=list(WINDOW_SIZES), default=None, help="Set the window size, instead of the size it last had")
    parser.add_argument("--port", type=int, default=8191, help="SNI connection port")
    parser.add_argument("--debug", action="store_true", default=False, help="Enable debug logging")
    parser.add_argument(
        "--no-autotrack",
        action="store_true",
        default=False,
        help="Don't automatically track doors (No SNI connection - Race Legal)",
    )
    parser.add_argument("--no-gl", action="store_true", default=False, help="Draw without OpenGL")
    args, qt_args = parser.parse_known_args()

    app = QApplication([sys.argv[0]] + qt_args)
    # Names the per-user folder
    app.setApplicationName("JankerDoorTracker")
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "data" / "JankerTracker.ico")))
    folder = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation))
    folder.mkdir(parents=True, exist_ok=True)
    window = MainWindow(args, settings_file=folder / "settings.yaml")
    window.show()
    install_interrupt_handler(app, window)
    if args.tracker_file:
        window.load_file(args.tracker_file)
    window.start_autosave(folder, restore=not args.tracker_file)
    if not args.no_autotrack:
        window.start_tracking()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
