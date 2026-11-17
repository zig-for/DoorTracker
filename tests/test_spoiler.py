"""A randomizer spoiler opened in place of a tracker file."""

from SpoilerToYaml import parse_doors


def test_a_big_key_door_the_spoiler_names_one_side_of_is_locked_on_both():
    doors = parse_doors(
        [
            "Eastern Courtyard N <=> Eastern Darkness S (Eastern Palace)",
            # Another door of the courtyard, listed after it
            "Eastern Courtyard EN <=> Eastern Big Key NE (Eastern Palace)",
            "Eastern Cannonball S <=> Eastern Courtyard Ledge S (Eastern Palace)",
            "Eastern Big Key EN <=> Eastern Compass Room SW (Eastern Palace)",
            "Door Types:",
            "Eastern Courtyard N (Eastern Palace) Big Key Door",
            "Eastern Courtyard EN (Eastern Palace) Big Key Door",
            # Only a big key door: nothing in the tracker goes by any other type
            "Eastern Cannonball S (Eastern Palace) Key Door",
            # A type the spoiler gives the far side itself is kept, wherever its line is
            "Eastern Big Key EN (Eastern Palace) Big Key Door",
            "Eastern Compass Room SW (Eastern Palace) Trap Door",
        ]
    )["Eastern_Palace"]
    assert doors["special_doors"] == {
        "Eastern Courtyard N": "Big Key Door",
        "Eastern Darkness S": "Big Key Door",
        "Eastern Courtyard EN": "Big Key Door",
        "Eastern Big Key NE": "Big Key Door",
        "Eastern Cannonball S": "Key Door",
        "Eastern Big Key EN": "Big Key Door",
        "Eastern Compass Room SW": "Trap Door",
    }
    # A door the spoiler links has that link and no other
    links = [(link["door"], link["linked_door"]) for link in doors["door_links"]]
    assert [link for link in links if "Eastern Courtyard EN" in link] == [("Eastern Courtyard EN", "Eastern Big Key NE")]
    # and one it does not list is linked as in the original game
    assert ("Eastern Courtyard WN", "Eastern Hint Tile EN") in links
