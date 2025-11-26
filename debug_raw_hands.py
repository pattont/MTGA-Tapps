#!/usr/bin/env python3
"""Debug script to examine raw hand data in the MTGA log."""

import json
import re
import sys
from pathlib import Path


def find_json_in_line(line):
    """Extract JSON object from a log line."""
    # Look for JSON that starts with { and ends with }
    start = line.find('{')
    if start == -1:
        return None

    # Track bracket depth to find matching closing brace
    depth = 0
    for i, char in enumerate(line[start:], start):
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(line[start:i+1])
                except json.JSONDecodeError:
                    return None
    return None


def main():
    """Examine raw hand zone data in the log."""
    # Find log path
    home = Path.home()
    log_paths = [
        home / "Library/Logs/Wizards Of The Coast/MTGA/Player.log",
        Path(f"{home}/AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log"),
    ]

    log_path = None
    for p in log_paths:
        if p.exists():
            log_path = p
            break

    if not log_path:
        print("Could not find MTGA log file")
        sys.exit(1)

    print("=" * 80)
    print("Raw Hand Data Analysis")
    print("=" * 80)
    print(f"Log file: {log_path}\n")

    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        lines = content.split('\n')

    recent_lines = lines[-15000:] if len(lines) > 15000 else lines

    print("1. Searching for 'ZoneType_Hand' in recent log...\n")

    hand_count = 0
    for i, line in enumerate(recent_lines):
        if "ZoneType_Hand" in line or '"Hand"' in line or '"type":"Hand"' in line:
            hand_count += 1
            if hand_count <= 3:
                print(f"Found at line ~{i}: ...{line[max(0,line.find('Hand')-30):line.find('Hand')+50]}...")

    print(f"\nTotal lines with 'Hand' zone: {hand_count}")

    print("\n" + "=" * 80)
    print("2. Searching for gameStateMessage with zones...\n")

    game_state_count = 0
    for i, line in enumerate(recent_lines):
        if "gamestatemessage" in line.lower() and "zones" in line.lower():
            game_state_count += 1
            if game_state_count <= 3:
                json_data = find_json_in_line(line)
                if json_data:
                    # Navigate to find zones
                    def find_zones(obj, path=""):
                        if isinstance(obj, dict):
                            if "zones" in obj:
                                return obj["zones"]
                            for k, v in obj.items():
                                result = find_zones(v, f"{path}.{k}")
                                if result:
                                    return result
                        return None

                    zones = find_zones(json_data)
                    if zones:
                        print(f"Game State #{game_state_count}: Found {len(zones)} zones")
                        for z in zones:
                            zone_type = z.get("type", "?")
                            owner = z.get("ownerSeatId", "?")
                            obj_ids = z.get("objectInstanceIds", [])
                            if "Hand" in str(zone_type):
                                print(f"  HAND: owner=Seat{owner}, cards={len(obj_ids)}")

    print(f"\nTotal gameStateMessage with zones: {game_state_count}")

    print("\n" + "=" * 80)
    print("3. Looking for greToClientEvent with gameStateMessage...\n")

    gre_count = 0
    for i, line in enumerate(recent_lines):
        if "gretoclientevent" in line.lower():
            gre_count += 1

    print(f"Total greToClientEvent lines: {gre_count}")

    print("\n" + "=" * 80)
    print("4. Looking for gameObjects with grpId...\n")

    grp_id_count = 0
    for i, line in enumerate(recent_lines):
        if '"grpid"' in line.lower() or '"grpId"' in line:
            grp_id_count += 1

    print(f"Total lines with grpId: {grp_id_count}")

    print("\n" + "=" * 80)
    print("5. Sample extraction of full game state...\n")

    # Find the most recent complete game state message
    for line in reversed(recent_lines):
        if "gamestatemessage" in line.lower():
            json_data = find_json_in_line(line)
            if json_data:
                def find_game_state(obj):
                    if isinstance(obj, dict):
                        if "gameStateMessage" in obj:
                            return obj["gameStateMessage"]
                        for v in obj.values():
                            result = find_game_state(v)
                            if result:
                                return result
                    return None

                gs = find_game_state(json_data)
                if gs and "zones" in gs and "gameObjects" in gs:
                    zones = gs.get("zones", [])
                    game_objects = gs.get("gameObjects", [])

                    print(f"Found game state with {len(zones)} zones and {len(game_objects)} game objects")

                    # Build grpId map
                    instance_to_grp = {}
                    for obj in game_objects:
                        iid = obj.get("instanceId")
                        grp = obj.get("grpId", 0)
                        if iid:
                            instance_to_grp[iid] = grp

                    # Check hand zones
                    for zone in zones:
                        zone_type = zone.get("type", "")
                        if "Hand" in str(zone_type):
                            owner = zone.get("ownerSeatId")
                            obj_ids = zone.get("objectInstanceIds", [])
                            visible = sum(1 for oid in obj_ids if instance_to_grp.get(oid, 0) > 0)
                            hidden = len(obj_ids) - visible

                            print(f"\nSeat {owner} Hand:")
                            print(f"  Total cards: {len(obj_ids)}")
                            print(f"  Visible (grpId > 0): {visible}")
                            print(f"  Hidden (grpId = 0): {hidden}")

                            if visible == len(obj_ids) and len(obj_ids) > 0:
                                print(f"  --> ALL VISIBLE = YOUR hand")
                            elif hidden == len(obj_ids) and len(obj_ids) > 0:
                                print(f"  --> ALL HIDDEN = OPPONENT's hand")

                            # Show first few card details
                            for oid in obj_ids[:3]:
                                grp = instance_to_grp.get(oid, 0)
                                print(f"    - instanceId={oid}, grpId={grp}")

                    break

    print("\n" + "=" * 80)
    print("6. Alternative: Check log_parser.extract_card_events output...\n")

    try:
        from src.mtga_tracker.log_parser import MTGALogParser
        parser = MTGALogParser()

        found = 0
        for line in reversed(recent_lines[-5000:]):
            event = parser.extract_card_events(line)
            if event and event.get("type") == "game_state":
                data = event.get("data", {})
                if "zones" in data and "gameObjects" in data:
                    found += 1
                    if found == 1:
                        zones = data.get("zones", [])
                        game_objects = data.get("gameObjects", [])
                        print(f"log_parser found: {len(zones)} zones, {len(game_objects)} game objects")

                        instance_to_grp = {
                            obj.get("instanceId"): obj.get("grpId", 0)
                            for obj in game_objects
                            if obj.get("instanceId")
                        }

                        for zone in zones:
                            if "Hand" in str(zone.get("type", "")):
                                owner = zone.get("ownerSeatId")
                                obj_ids = zone.get("objectInstanceIds", [])
                                visible = sum(1 for oid in obj_ids if instance_to_grp.get(oid, 0) > 0)
                                print(f"  Seat {owner} Hand: {len(obj_ids)} cards, {visible} visible")
                    if found >= 3:
                        break

        print(f"\nlog_parser found {found} game states with zones+gameObjects")

    except Exception as e:
        print(f"Error using log_parser: {e}")


if __name__ == "__main__":
    main()
