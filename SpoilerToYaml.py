from collections import defaultdict
from data.doors_data import (
    doors_data,
    doors_to_regions,
    regions_to_doors,
    interior_doors,
    default_door_connections,
    default_one_way_connections,
    spiral_staircases,
    straight_staircases,
    open_edges,
    ladders,
)

vanilla_connections = {}
for data in [
        default_door_connections,
        default_one_way_connections,
        spiral_staircases,
        straight_staircases,
        open_edges,
        ladders,
        interior_doors,
    ]:
        for door, linked_door in data:
            vanilla_connections[door] = linked_door
vanilla_connections_rev = {v: k for k, v in vanilla_connections.items()}

def parse_doors(door_data):
    mode = "doors"
    doors = defaultdict(lambda: dict([("door_links", []), ("lobby_doors", []), ("special_doors", {}), ("tiles", {})]))
    regions_seen = defaultdict(list)  # dungeon -> the regions of the doors the spoiler links there
    lone_big_key_doors = []  # (dungeon, door) for each big key door the spoiler names one side of

    for line in door_data:
        if line.strip() == "":
            continue
        if line.startswith("Dungeon Lobbies"):
            mode = "lobbies"
            print("Lobbies")
            continue
        if line.startswith("Door Types"):
            mode = "types"
            print("Types")
            continue

        if mode == "doors":
            if " <=> " in line:
                door, linked_door = line.split(" <=> ")
            elif  " => " in line:
                door, linked_door = line.split(" => ")
            else:
                print("Error parsing door data (decoupled not yet supported): " + line)
                continue
            dungeon_name = linked_door.split(" (")[-1].strip(")").replace(" ", "_")
            ld_list = linked_door.split(" (")  # Remove dungeon names
            linked_door = " (".join(ld_list[:-1]).strip()
            doors[dungeon_name]["door_links"].append({"door": door.strip(), "linked_door": linked_door})
            door_tile = f"{int(doors_data[door][0]) % 16}__{int(doors_data[door][0]) // 16}"
            linked_door_tile = f"{int(doors_data[linked_door][0]) % 16}__{int(doors_data[linked_door][0]) // 16}"
            doors[dungeon_name]["tiles"][door_tile] = True
            doors[dungeon_name]["tiles"][linked_door_tile] = True
            for i in [doors_to_regions[door], doors_to_regions[linked_door]]:
                regions_seen[dungeon_name] += i if type(i) == list else [i]
        if mode == "lobbies":
            lobby, door = line.split(": ")
            doors["lobbies"][lobby.strip()] = door.strip()
        if mode == "types":
            # Extract dungeon name from brackets
            dsplit = line.split("(")
            door_type = dsplit[-1].split(")")[-1].strip()
            dungeon = dsplit[-1].split(")")[0].strip().replace(" ", "_")
            door = "(".join(dsplit[:-1])
            if " <-> " in door:
                door, linked_door = door.split(" <-> ")
                doors[dungeon]["special_doors"][door.strip()] = door_type
                doors[dungeon]["special_doors"][linked_door.strip()] = door_type
            else:
                door = door.strip()
                doors[dungeon]["special_doors"][door] = door_type
                if door_type == "Big Key Door":
                    lone_big_key_doors.append((dungeon, door))

    # The other doors of the rooms the spoiler names are linked as in the original game. This waits until every
    # line is read: a door can be listed after another of its room
    linked = {name for found in doors.values() for link in found["door_links"] for name in (link["door"], link["linked_door"])}
    for dungeon, regions in regions_seen.items():
        for door in (door for region in regions for door in regions_to_doors[region]):
            leads_to = vanilla_connections.get(door) or vanilla_connections_rev.get(door)
            if door not in linked and leads_to:
                doors[dungeon]["door_links"].append({"door": door, "linked_door": leads_to})
                linked |= {door, leads_to}
    # The randomizer mostly locks the door a big key door leads to as well, and the spoiler does not say when it has
    # not: it is taken as locked, unless the spoiler gives it a type of its own
    links = [(link["door"], link["linked_door"]) for found in doors.values() for link in found["door_links"]]
    for dungeon, door in lone_big_key_doors:
        far_side = next((b if a == door else a for a, b in links if door in (a, b)), None)
        if far_side is not None:
            doors[dungeon]["special_doors"].setdefault(far_side, "Big Key Door")
    return doors


def parse_dr_spoiler(fh) -> dict:
    yaml_data = {"placements": {1: {}}}
    fh.seek(0)
    spoiler_data = [line.strip() for line in fh.readlines()]
    log_locs = {"Doors:": None, "Locations:": None, "Playthrough:": None}
    for section in log_locs.keys():
        try:
            log_locs[section] = spoiler_data.index(section)
        except ValueError:
            pass
    log_locs = {k: v for k, v in log_locs.items() if v is not None}
    for n, (section, index) in enumerate(log_locs.items()):
        if section == "Playthrough:":
            continue
        data = spoiler_data[index + 1 : list(log_locs.values())[n + 1] - 1]
        if section == "Doors:":
            return parse_doors(data)
    return yaml_data
