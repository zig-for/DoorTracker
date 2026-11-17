"""Link's head as the game's own sprite has it, read from the ROM to draw the player with.

Where it is comes from the randomizer. write_sprite in its Rom.py puts a sprite's sheet at 0x80000 and its palettes at
0xDD308: 15 colours of two bytes for the green mail, then for the blue and for the red. get_image_for_sprite in its
SpriteSelector.py draws the head facing down from 0x40 bytes into the sheet, a picture of two tiles by two.
"""

from collections.abc import Mapping

SIZE = 16  # the head's width and height
MAILS = 3
_SHEET_AT, _PALETTES_AT = 0x80000, 0xDD308
_HEAD_AT = 0x40
_TILE = 0x20  # bytes in a tile, which is 8 by 8
_SHEET_ROW = 16 * _TILE  # a sheet is 16 tiles wide
_PALETTE = 15 * 2

# What to read of the ROM: name -> (address, length)
READS = {
    "head top": (_SHEET_AT + _HEAD_AT, 2 * _TILE),
    "head bottom": (_SHEET_AT + _HEAD_AT + _SHEET_ROW, 2 * _TILE),
    "palettes": (_PALETTES_AT, MAILS * _PALETTE),
}


def _tile(data: bytes) -> list[list[int]]:
    """A tile's colour numbers, by row. A row is four bit planes: two bytes at the row's place, and two 16 bytes on."""
    rows = []
    for y in range(8):
        planes = data[2 * y], data[2 * y + 1], data[2 * y + 16], data[2 * y + 17]
        rows.append([sum((plane >> (7 - x) & 1) << bit for bit, plane in enumerate(planes)) for x in range(8)])
    return rows


def decode(memory: Mapping[str, bytes]) -> list[bytes]:
    """The head in the colours of the green mail, the blue and the red: each SIZE by SIZE, by row, four bytes a pixel
    of red, green, blue and how solid it is, 255 or 0.

    memory: what was read of the ROM, by name in READS.
    """
    numbers = [[0] * SIZE for _ in range(SIZE)]
    for name, top in (("head top", 0), ("head bottom", 8)):
        for half in range(2):
            for y, row in enumerate(_tile(memory[name][half * _TILE : (half + 1) * _TILE])):
                numbers[top + y][half * 8 : half * 8 + 8] = row
    heads = []
    for mail in range(MAILS):
        colours = [bytes(4)]  # colour 0 is see-through
        for at in range(mail * _PALETTE, (mail + 1) * _PALETTE, 2):
            # Five bits each of red, green and blue
            packed = int.from_bytes(memory["palettes"][at : at + 2], "little")
            colours.append(bytes((packed >> shift & 0x1F) * 8 for shift in (0, 5, 10)) + b"\xff")
        heads.append(b"".join(colours[number] for row in numbers for number in row))
    return heads
