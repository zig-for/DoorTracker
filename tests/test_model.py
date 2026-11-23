"""Joining rooms into blocks, the save file, removing supertiles, and layout."""

import copy

from data.doors_data import dark_tiles, default_one_way_connections, dungeon_lobbies
from gui.Doors import seed_map
from gui.Doors.bosses import BOSS_ROOMS
from gui.Doors.randomizer import doors_and_portals
from gui.Doors.rooms import DOORS, INTERIOR_DOORS, SPLIT, SUPERTILES, supertile
from support import VANILLA, a_rom, grow, joined_doors, new_model, next_link, open_doors, positions


def stairs_pair(model):
    """An up stair and a down stair, in two lit, unsplit supertiles that are not on the map."""

    def stair(facing, avoid=None):
        return next(
            d
            for tile in sorted(SUPERTILES)
            if tile not in model.tiles and tile not in dark_tiles and tile != avoid and SPLIT.part_count(tile) == 1
            for d in supertile(tile).doors
            if DOORS[d].facing == facing and d not in INTERIOR_DOORS
        )

    up = stair("Up")
    return up, stair("Dn", avoid=DOORS[up].tile)


def test_rooms_linked_through_facing_doorways_are_joined():
    model = new_model()
    door, other = next_link(model)
    model.add_link(door, other)
    (link,) = model.door_links
    a, b = model.rooms.node(door), model.rooms.node(other)
    assert link in model.blocks.joined
    assert model.blocks.root[a] == model.blocks.root[b]
    # The two doorways meet, and each keeps its dot
    ax, ay = model.port(door)
    bx, by = model.port(other)
    assert abs(ax - bx) + abs(ay - by) < 40
    assert door in {dot.door for dot in model.door_dots(a)}


def test_stairs_link_rooms_without_joining_them():
    model = grow(new_model(), 4)
    up, down = stairs_pair(model)
    model.add_link(up, down)
    link = model.door_links[-1]
    assert link not in model.blocks.joined
    assert model.blocks.root[model.rooms.node(up)] != model.blocks.root[model.rooms.node(down)]
    assert "cannot be joined" in (model.toggle_join(link) or "")


def test_a_join_split_by_hand_stays_split():
    model = grow(new_model(), 3)
    link = model.door_links[0]
    assert link in model.blocks.joined
    assert model.toggle_join(link) is None
    model.add_link(*next_link(model))
    assert link not in model.blocks.joined

    again = new_model()
    again.load(model.save())
    assert (link.door, link.linked_door) not in joined_doors(again)
    assert joined_doors(again) == joined_doors(model)


def test_removing_a_link_leaves_the_other_joins_alone():
    model = grow(new_model(), 6)
    before = joined_doors(model)
    removed = model.door_links[0]
    model.remove_link(removed)
    assert joined_doors(model) == [pair for pair in before if pair != (removed.door, removed.linked_door)]


def contested_map():
    """A map where two links want the same spot, and the one that got it is not the one the default order picks."""
    base = grow(new_model(), 8)
    loser = next(x for x in base.door_links if base.join_offset(x.door, x.linked_door) is not None and x not in base.blocks.joined)
    saved = base.save()
    saved["joined_links"].insert(0, base.door_links.index(loser))
    model = new_model()
    model.load(saved)
    assert (loser.door, loser.linked_door) in joined_doors(model)
    assert joined_doors(model) != joined_doors(base)
    return model


def decorated_map():
    """A contested map with a bit of everything else a save has to carry."""
    model = contested_map()
    model.add_link(*stairs_pair(model))
    model.toggle_join(next(x for x in model.door_links if x in model.blocks.joined))
    model.set_pinned(model.rooms.node(model.door_links[3].door), True)
    spare = [d for tile in model.tiles for d in open_doors(model, tile)]
    model.annotate(spare[0], "Bow", [])
    # A boss as the seed's own map gives it, and the mark of a map that came from there
    model.reveal_bosses({(4, 10): "Mothula"})
    model.revealed = True
    model.auto_add_lobby(next(d for d in spare[1:] if DOORS[d].facing == "So"))

    # Still contested: the default order would join different links
    by_default = new_model()
    by_default.load({**model.save(), "joined_links": []})
    assert joined_doors(by_default) != joined_doors(model)
    return model


def contents(model):
    """Everything a save has to carry, read from the model."""
    return {
        "links": [(link.door, link.linked_door, link.join) for link in model.door_links],
        "joined": joined_doors(model),
        "lobbies": [(lobby.door, lobby.lobby) for lobby in model.lobby_doors],
        "icons": model.special_doors,
        "bosses": model.bosses,
        "from the seed": (model.revealed, model.bosses_revealed),
        "pinned": model.fixed,
        "lit": {tile: state.has_been_lit for tile, state in model.tiles.items()},
        "positions": {node: (round(x, 1), round(y, 1)) for node, (x, y) in model.pos.items()},
    }


def test_a_save_loads_back_to_the_same_map():
    model = decorated_map()
    saved = model.save()
    again = new_model()
    again.load(copy.deepcopy(saved))
    assert contents(again) == contents(model)
    assert again.save() == saved


def test_files_from_before_join_was_called_join_still_load():
    model = decorated_map()
    saved = model.save()
    older = copy.deepcopy(saved)
    older["stacked_links"] = older.pop("joined_links")
    for entry in older["door_links"]:
        if "join" in entry:
            entry["stack"] = entry.pop("join")
    again = new_model()
    again.load(older)
    assert contents(again) == contents(model)


def test_a_file_with_no_saved_joins_gets_them_from_its_positions():
    model = decorated_map()
    saved = model.save()
    del saved["joined_links"]
    again = new_model()
    again.load(saved)
    assert joined_doors(again) == joined_doors(model)


def test_a_file_naming_doors_this_version_does_not_know_still_loads():
    model = decorated_map()
    saved = model.save()
    saved["door_links"].append({"door": "No Such Door N", "linked_door": saved["door_links"][0]["door"]})
    saved["lobby_doors"].append({"door": "No Such Door S", "lobby": "Nowhere"})
    saved["special_doors"]["No Such Door E"] = "Bow"

    again = new_model()
    again.load(saved)
    again.relayout()
    assert joined_doors(again) == joined_doors(model)
    assert all("No Such Door" not in edge.a + edge.b for edge in again.edges())
    assert again.save()["door_links"] == saved["door_links"]


def test_an_icon_put_on_an_entrance_takes_its_place():
    model = new_model()
    door = next(d for tile in model.tiles for d in open_doors(model, tile) if DOORS[d].facing == "So")
    lobbies = list(dungeon_lobbies[model.tab_world])
    for icon, entrances in ((lobbies[0], [(door, lobbies[0])]), (lobbies[1], [(door, lobbies[1])]), ("Bow", [])):
        model.annotate(door, icon, lobbies)
        assert [(lobby.door, lobby.lobby) for lobby in model.lobby_doors if lobby.door == door] == entrances
        assert model.special_doors[door] == icon


def test_a_boss_room_shows_the_boss_picked_for_it():
    model = new_model("Eastern_Palace")
    tile = (8, 12)
    model.add_tile(tile, has_been_lit=True)
    (node,) = [n for n in model.nodes() if n.tile == tile and model.boss_spots(n)]
    for picked in (None, "Mothula", None):
        model.set_boss(tile, picked)
        (spot,) = model.boss_spots(node)
        assert spot.boss == picked


def test_removing_a_supertile_removes_everything_on_it():
    model = decorated_map()
    link = model.door_links[2]
    tile = DOORS[link.linked_door].tile
    node = model.rooms.node(link.linked_door)
    model.set_pinned(node, True)
    model.toggle_expanded(node)
    model.move_player(tile, 250, 250)
    model.move_player(tile, 250, 250)
    model.annotate(open_doors(model, tile)[0], "Bow", [])

    assert model.remove_tile(tile) is True
    doors = set(supertile(tile).doors)
    assert not [x for x in model.door_links if x.door in doors or x.linked_door in doors]
    assert not doors & set(model.special_doors)
    assert model.player is None
    for nodes in (model.pos, model.fixed, model.kept_expanded, model.visited, model.blocks.root, model.nodes()):
        assert not [n for n in nodes if n.tile == tile]
    # Still a working map
    model.relayout()
    model.save()

    start = next(iter(new_model().tiles))
    assert model.remove_tile(start) is False


def test_relayout_leaves_no_rooms_overlapping():
    model = grow(new_model(), 20)
    model.relayout()

    # Parts of one supertile may share picture area; any two supertiles may not, joined or not
    boxes = []
    for node, (x, y) in model.pos.items():
        for left, top, right, bottom in model.pieces(node):
            boxes.append((node.tile, x + left, y + top, x + right, y + bottom))
    for i, (tile, left, top, right, bottom) in enumerate(boxes):
        for other, l2, t2, r2, b2 in boxes[i + 1 :]:
            if other != tile:
                assert right <= l2 or r2 <= left or bottom <= t2 or b2 <= top, (tile, other)


def test_relayout_leaves_pinned_rooms_where_they_are():
    model = grow(new_model(), 20)
    pinned = model.rooms.node(model.door_links[4].linked_door)
    model.set_pinned(pinned, True)
    before = positions(model)
    held = model.blocks.of(pinned)
    model.relayout()

    def moved(node):
        (x, y), (was_x, was_y) = positions(model)[node], before[node]
        return abs(x - was_x) + abs(y - was_y) > 0.01

    assert not [node for node in held if moved(node)]
    assert [node for node in before if moved(node)]


def test_adding_a_room_does_not_move_the_rooms_already_there():
    model = grow(new_model(), 8)
    model.relayout()
    before = positions(model)

    # A room with no link yet, as the tracker adds it; then the link
    door, other = next_link(model)
    model.add_tile(DOORS[other].tile, has_been_lit=True)
    assert {node: positions(model)[node] for node in before} == before
    model.auto_add_door_link(door, other)
    moved = [node for node in before if positions(model)[node] != before[node]]
    assert moved == []


def test_a_hole_is_linked_only_to_where_a_hole_lands_and_nothing_else_is_linked_to_there():
    hole, landing = "Ice Bomb Drop Hole", "Ice Stalfos Hint Drop Entrance"
    stairs = ("Hera Lobby Key Stairs", "Hera Tile Room Up Stairs")
    shuffled = new_model("Ice_Palace", vanilla_drops=False)
    assert shuffled.can_link(hole, landing) and shuffled.can_link(*stairs)
    assert not shuffled.can_link(stairs[0], landing) and not shuffled.can_link(hole, stairs[1])
    # Auto-tracking makes no such link either
    assert shuffled.auto_add_door_link(stairs[1], landing) is False
    # With holes landing where the original game's do, a hole and its landing are not linked at all
    as_they_were = new_model("Ice_Palace")
    assert not as_they_were.can_link(hole, landing) and as_they_were.can_link(*stairs)


def test_no_room_is_laid_out_on_an_entrances_marker():
    # Skull Woods as in the original game: the room south of the first lobby would join on under its entrance
    seed = seed_map.decode(a_rom(VANILLA, default_one_way_connections))
    model = new_model("Skull_Woods")
    model.show_seed(seed.links(decoupled=False), {name: door for name, door in seed.entrances.items() if name in dungeon_lobbies[model.tab_world]})
    assert any(model.marker_boxes(node) for node in model.nodes())
    for node in model.nodes():
        x, y = model.pos[node]
        for left, top, right, bottom in model.marker_boxes(node):
            for other in model.nodes():
                ox, oy = model.pos[other]
                on_it = [p for p in model.pieces(other) if x + left < ox + p[2] and ox + p[0] < x + right and y + top < oy + p[3] and oy + p[1] < y + bottom]
                assert other == node or not on_it, (node, other)


def test_a_seeds_links_and_entrances_are_read_back_from_its_rom():
    # Two of the original game's links, a west door to an east one and an east to a west, joined the other way
    (a, b), (c, d) = VANILLA[0], VANILLA[1]
    pairs = [(a, c), (b, d), *VANILLA[2:]]
    # Three entrances moved: to a room's right door, to a left one, and to a middle one
    moved = {"Eastern": "Eastern Hint Tile Blocked Path SE", "Skull 1": "Skull Star Pits SW", "Skull 3": "Eastern Darkness S"}
    # Three boss rooms given other bosses: Eastern's, the Ice Palace's and Misery Mire's
    seed = seed_map.decode(a_rom(pairs, default_one_way_connections, moved, bosses={0xC8: "Mothula", 0xDE: "Vitreous", 0x90: "Kholdstare"}))
    assert seed.leads == {**dict(pairs), **{y: x for x, y in pairs}, **dict(default_one_way_connections)}
    assert seed.entrances == {portal.name: portal.door.name for portal in doors_and_portals()[1]} | moved
    assert [seed.bosses[tile] for tile in ((8, 12), (14, 13), (0, 9))] == ["Mothula", "Vitreous", "Kholdstare"]
    # The rest have their own, as Ganon's Tower's three do
    assert [seed.bosses[tile] for tile in ((12, 1), (12, 6), (13, 4))] == ["Armos Knights", "Lanmolas", "Moldorm"]
    assert set(seed.bosses) == set(BOSS_ROOMS)
    # Each pair once, and the ways into rooms with no way back
    assert len(seed.links(decoupled=False)) == len(pairs) + len(default_one_way_connections)


def test_the_cheat_gives_each_tab_its_own_dungeon_as_the_seed_made_it():
    seed = seed_map.decode(a_rom(VANILLA, default_one_way_connections))
    for tab in sorted({record.dungeon for record in SUPERTILES.values() if record.dungeon}):
        # Rooms only fallen into are the dungeon's too, whatever the option says of where holes land
        model = new_model(tab, vanilla_drops=False)
        model.add_tile(DOORS["Hera Lobby S"].tile, has_been_lit=True)  # what was on the map goes
        mine = {name: door for name, door in seed.entrances.items() if name in dungeon_lobbies[model.tab_world]}
        model.show_seed(seed.links(decoupled=False), mine)
        model.reveal_bosses(seed.bosses)
        # With the doors as in the original game, that is the dungeon's own rooms, all lit, each boss room with its boss
        assert set(model.tiles) == {tile for tile, record in SUPERTILES.items() if record.dungeon == tab}, tab
        assert set(model.bosses) == set(model.tiles) & set(BOSS_ROOMS), tab
        assert not model.bosses_to_reveal()
        assert not any(model.is_hidden_dark(tile) for tile in model.tiles)
        assert set(mine.values()) <= {lobby.door for lobby in model.lobby_doors}
