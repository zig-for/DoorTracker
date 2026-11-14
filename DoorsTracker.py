"""Janker Door Tracker: auto-tracks ALttP door randomizer dungeon layouts through SNI. Qt entry point."""

import argparse
import asyncio
import signal
import sys
import traceback
from pathlib import Path
from typing import Any

import yaml
from PIL import Image
from PySide6.QtCore import QByteArray, QSize, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QGridLayout,
    QMainWindow,
    QMessageBox,
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
from gui.Doors import rooms
from gui.qt.graph_page import Assets, GraphPage

WINDOW_SIZES = {"small": (1064, 632), "medium": (1588, 888), "large": (2088, 1144)}
TITLE = "Janker Door Tracker"
# The map is autosaved this long after its last change, in ms
SAVE_DELAY = 1000
# and once more this long after that if Simulate is on, as the cards keep moving
DRIFT_SAVE_DELAY = 10_000
# Holds the name of the autosave written last
LATEST = "latest.txt"
# What is kept between launches, and its value on a first launch. A saved setting not listed here is ignored
DEFAULT_SETTINGS: dict[str, Any] = {
    "autosave": True,
    "tab": None,  # dungeon of the selected tab
    "window": None,  # QWidget.saveGeometry(), as hex
    # View and Experimental menus
    "show_all_doors": False,
    "hide_single_route_tiles": False,
    "decoupled_doors": False,
    "vanilla_drops": True,
    "trim_rooms": True,
    "split_rooms": True,
    # Toolbar
    "group_by_dungeon": False,
    "auto_join": True,
    "circle_repulsion": False,
    "show_repulsion": False,
    "simulate": False,
    "follow_player": False,
    "labels": True,
}


def autosave_name(seed_hash: str | None) -> str:
    """Each seed's map has its own file. A map not yet seen in a game has no seed."""
    return f"autosave-{seed_hash}.yaml" if seed_hash else "autosave.yaml"


class IconPicker(QDialog):
    """The annotation and lobby icons, laid out as they are on the icon sheet."""

    def __init__(self, parent, assets, world):
        super().__init__(parent)
        self.setWindowTitle("Annotate door")
        self.choice = None
        grid = QGridLayout(self)
        grid.setSpacing(2)
        for name, (row, column) in sprites.all_icons.items():
            button = QToolButton()
            button.setIcon(QIcon(assets.icon(name).scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)))
            button.setIconSize(QSize(32, 32))
            button.setToolTip(name.replace("_", " "))
            usable = (name in sprites.item_table or name in sprites.dungeon_lobbies[world]) and name != "Sanctuary_Mirror"
            button.setEnabled(usable)
            button.clicked.connect(lambda checked=False, name=name: self._pick(name))
            grid.addWidget(button, row, column)

    def _pick(self, name):
        self.choice = name
        self.accept()


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
        button.clicked.connect(lambda checked=False: self._pick(tile))
        self.buttons[tile] = button
        return button

    def _pick(self, tile):
        self.choice = tile
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
            saved = yaml.safe_load(settings_file.read_text())
            self.settings.update({name: value for name, value in saved.items() if name in DEFAULT_SETTINGS})
        self.autosave: Path | None = None  # folder; see start_autosave
        self._latest: str | None = None  # autosave file the next launch loads, as LATEST says
        self.autosave_on: bool = self.settings["autosave"]  # File -> Autosave, for this run
        self.seed_hash: str | None = None  # of the game the map was made on, once known; kept in the tracker file
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_after_change)
        self._drift_timer = QTimer(self)
        self._drift_timer.setSingleShot(True)
        self._drift_timer.timeout.connect(self._write_autosave)
        self.setWindowTitle(TITLE)
        if args.size is None and self.settings["window"]:
            self.restoreGeometry(QByteArray.fromHex(self.settings["window"].encode()))
        else:
            self.resize(*WINDOW_SIZES[args.size or "medium"])
        self.device: str | None = None
        self.sni_task: asyncio.Task | None = None
        self.loop: asyncio.AbstractEventLoop | None = None

        eg_map = Path(__file__).parent / "data" / "maps" / "egmap.png"
        self.assets = Assets(Image.open(eg_map))

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.pages: dict[str, GraphPage] = {}  # by dungeon, in tab order
        for dungeon, world in dungeon_worlds.items():
            if dungeon in ("Overworld", "Underworld"):
                continue
            page = GraphPage(self, world, self.assets, use_gl=not args.no_gl)
            self.pages[dungeon] = page
            self.tabs.addTab(page, dungeon.replace("_", " "))
        if self.settings["tab"] in self.pages:
            self.select_dungeon(self.settings["tab"])
        self.tabs.currentChanged.connect(lambda: self.set_setting("tab", self.current_dungeon()))
        self._build_menus()

    # -------------------------------------------------------------------- menus

    def _build_menus(self):
        bar = self.menuBar()
        file_menu = bar.addMenu("File")
        file_menu.addAction("Load Tracker Data", lambda: self.load_file())
        file_menu.addAction("Save Tracker Data", self.save_file)
        self.autosave_action = QAction("Autosave", self, checkable=True)
        self.autosave_action.setChecked(self.autosave_on)
        self.autosave_action.toggled.connect(self._set_autosave)
        file_menu.addAction(self.autosave_action)
        file_menu.addSeparator()
        file_menu.addAction("Stop Auto-tracking", self.stop_tracking)
        file_menu.addAction("Reconnect to SNI", lambda: self.start_tracking())
        self.devices_menu = file_menu.addMenu("Devices")
        self.set_devices([])
        file_menu.addSeparator()
        file_menu.addAction("Reset Tracker", self.reset_tracker)
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)

        view_menu = bar.addMenu("View")
        view_menu.addAction("Fit to window", lambda: self.current_page().fit_view())
        view_menu.addAction("Re-layout", lambda: self.current_page().relayout())
        experimental = bar.addMenu("Experimental")
        for menu, label, name in (
            (view_menu, "Show All Doors", "show_all_doors"),
            (experimental, "Hide Single Route Tiles", "hide_single_route_tiles"),
            (experimental, "Enable Decoupled Support", "decoupled_doors"),
            (experimental, "Drops Are Not Shuffled", "vanilla_drops"),
            (experimental, "Trim Rooms", "trim_rooms"),
            (experimental, "Split Partitioned Rooms", "split_rooms"),
        ):
            action = QAction(label, self, checkable=True)
            action.setChecked(self.settings[name])
            action.toggled.connect(lambda checked, name=name: self.set_option(name, checked))
            menu.addAction(action)

    def set_setting(self, name: str, value: Any) -> None:
        """Change a setting and keep it for the next launch."""
        self.settings[name] = value
        if self.settings_file is not None:
            files.write_text(self.settings_file, yaml.dump(self.settings))

    def set_option(self, name: str, value: bool) -> None:
        """Change a setting the pages act on, in every tab."""
        self.set_setting(name, value)
        for page in self.pages.values():
            page.option_changed(name)

    def current_page(self) -> GraphPage:
        return list(self.pages.values())[self.tabs.currentIndex()]

    def current_dungeon(self) -> str:
        return self.current_page().dungeon_name

    # -------------------------------------------------------------------- files

    def load_file(self, file: str | None = None) -> None:
        if file is None:
            file, _ = QFileDialog.getOpenFileName(self, "Load Tracker Data", ".", "Yaml Files (*.yaml *.yml);;All Files (*)")
        if not file:
            return
        with open(file, mode="r") as fh:
            try:
                data: dict[str, Any] = yaml.safe_load(fh)
            except Exception:
                from SpoilerToYaml import parse_dr_spoiler

                data = parse_dr_spoiler(fh)
        if "Agahnims_Tower" in data:
            data["Castle_Tower"] = data.pop("Agahnims_Tower")
        self.seed_hash = data.pop("seed_hash", None)
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
        files.write_text(Path(file), yaml.dump(self.tracker_data()))

    def tracker_data(self) -> dict[str, Any]:
        """Everything a tracker file holds."""
        data: dict[str, Any] = {dungeon: page.return_connections() for dungeon, page in self.pages.items()}
        if self.seed_hash is not None:
            data["seed_hash"] = self.seed_hash
        return data

    # ----------------------------------------------------------------- autosave

    def start_autosave(self, folder: Path, restore: bool) -> None:
        """Keep the map in this folder from here on. restore: first load the map the last run left there.

        Nothing is saved before this is called, so a new window cannot save its empty map over a file.
        """
        latest = folder / LATEST
        if restore and self.autosave_on and latest.exists():
            self._latest = latest.read_text()
            file = folder / self._latest
            try:
                self.load_file(str(file))
            except Exception as error:
                traceback.print_exc()
                # Saving now would overwrite the file that failed to load. Off for this run only
                self.autosave_on = False
                self.autosave_action.blockSignals(True)
                self.autosave_action.setChecked(False)
                self.autosave_action.blockSignals(False)
                QMessageBox.warning(
                    self,
                    "Autosave not loaded",
                    f"{file}\n\n{error!r}\n\nThe file has been left as it is, and File -> Autosave has been "
                    "turned off. Turning it on again will save over the file.",
                )
        self.autosave = folder
        if not restore:
            self.map_changed()

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

    def _write_autosave(self) -> None:
        if self.autosave is None or not self.autosave_on:
            return
        name = autosave_name(self.seed_hash)
        files.write_text(self.autosave / name, yaml.dump(self.tracker_data()))
        if name != self._latest:
            files.write_text(self.autosave / LATEST, name)
            self._latest = name

    def seed_seen(self, seed_hash: str) -> None:
        """The auto-tracker is in a game with this hash. Each seed has its own autosave: a new seed swaps maps."""
        if seed_hash == self.seed_hash:
            return
        if self.seed_hash is not None and self.autosave is not None and self.autosave_on:
            # The map on screen is another seed's: put it away and bring out this one's
            self._write_autosave()
            file = self.autosave / autosave_name(seed_hash)
            if file.exists():
                self.load_file(str(file))
            else:
                for page in self.pages.values():
                    page.init_page()
        self.seed_hash = seed_hash
        self.map_changed()

    def reset_tracker(self):
        answer = QMessageBox.question(
            self,
            "Reset?",
            "This will reset your tracker, losing all connections etc.\nAre you sure you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            for page in self.pages.values():
                page.init_page()

    # ------------------------------------------------------------------ pickers

    def pick_icon(self, world: World) -> str | None:
        dialog = IconPicker(self, self.assets, world)
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
            self.devices_menu.addAction(uri, lambda uri=uri: self.start_tracking(device=uri))

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
            QTimer.singleShot(0, lambda: self.start_tracking(forced=True, device=self.device))

    def highlight_dungeon(self, name: str | None) -> None:
        for dungeon, page in self.pages.items():
            label = dungeon.replace("_", " ")
            self.tabs.setTabText(self.tabs.indexOf(page), f"▶ {label}" if dungeon == name else label)

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
            self.setWindowTitle(f"{TITLE} - Auto-tracking disabled")

    def _pump_asyncio(self):
        """Run pending asyncio callbacks once, from the Qt timer."""
        loop = self.loop
        if loop is None:
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
