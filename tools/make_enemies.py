"""Generate data/enemies: a picture at game size of each kind of enemy a kill room can hold, from the pictures of
StripesOO7's ALttP PopTracker pack, https://github.com/StripesOO7/alttp-ap-poptracker-pack (as of its commit
5f57a21), which are Zelda Wiki's.

    uv run tools/make_enemies.py <the pack's images/Enemies folder>
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageOps  # noqa: E402

from gui.Doors.kill_rooms import PICKS  # noqa: E402

# What an enemy can be picked as -> the pack's name for its picture
PICTURES = {
    "Raven": "Raven",
    "Vulture": "Vulture",
    "Octorok": "Octorok (one-way)",
    "Buzzblob": "Buzzblob",
    "Snapdragon": "Snapdragon",
    "Octoballoon": "Octoballoon",
    "Hinox": "Hinox",
    "Moblin": "Moblin",
    "MiniHelmasaur": "Mini Helmasaur",
    "Hoarder": "Bush Hoarder",
    "MiniMoldorm": "Mini Moldorm",
    "Poe": "Poe",
    "Sluggula": "Sluggula",
    "Ropa": "Ropa",
    "RedBari": "Red Bari",
    "BlueBari": "Blue Bari",
    "HardhatBeetle": "Hardhat Beetle",
    "Deadrock": "Deadrock",
    "Hoarder2": "Rock Hoarder",
    "BlueGuard": "Blue Sword Soldier",
    "GreenGuard": "Green Sword Soldier",
    "RedSpearGuard": "Red Spear Soldier",
    "BluesainBolt": "Assault Sword Soldier",
    "UsainBolt": "Green Spear Soldier",
    "BlueArcher": "Blue Archer",
    "GreenBushGuard": "Green Bush Archer",
    "RedJavelinGuard": "Red Javelin Soldier",
    "RedBushGuard": "Red Bush Javelin Soldier",
    "BombGuard": "Red Bomb Soldier",
    "GreenKnifeGuard": "Green Soldier Recruit",
    "Geldman": "Geldman",
    "Popo": "Popo",
    "ArmosStatue": "Armos",
    "FireballZora": "Fireball Zora",
    "Crab": "Crab",
    "Debirando": "Devalant (shooter)",
    "BallNChain": "Ball and Chain Trooper",
    "CannonTrooper": "Cannon Soldier",
    "CricketRat": "Rat",
    "Snake": "Rope",
    "Leever": "Leever",
    "FloatingSkull": "Floating Stalfos Head",
    "Hover": "Water Tektite",
    "GreenEyegoreMimic": "Green Eyegore",
    "RedEyegoreMimic": "Red Eyegore",
    "Kodongo": "Kodongo",
    "Gibdo": "Gibdo",
    "Terrorpin": "Terrorpin",
    "Blob": "Slime",
    "StalfosKnight": "Stalfos Knight",
    "Pengator": "Pengator",
    "Wizzrobe": "Wizzrobe",
    "Zoro": "Zoro",
    "Babasu": "Babasu",
    "BlueZazak": "Blue Zazak",
    "RedZazak": "Red Zazak",
    "Stalfos": "Stalfos",
    "GreenZirro": "Green Zirro",
    "BlueZirro": "Blue Zirro",
    "Pikit": "Pikit",
    "Gibo": "Gibo",
    "Pokey": "Hokku-Bokku",
    "Tektite": "Tektite",
    "Lynel": "Lynel",
    "Stal": "Stal",
    "GreenMimic": "Mimic",
    "RedMimic": "Mimic",
}
# The pack has one picture for the two Mimics, its left half red and its right green: which half each is
MIMIC_HALVES = {"RedMimic": "left", "GreenMimic": "right"}
# A kind the game draws from either of two sheets of graphics -> the pack's name for how it looks on the second.
# Its picture is the left half of the first look and the right half of this one
SECOND_LOOKS = {
    "Raven": "New folder/Kyune",
    "Octorok": "New folder/Slarok",
    "FireballZora": "New folder/Ku",
    "Snake": "New folder/Stalrope",
}


def game_size(picture: Image.Image) -> Image.Image:
    """A picture the pack has enlarged, each pixel a square of them, brought back to one pixel each."""
    for times in range(min(picture.size), 1, -1):
        if picture.width % times == 0 and picture.height % times == 0:
            small = picture.resize((picture.width // times, picture.height // times), Image.Resampling.NEAREST)
            if small.resize(picture.size, Image.Resampling.NEAREST).tobytes() == picture.tobytes():
                return small
    return picture


def whole(picture: Image.Image, half: str) -> Image.Image:
    """One half of a picture and its mirror image."""
    wide = picture.width // 2
    kept = picture.crop((0, 0, wide, picture.height) if half == "left" else (picture.width - wide, 0, picture.width, picture.height))
    made = Image.new("RGBA", (wide * 2, picture.height))
    made.paste(kept, (0 if half == "left" else wide, 0))
    made.paste(ImageOps.mirror(kept), (wide if half == "left" else 0, 0))
    return made


def main():
    pack = Path(sys.argv[1])

    def read(name: str) -> Image.Image:
        return game_size(Image.open(pack / f"{name}.png").convert("RGBA"))

    assert set(PICTURES) == set(PICKS), set(PICTURES) ^ set(PICKS)
    for kind, name in PICTURES.items():
        picture = read(name)
        if kind in MIMIC_HALVES:
            picture = whole(picture, MIMIC_HALVES[kind])
        if kind in SECOND_LOOKS:
            second = read(SECOND_LOOKS[kind])
            assert second.size == picture.size, kind
            middle = picture.width // 2
            picture.paste(second.crop((middle, 0, second.width, second.height)), (middle, 0))
        picture.save(ROOT / "data" / "enemies" / f"{kind}.png")


if __name__ == "__main__":
    main()
