"""Generate data/JankerTracker.ico from data/maps/egmap.png: a shutter door in Hyrule Castle's dungeon.

    uv run tools/make_icon.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from gui.Doors.rooms import DOORS  # noqa: E402

DOOR = "Hyrule Dungeon Armory S"
MIDDLE = (1, 9)  # of the door's picture, from where the door is walked through
SIDE = 32
SIZES = [16, 24, 32, 48, 64, 128, 256]


def main():
    door = DOORS[DOOR]
    x = door.tile[0] * 512 + round(door.x * 512) + MIDDLE[0]
    y = door.tile[1] * 512 + round(door.y * 512) + MIDDLE[1]
    half = SIDE // 2
    square = Image.open(ROOT / "data" / "maps" / "egmap.png").convert("RGBA").crop((x - half, y - half, x + half, y + half))
    # Enlarged with its pixels kept square. The sizes that are not a multiple of it are smoothed down from this
    large = square.resize((SIZES[-1], SIZES[-1]), Image.Resampling.NEAREST)
    large.save(ROOT / "data" / "JankerTracker.ico", sizes=[(size, size) for size in SIZES])


if __name__ == "__main__":
    main()
