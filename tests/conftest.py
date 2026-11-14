import argparse
import os

import pytest

# No windows on screen while testing; must be set before Qt starts
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def open_window(app):
    """Opens the tracker's main window, not connected to SNI. It keeps no files unless given a settings file."""
    import DoorsTracker

    opened = []

    def open_window(settings_file=None, size="medium"):
        args = argparse.Namespace(tracker_file=None, size=size, port=8191, debug=False, no_autotrack=True, no_gl=True)
        window = DoorsTracker.MainWindow(args, settings_file)
        window.show()
        app.processEvents()
        opened.append(window)
        return window

    yield open_window
    for window in opened:
        window.close()


@pytest.fixture
def window(open_window):
    return open_window()
