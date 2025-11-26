#!/usr/bin/env python3
"""Debug script to test hand visibility player detection.

This script tests the CUMULATIVE approach to hand visibility detection.
It accumulates instanceId -> grpId mappings across all game state messages,
then checks hand zones to determine which player is YOU.
"""

import json
import sys
from pathlib import Path
from src.mtga_tracker.log_parser import MTGALogParser


def main():
    """Test the cumulative hand visibility detection."""
    try:
        parser = MTGALogParser()
        print("=" * 80)
        print("MTGA Hand Visibility Detection Test (Cumulative)")
        print("=" * 80)
        print(f"Log file: {parser.log_path}\n")

        with open(parser.log_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        recent_lines = lines[-10000:] if len(lines) > 10000 else lines

        # Step 1: Build cumulative instanceId -> grpId map
        print("Step 1: Building cumulative instanceId -> grpId map...")
        print("-" * 80)

        instance_to_grp = {}

        for line in recent_lines:
            event = parser.extract_card_events(line)
            if not event or event.get("type") != "game_state":
                continue

            data = event.get("data", {})
            game_objects = data.get("gameObjects", [])

            for obj in game_objects:
                instance_id = obj.get("instanceId")
                grp_id = obj.get("grpId", 0)

                if instance_id and grp_id and grp_id > 0:
                    instance_to_grp[instance_id] = grp_id

        print(f"Accumulated {len(instance_to_grp)} instanceId -> grpId mappings")
        if instance_to_grp:
            sample = list(instance_to_grp.items())[:5]
            print(f"Sample: {sample}")

        # Step 2: Find hand zones and check visibility
        print("\nStep 2: Scanning for hand zones (from most recent)...")
        print("-" * 80)

        detected_seat = None
        found_count = 0

        for line in reversed(recent_lines):
            event = parser.extract_card_events(line)
            if not event or event.get("type") != "game_state":
                continue

            data = event.get("data", {})
            zones = data.get("zones", [])

            # Find hand zones
            hands = []
            for zone in zones:
                zone_type = zone.get("type", "")
                if "Hand" in zone_type:
                    owner_seat = zone.get("ownerSeatId")
                    obj_ids = zone.get("objectInstanceIds", [])

                    if obj_ids and owner_seat:
                        visible = 0
                        hidden = 0
                        for oid in obj_ids:
                            grp = instance_to_grp.get(oid, 0)
                            if grp > 0:
                                visible += 1
                            else:
                                hidden += 1

                        hands.append({
                            'seat': owner_seat,
                            'visible': visible,
                            'hidden': hidden,
                            'total': len(obj_ids)
                        })

            # Only process if we have exactly 2 hands with cards
            if len(hands) == 2 and hands[0]['total'] > 0 and hands[1]['total'] > 0:
                found_count += 1

                if found_count <= 3:  # Show first 3 examples
                    print(f"\nGame State #{found_count}:")
                    for h in hands:
                        visibility_pct = (h['visible'] / h['total'] * 100) if h['total'] > 0 else 0
                        print(f"  Seat {h['seat']}: {h['total']} cards - "
                              f"{h['visible']} visible, {h['hidden']} hidden "
                              f"({visibility_pct:.0f}% visible)")

                    # Determine which seat is the player
                    hand1, hand2 = hands

                    # Clear case: one hand all visible, other all hidden
                    if hand1['visible'] > 0 and hand1['hidden'] == 0 and hand2['visible'] == 0:
                        your_seat = hand1['seat']
                    elif hand2['visible'] > 0 and hand2['hidden'] == 0 and hand1['visible'] == 0:
                        your_seat = hand2['seat']
                    # Compare visible counts
                    elif hand1['visible'] > hand2['visible']:
                        your_seat = hand1['seat']
                    elif hand2['visible'] > hand1['visible']:
                        your_seat = hand2['seat']
                    else:
                        your_seat = None

                    if your_seat:
                        print(f"  --> YOUR seat: {your_seat}")
                        if not detected_seat:
                            detected_seat = your_seat
                    else:
                        print(f"  --> Could not determine seat")

        print("\n" + "=" * 80)
        print("RESULTS")
        print("=" * 80)
        print(f"\nFound {found_count} game states with both player hands.")

        if detected_seat:
            print(f"\n*** DETECTED: You are Seat {detected_seat} ***")
            print(f"\nThis means:")
            print(f"  - Cards owned by Seat {detected_seat} are YOURS")
            print(f"  - Cards owned by Seat {3 - detected_seat} are OPPONENT's")
        else:
            print("\nCould not reliably detect your seat from hand visibility.")
            print("Possible reasons:")
            print("  1. No recent game with opening hands in log")
            print("  2. Not enough object data accumulated")
            print("\nTry running this after playing a game in MTGA.")

        # Step 3: Test the tracker's detection
        print("\n" + "=" * 80)
        print("Step 3: Testing tracker's detection method...")
        print("=" * 80)

        from src.mtga_tracker.tracker import CardTracker, GameState

        # Clear any manual override
        GameState.MANUAL_PLAYER_SEAT = None

        tracker = CardTracker(parser)
        tracker._detect_player_seat_from_log()

        if tracker.game_state.player_seat_id:
            print(f"\nTracker detected: You are Seat {tracker.game_state.player_seat_id}")
            print(f"Accumulated {len(tracker.game_state.instance_to_grp)} instanceId -> grpId mappings")
        else:
            print("\nTracker could not detect seat ID")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
