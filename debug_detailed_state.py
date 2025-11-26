#!/usr/bin/env python3
"""Debug script to examine the detailed game state structure."""

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


def find_nested(obj, key, results=None):
    """Find all occurrences of a key in nested dict/list."""
    if results is None:
        results = []

    if isinstance(obj, dict):
        if key in obj:
            results.append(obj[key])
        for v in obj.values():
            find_nested(v, key, results)
    elif isinstance(obj, list):
        for item in obj:
            find_nested(item, key, results)

    return results


def main():
    home = Path.home()
    log_path = home / "Library/Logs/Wizards Of The Coast/MTGA/Player.log"

    if not log_path.exists():
        log_path = Path(f"{home}/AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log")

    print("=" * 80)
    print("Detailed Game State Structure Analysis")
    print("=" * 80)
    print(f"Log: {log_path}\n")

    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    recent = lines[-15000:] if len(lines) > 15000 else lines

    # Find a complete game state with zones
    for line in reversed(recent):
        if "gamestatemessage" not in line.lower():
            continue

        json_data = find_json_in_line(line)
        if not json_data:
            continue

        # Find gameStateMessage
        gsm = find_nested(json_data, "gameStateMessage")
        if not gsm:
            continue

        gs = gsm[0] if gsm else None
        if not gs or "zones" not in gs:
            continue

        zones = gs.get("zones", [])
        game_objects = gs.get("gameObjects", [])

        print(f"Found gameStateMessage:")
        print(f"  zones: {len(zones)}")
        print(f"  gameObjects: {len(game_objects)}")
        print(f"  other keys: {[k for k in gs.keys() if k not in ['zones', 'gameObjects']]}")

        # Analyze zones
        print("\n--- ZONES ---")
        for i, zone in enumerate(zones[:10]):
            zone_type = zone.get("type", "?")
            owner = zone.get("ownerSeatId", "?")
            obj_ids = zone.get("objectInstanceIds", [])
            visibility = zone.get("visibility", "?")
            print(f"  Zone {i}: type={zone_type}, owner=Seat{owner}, "
                  f"objects={len(obj_ids)}, visibility={visibility}")

        # Analyze game objects
        print("\n--- GAME OBJECTS (first 10) ---")
        for i, obj in enumerate(game_objects[:10]):
            instance_id = obj.get("instanceId", "?")
            grp_id = obj.get("grpId", "N/A")
            owner = obj.get("ownerSeatId", "?")
            zone_id = obj.get("zoneId", "?")
            obj_type = obj.get("type", "?")
            name = obj.get("name", "?")
            card_types = obj.get("cardTypes", [])

            print(f"  Obj {i}: instanceId={instance_id}, grpId={grp_id}, "
                  f"owner=Seat{owner}, zone={zone_id}, type={obj_type}")

            if grp_id == "N/A" or grp_id == 0:
                # Show all keys for this object to find where card ID might be
                print(f"       Keys: {list(obj.keys())[:10]}")

        # Check if grpId is somewhere else
        print("\n--- SEARCHING FOR grpId LOCATIONS ---")
        all_grp_ids = find_nested(json_data, "grpId")
        print(f"Found {len(all_grp_ids)} grpId values in entire message")
        if all_grp_ids:
            unique_grps = set(all_grp_ids[:20])
            print(f"Sample grpIds: {list(unique_grps)[:10]}")

        # Look for alternative card identifier keys
        print("\n--- ALTERNATIVE CARD ID KEYS ---")
        for key in ["cardId", "mtgaId", "templateId", "catalogId", "arenaId"]:
            values = find_nested(json_data, key)
            if values:
                print(f"  {key}: found {len(values)} values, samples: {values[:5]}")

        # Look at a hand zone specifically
        print("\n--- HAND ZONE DETAILS ---")
        for zone in zones:
            if "Hand" in str(zone.get("type", "")):
                owner = zone.get("ownerSeatId")
                obj_ids = zone.get("objectInstanceIds", [])
                print(f"\nSeat {owner} Hand zone:")
                print(f"  Zone keys: {list(zone.keys())}")
                print(f"  Object IDs in hand: {obj_ids[:7]}")

                # Find these objects in gameObjects
                for oid in obj_ids[:5]:
                    for obj in game_objects:
                        if obj.get("instanceId") == oid:
                            print(f"  Object {oid}:")
                            print(f"    grpId: {obj.get('grpId', 'N/A')}")
                            print(f"    ownerSeatId: {obj.get('ownerSeatId', 'N/A')}")
                            print(f"    All keys: {list(obj.keys())}")
                            break
                    else:
                        print(f"  Object {oid}: NOT FOUND in gameObjects")

        # Look for diffed updates that might contain grpId
        print("\n--- CHECKING FOR DIFF UPDATES ---")
        diff_objs = gs.get("diffDeletedInstanceIds", [])
        print(f"diffDeletedInstanceIds: {len(diff_objs)} items")

        # Check annotations
        annotations = gs.get("annotations", [])
        print(f"\nannotations: {len(annotations)} items")

        break

    # Also look for initial hand dealing messages
    print("\n" + "=" * 80)
    print("Looking for OpeningHandMessage or initial hand data...")
    print("=" * 80)

    for line in recent:
        if "openinghand" in line.lower() or "initialdraw" in line.lower():
            print(f"\nFound: ...{line[:200]}...")
            json_data = find_json_in_line(line)
            if json_data:
                grp_ids = find_nested(json_data, "grpId")
                print(f"  grpIds found: {grp_ids[:10] if grp_ids else 'None'}")
            break


if __name__ == "__main__":
    main()
