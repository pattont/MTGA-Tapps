#!/usr/bin/env python3
# DEPRECATED (2026-08): early-development debug relic, kept for reference only.
# Not maintained and likely broken — see tests/deprecated/README.md.
"""Debug script to identify player seat ID and life total structure."""

import json
import sys
from pathlib import Path
from src.mtga_tracker.log_parser import MTGALogParser


def main():
    """Analyze MTGA log to find correct seat mappings."""
    try:
        parser = MTGALogParser()
        print(f"Log file: {parser.log_path}")
        print("\n" + "="*80)
        print("Analyzing log for player seat ID...")
        print("="*80 + "\n")

        # Read the log file
        with open(parser.log_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        player_seat = None
        opponent_seat = None

        # Look for authenticateResponse which contains the player's userId
        for line in lines:
            if "authenticateResponse" in line.lower() or "\"screenname\"" in line.lower():
                json_data = parser.parse_json_from_line(line)
                if json_data and "authenticateResponse" in json_data:
                    screen_name = json_data.get("authenticateResponse", {}).get("screenName")
                    if screen_name:
                        print(f"✓ Found your screen name: {screen_name}")
                        break

        # Look for matchGameRoomStateChangedEvent to find seat assignment
        for line in lines:
            if "matchgameroomstatechangedevent" in line.lower():
                json_data = parser.parse_json_from_line(line)
                if json_data and "matchGameRoomStateChangedEvent" in json_data:
                    event = json_data["matchGameRoomStateChangedEvent"]
                    if "gameRoomInfo" in event and "gameRoomConfig" in event["gameRoomInfo"]:
                        config = event["gameRoomInfo"]["gameRoomConfig"]
                        if "reservedPlayers" in config:
                            print("\n✓ Found player seat assignments:")
                            for player in config["reservedPlayers"]:
                                player_id = player.get("userId", "unknown")
                                system_seat = player.get("systemSeatId")
                                team_id = player.get("teamId")
                                print(f"   Seat {system_seat}: Team {team_id}, User {player_id}")

                            # First player is usually you (seat 1)
                            if len(config["reservedPlayers"]) >= 2:
                                player_seat = config["reservedPlayers"][0].get("systemSeatId", 1)
                                opponent_seat = config["reservedPlayers"][1].get("systemSeatId", 2)
                                print(f"\n✓ Detected: You are seat {player_seat}, Opponent is seat {opponent_seat}")
                            break

        # Analyze game state messages for life and player info
        print("\n" + "="*80)
        print("Analyzing game state messages...")
        print("="*80 + "\n")

        found_game_state = False
        for line in lines[-1000:]:  # Check last 1000 lines
            event = parser.extract_card_events(line)
            if event and event.get("type") == "game_state":
                data = event.get("data", {})

                if "players" in data:
                    found_game_state = True
                    print("✓ Found player data structure:")
                    for player in data["players"]:
                        seat_id = player.get("systemSeatNumber")
                        life = player.get("lifeTotal")
                        pending_damage = player.get("pendingDamage", 0)
                        starting_life = player.get("startingLifeTotal")

                        print(f"\n   Seat {seat_id}:")
                        print(f"      Life: {life}")
                        print(f"      Starting Life: {starting_life}")
                        print(f"      Pending Damage: {pending_damage}")

                        if seat_id == player_seat:
                            print(f"      *** This is YOU ***")
                        elif seat_id == opponent_seat:
                            print(f"      *** This is OPPONENT ***")

                    # Only show first one
                    break

        if not found_game_state:
            print("⚠ No game state found. Make sure you're in an active game.")

        # Check for annotations with seat info
        print("\n" + "="*80)
        print("Checking card play annotations...")
        print("="*80 + "\n")

        found_annotations = False
        for line in lines[-1000:]:
            event = parser.extract_card_events(line)
            if event and event.get("type") == "game_state":
                data = event.get("data", {})

                if "annotations" in data and "gameObjects" in data:
                    for annotation in data["annotations"]:
                        ann_type = annotation.get("type", [])
                        if "AnnotationType_ZoneTransfer" in ann_type:
                            details = annotation.get("details", [])
                            category = None
                            for detail in details:
                                if detail.get("key") == "category":
                                    category = detail.get("valueString", [None])[0]

                            if category == "CastSpell":
                                found_annotations = True
                                affected_ids = annotation.get("affectedIds", [])
                                if affected_ids:
                                    instance_id = affected_ids[0]

                                    # Find the card object
                                    for obj in data["gameObjects"]:
                                        if obj.get("instanceId") == instance_id:
                                            grp_id = obj.get("grpId")
                                            owner_seat = obj.get("ownerSeatId")

                                            player_label = "YOU" if owner_seat == player_seat else "OPPONENT"
                                            print(f"✓ Card cast: grpId={grp_id}, ownerSeat={owner_seat} ({player_label})")
                                            break

                                # Only show a few examples
                                if found_annotations:
                                    break

                    if found_annotations:
                        break

        if not found_annotations:
            print("⚠ No card annotations found. Play some cards to test.")

        # Summary
        print("\n" + "="*80)
        print("SUMMARY")
        print("="*80)
        if player_seat and opponent_seat:
            print(f"\n✓ Your seat ID: {player_seat}")
            print(f"✓ Opponent seat ID: {opponent_seat}")
            print(f"\nThe tracker should check:")
            print(f"  - owner_seat == {player_seat} for YOUR cards")
            print(f"  - owner_seat == {opponent_seat} for OPPONENT cards")
            print(f"  - seat_id == {player_seat} for YOUR life total")
            print(f"  - seat_id == {opponent_seat} for OPPONENT life total")
        else:
            print("\n⚠ Could not determine seat assignments.")
            print("   Try running this while in an active game.")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
