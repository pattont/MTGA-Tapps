#!/usr/bin/env python3
"""Debug script to find reliable player identity detection."""

import json
import sys
from pathlib import Path
from src.mtga_tracker.log_parser import MTGALogParser


def main():
    """Find the most reliable way to identify the local player."""
    try:
        parser = MTGALogParser()
        print("=" * 80)
        print("MTGA Player Identity Analyzer")
        print("=" * 80)
        print(f"Log file: {parser.log_path}\n")
        print("Looking for reliable player identification methods...")
        print("=" * 80 + "\n")

        # Read the log file
        with open(parser.log_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            lines = content.split('\n')

        # Method 1: Look for your screen name / account info
        print("METHOD 1: Screen Name / Account Info")
        print("-" * 80)
        for line in lines:
            if "screenname" in line.lower() or "playername" in line.lower() or "displayname" in line.lower():
                json_data = parser.parse_json_from_line(line)
                if json_data:
                    print(f"Found potential player info: {list(json_data.keys())[:5]}")
                    if "Payload" in json_data:
                        payload = json_data.get("Payload", {})
                        if isinstance(payload, str):
                            try:
                                payload = json.loads(payload)
                            except:
                                pass
                        if isinstance(payload, dict):
                            for key in ["screenName", "playerName", "displayName"]:
                                if key in payload:
                                    print(f"  ✓ Your {key}: {payload[key]}")
                    break

        # Method 2: Look for clientToGREMessage - YOUR actions
        print("\nMETHOD 2: Client-to-Server Messages (YOUR actions)")
        print("-" * 80)
        your_seat_from_actions = None
        for line in lines[-2000:]:  # Recent lines
            if "clienttogremessage" in line.lower() or "clienttomatchdoormessage" in line.lower():
                json_data = parser.parse_json_from_line(line)
                if json_data:
                    # Look for seat ID in your messages
                    def find_seat(obj, path=""):
                        if isinstance(obj, dict):
                            for k, v in obj.items():
                                if k.lower() in ["systemseatid", "seatid", "playerseatid"]:
                                    print(f"  ✓ Found YOUR seat in {path}: {k} = {v}")
                                    return v
                                result = find_seat(v, f"{path}.{k}")
                                if result:
                                    return result
                        elif isinstance(obj, list):
                            for i, v in enumerate(obj):
                                result = find_seat(v, f"{path}[{i}]")
                                if result:
                                    return result
                        return None

                    seat = find_seat(json_data)
                    if seat and not your_seat_from_actions:
                        your_seat_from_actions = seat
                        print(f"  ✓ YOUR seat ID (from your actions): {seat}")

        # Method 3: Look for match config with your userId
        print("\nMETHOD 3: Match Config (reservedPlayers)")
        print("-" * 80)
        your_user_id = None
        your_seat_from_config = None

        # First find your userId
        for line in lines:
            if "authenticate" in line.lower():
                json_data = parser.parse_json_from_line(line)
                if json_data:
                    def find_userid(obj):
                        if isinstance(obj, dict):
                            for k, v in obj.items():
                                if k.lower() == "userid" or k.lower() == "accountid":
                                    return v
                                result = find_userid(v)
                                if result:
                                    return result
                        return None
                    uid = find_userid(json_data)
                    if uid:
                        your_user_id = uid
                        print(f"  ✓ Your userId: {uid}")
                        break

        # Then find which seat has your userId
        for line in lines:
            if "reservedplayers" in line.lower():
                json_data = parser.parse_json_from_line(line)
                if json_data:
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
                        print(f"  Found reservedPlayers with {len(reserved)} entries:")
                        for i, player in enumerate(reserved):
                            uid = player.get("userId", "?")
                            seat = player.get("systemSeatId", "?")
                            team = player.get("teamId", "?")
                            print(f"    Player {i+1}: userId={uid}, seat={seat}, team={team}")
                            if your_user_id and uid == your_user_id:
                                your_seat_from_config = seat
                                print(f"    ✓ This is YOU!")
                        break

        # Method 4: Look for mulligan decisions from YOUR client
        print("\nMETHOD 4: Mulligan Decisions (YOUR choices)")
        print("-" * 80)
        for line in lines[-3000:]:
            if "mulligan" in line.lower() and "clientto" in line.lower():
                json_data = parser.parse_json_from_line(line)
                if json_data:
                    print(f"  Found mulligan decision from client")
                    # Your mulligan decision indicates your seat
                    def find_mulligan_seat(obj):
                        if isinstance(obj, dict):
                            if "systemSeatId" in obj:
                                return obj["systemSeatId"]
                            for v in obj.values():
                                result = find_mulligan_seat(v)
                                if result:
                                    return result
                        return None
                    seat = find_mulligan_seat(json_data)
                    if seat:
                        print(f"  ✓ YOUR seat from mulligan: {seat}")
                    break

        # Method 5: Look for "controllerSeatId" in your played cards
        print("\nMETHOD 5: Controller Seat in Played Cards")
        print("-" * 80)
        print("  Looking for cards you control...")

        # Summary
        print("\n" + "=" * 80)
        print("SUMMARY: Recommended Player Detection")
        print("=" * 80)

        if your_seat_from_actions:
            print(f"\n✓ BEST METHOD: Your seat ID from YOUR actions: {your_seat_from_actions}")
            print("  Reason: clientToGREMessage comes FROM your client, so the seat in")
            print("          those messages is definitively YOUR seat.")
        elif your_seat_from_config:
            print(f"\n✓ ALTERNATIVE: Your seat from config + userId: {your_seat_from_config}")
            print("  Reason: Match your userId to seat assignment in reservedPlayers")
        else:
            print("\n⚠ Could not reliably detect your seat ID")
            print("  Run this while in an active game for better results")

        print("\nRECOMMENDED IMPLEMENTATION:")
        print("-" * 80)
        print("""
1. Look for 'clientToGREMessage' or 'clientToMatchDoorMessage'
2. Extract the systemSeatId from YOUR client's messages
3. That seat ID is definitively YOU (not the opponent)
4. The other seat is the opponent

This works because:
- Messages FROM your client are YOUR actions
- The seat ID in those messages is YOUR seat
- This doesn't depend on who goes first or array order
""")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
