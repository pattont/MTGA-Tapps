#!/usr/bin/env python3
"""Find the actual opening hand message that contains card IDs."""

import json
import sys
from pathlib import Path


def find_json_in_line(line):
    """Extract JSON object from a log line."""
    start = line.find('{')
    if start == -1:
        return None

    depth = 0
    for i, char in enumerate(line[start:], start):
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(line[start:i+1])
                except:
                    return None
    return None


def find_all_keys(obj, target_keys, results=None, path=""):
    """Find all occurrences of target keys."""
    if results is None:
        results = []

    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in target_keys:
                results.append((path + "." + k, v))
            find_all_keys(v, target_keys, results, path + "." + k)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            find_all_keys(item, target_keys, results, path + f"[{i}]")

    return results


def main():
    home = Path.home()
    log_path = home / "Library/Logs/Wizards Of The Coast/MTGA/Player.log"

    if not log_path.exists():
        log_path = Path(f"{home}/AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log")

    print("=" * 80)
    print("Looking for Opening Hand Messages with Card IDs")
    print("=" * 80)
    print(f"Log: {log_path}\n")

    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    recent = lines[-20000:] if len(lines) > 20000 else lines

    # Look for messages related to opening hand, mulligan, initial game state
    keywords = [
        "mulligan", "openinghand", "initialhand", "startinghand",
        "gamestart", "matchstarted", "gamebegin"
    ]

    print("1. Searching for hand-related messages...\n")

    for keyword in keywords:
        count = sum(1 for line in recent if keyword in line.lower())
        print(f"  '{keyword}': {count} lines")

    print("\n2. Analyzing mulligan messages (contain opening hand)...\n")

    mulligan_count = 0
    for line in recent:
        if "mulligan" in line.lower():
            mulligan_count += 1
            json_data = find_json_in_line(line)
            if json_data and mulligan_count <= 5:
                print(f"--- Mulligan message #{mulligan_count} ---")

                # Look for grpIds
                grp_results = find_all_keys(json_data, ["grpId", "grpIds", "cardId"])
                if grp_results:
                    print(f"  Found card IDs:")
                    for path, value in grp_results[:10]:
                        print(f"    {path}: {value}")

                # Look for seat IDs
                seat_results = find_all_keys(json_data, ["systemSeatId", "seatId", "playerSeatId"])
                if seat_results:
                    print(f"  Found seat IDs:")
                    for path, value in seat_results[:5]:
                        print(f"    {path}: {value}")

                print()

    print(f"Total mulligan messages: {mulligan_count}")

    # Look for GREToClient events with full game state
    print("\n" + "=" * 80)
    print("3. Looking for initial game state with full object list...")
    print("=" * 80 + "\n")

    # Find game states with many game objects (initial states are larger)
    for line in recent:
        if "gretoclient" not in line.lower():
            continue

        json_data = find_json_in_line(line)
        if not json_data:
            continue

        # Find gameStateMessage
        def find_gsm(obj):
            if isinstance(obj, dict):
                if "gameStateMessage" in obj:
                    return obj["gameStateMessage"]
                for v in obj.values():
                    r = find_gsm(v)
                    if r:
                        return r
            return None

        gsm = find_gsm(json_data)
        if not gsm:
            continue

        game_objects = gsm.get("gameObjects", [])
        zones = gsm.get("zones", [])

        # Look for larger game states (initial ones have more objects)
        if len(game_objects) > 20:
            print(f"Found large game state: {len(game_objects)} objects, {len(zones)} zones")

            # Find hands
            hand_zones = [z for z in zones if "Hand" in str(z.get("type", ""))]
            for hz in hand_zones:
                owner = hz.get("ownerSeatId")
                obj_ids = hz.get("objectInstanceIds", [])
                print(f"\n  Seat {owner} Hand ({len(obj_ids)} cards):")

                # Find these objects
                for oid in obj_ids:
                    for obj in game_objects:
                        if obj.get("instanceId") == oid:
                            grp = obj.get("grpId", "?")
                            print(f"    instanceId={oid}, grpId={grp}")
                            break
                    else:
                        print(f"    instanceId={oid}, NOT IN gameObjects")

            break

    # Alternative: build cumulative instance->grpId map
    print("\n" + "=" * 80)
    print("4. Building cumulative instanceId -> grpId map...")
    print("=" * 80 + "\n")

    instance_to_grp = {}

    for line in recent:
        if "gameobject" not in line.lower() and "grpid" not in line.lower():
            continue

        json_data = find_json_in_line(line)
        if not json_data:
            continue

        # Find all gameObjects arrays
        def find_game_objects(obj, found=None):
            if found is None:
                found = []
            if isinstance(obj, dict):
                if "gameObjects" in obj:
                    found.extend(obj["gameObjects"])
                for v in obj.values():
                    find_game_objects(v, found)
            elif isinstance(obj, list):
                for item in obj:
                    find_game_objects(item, found)
            return found

        game_objects = find_game_objects(json_data)
        for obj in game_objects:
            iid = obj.get("instanceId")
            grp = obj.get("grpId")
            if iid and grp and grp > 0:
                instance_to_grp[iid] = grp

    print(f"Built map with {len(instance_to_grp)} instanceId -> grpId mappings")
    print(f"Sample: {list(instance_to_grp.items())[:10]}")

    # Now check hand zones with cumulative map
    print("\n5. Re-checking hand zones with cumulative map...")

    for line in reversed(recent):
        if "zone" not in line.lower() or "hand" not in line.lower():
            continue

        json_data = find_json_in_line(line)
        if not json_data:
            continue

        def find_zones(obj, found=None):
            if found is None:
                found = []
            if isinstance(obj, dict):
                if "zones" in obj:
                    found.extend(obj["zones"])
                for v in obj.values():
                    find_zones(v, found)
            return found

        zones = find_zones(json_data)
        hand_zones = [z for z in zones if "Hand" in str(z.get("type", ""))]

        if len(hand_zones) >= 2:
            print("\nFound 2 hand zones:")
            for hz in hand_zones:
                owner = hz.get("ownerSeatId")
                obj_ids = hz.get("objectInstanceIds", [])
                visible = sum(1 for oid in obj_ids if instance_to_grp.get(oid, 0) > 0)
                print(f"  Seat {owner}: {len(obj_ids)} cards, {visible} with known grpId")

            break


if __name__ == "__main__":
    main()
