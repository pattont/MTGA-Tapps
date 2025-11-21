#!/usr/bin/env python3
"""Debug script to find YOUR seat ID by dumping relevant log data."""

import json
import sys
from pathlib import Path
from src.mtga_tracker.log_parser import MTGALogParser


def main():
    """Dump all seat-related info to find your identity."""
    try:
        parser = MTGALogParser()
        print("=" * 80)
        print("Finding YOUR Seat ID")
        print("=" * 80)
        print(f"Log file: {parser.log_path}\n")

        with open(parser.log_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        recent_lines = lines[-10000:] if len(lines) > 10000 else lines

        # Look for key patterns
        print("=" * 80)
        print("1. Looking for 'systemSeatId' in client messages...")
        print("=" * 80)

        client_seats = []
        for i, line in enumerate(recent_lines):
            if "clienttogre" in line.lower():
                json_data = parser.parse_json_from_line(line)
                if json_data and "systemSeatId" in str(json_data):
                    # Find the seat ID
                    def find_all_seats(obj, found=None):
                        if found is None:
                            found = []
                        if isinstance(obj, dict):
                            for k, v in obj.items():
                                if "seat" in k.lower() and isinstance(v, int):
                                    found.append((k, v))
                                find_all_seats(v, found)
                        elif isinstance(obj, list):
                            for item in obj:
                                find_all_seats(item, found)
                        return found

                    seats = find_all_seats(json_data)
                    if seats:
                        client_seats.append(seats)
                        if len(client_seats) <= 5:
                            print(f"  clientToGRE message found seats: {seats}")

        if client_seats:
            # Count which seat appears most
            seat_counts = {}
            for seat_list in client_seats:
                for key, val in seat_list:
                    seat_counts[val] = seat_counts.get(val, 0) + 1
            print(f"\n  Seat frequency in YOUR client messages: {seat_counts}")
            most_common = max(seat_counts, key=seat_counts.get)
            print(f"  → Most likely YOUR seat: {most_common}")
        else:
            print("  No client messages with seat IDs found")

        print("\n" + "=" * 80)
        print("2. Looking for YOUR player ID / account info...")
        print("=" * 80)

        your_player_id = None
        for line in lines:  # Search all lines for account info
            if "playerid" in line.lower() or "accountid" in line.lower() or "userid" in line.lower():
                json_data = parser.parse_json_from_line(line)
                if json_data:
                    data_str = json.dumps(json_data)
                    if "playerId" in data_str or "accountId" in data_str:
                        # Try to extract
                        def find_id(obj):
                            if isinstance(obj, dict):
                                for k in ["playerId", "accountId", "userId"]:
                                    if k in obj and obj[k]:
                                        return obj[k]
                                for v in obj.values():
                                    result = find_id(v)
                                    if result:
                                        return result
                            return None

                        pid = find_id(json_data)
                        if pid and not your_player_id:
                            your_player_id = pid
                            print(f"  Found player ID: {pid}")
                            break

        print("\n" + "=" * 80)
        print("3. Looking at reservedPlayers in match config...")
        print("=" * 80)

        for line in reversed(recent_lines):
            if "reservedplayers" in line.lower():
                json_data = parser.parse_json_from_line(line)
                if json_data:
                    data_str = json.dumps(json_data, indent=2)
                    # Find reservedPlayers array
                    def find_reserved(obj):
                        if isinstance(obj, dict):
                            if "reservedPlayers" in obj:
                                return obj["reservedPlayers"]
                            for v in obj.values():
                                result = find_reserved(v)
                                if result:
                                    return result
                        return None

                    reserved = find_reserved(json_data)
                    if reserved:
                        print(f"  Found {len(reserved)} players:")
                        for i, p in enumerate(reserved):
                            uid = p.get("userId", "?")
                            seat = p.get("systemSeatId", "?")
                            team = p.get("teamId", "?")
                            print(f"    Player {i+1}: userId={uid}, systemSeatId={seat}, teamId={team}")
                            if your_player_id and uid == your_player_id:
                                print(f"    ^^^ THIS IS YOU! Your seat = {seat}")
                        break

        print("\n" + "=" * 80)
        print("4. Looking at game state messages for clues...")
        print("=" * 80)

        # The key insight: YOUR hand is visible to you, opponent's is not
        # Look for zones where you can see card details
        for line in reversed(recent_lines[-2000:]):
            if "gamestatemessage" in line.lower():
                json_data = parser.parse_json_from_line(line)
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
                    if gs and "zones" in gs:
                        for zone in gs["zones"]:
                            zone_type = zone.get("type", "")
                            owner = zone.get("ownerSeatId")
                            visibility = zone.get("visibility", "")
                            obj_count = len(zone.get("objectInstanceIds", []))

                            # Your hand should be visible to you
                            if "Hand" in zone_type and visibility:
                                print(f"  Zone: {zone_type}, Owner: Seat {owner}, Visibility: {visibility}, Cards: {obj_count}")
                        break

        print("\n" + "=" * 80)
        print("5. Looking for 'seatId' in action responses...")
        print("=" * 80)

        for line in reversed(recent_lines[-3000:]):
            if "actionresp" in line.lower() or "mulligan" in line.lower():
                json_data = parser.parse_json_from_line(line)
                if json_data:
                    data_str = str(json_data)
                    if "seatId" in data_str or "systemSeatId" in data_str:
                        print(f"  Found action with seat info:")
                        # Pretty print just the relevant parts
                        def find_seats_verbose(obj, path=""):
                            if isinstance(obj, dict):
                                for k, v in obj.items():
                                    if "seat" in k.lower():
                                        print(f"    {path}.{k} = {v}")
                                    find_seats_verbose(v, f"{path}.{k}")
                        find_seats_verbose(json_data)
                        break

        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print("""
To determine YOUR seat, we need to find data that is unique to YOU.

Key insight: The log file is YOUR client's log!
- When YOU send a message, it shows YOUR seat
- Look at 'clientToGREMessage' - these are YOUR actions

If the seat detection is still wrong, the issue might be that
the tracker is detecting the seat from the wrong game session.

TRY THIS:
1. Close and restart MTGA completely
2. Start the tracker BEFORE starting a new match
3. The tracker should detect your seat from YOUR first action

The tracker should say:
  "🎮 Detected: You are Seat X (from your actions)"

If X is wrong, please run this script and share the output!
""")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
