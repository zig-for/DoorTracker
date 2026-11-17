"""A randomizer spoiler opened in place of a tracker file."""

from SpoilerToYaml import parse_doors


def test_a_big_key_door_the_spoiler_names_one_side_of_is_locked_on_both():
    doors = parse_doors(
        [
            "Eastern Courtyard N <=> Eastern Darkness S (Eastern Palace)",
            "Eastern Cannonball S <=> Eastern Courtyard Ledge S (Eastern Palace)",
            "Eastern Big Key NE <=> Eastern Compass Room SW (Eastern Palace)",
            "Door Types:",
            "Eastern Courtyard N (Eastern Palace) Big Key Door",
            # Only a big key door: nothing in the tracker goes by any other type
            "Eastern Cannonball S (Eastern Palace) Key Door",
            # A type the spoiler gives the far side itself is kept
            "Eastern Compass Room SW (Eastern Palace) Trap Door",
            "Eastern Big Key NE (Eastern Palace) Big Key Door",
        ]
    )
    assert doors["Eastern_Palace"]["special_doors"] == {
        "Eastern Courtyard N": "Big Key Door",
        "Eastern Darkness S": "Big Key Door",
        "Eastern Cannonball S": "Key Door",
        "Eastern Compass Room SW": "Trap Door",
        "Eastern Big Key NE": "Big Key Door",
    }
