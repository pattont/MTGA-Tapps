#!/usr/bin/env python3
"""Debug script to examine zone structure in MTGA logs."""

import json
import sys
from pathlib import Path
from src.mtga_tracker.log_parser import MTGALogParser


def main():
    """Examine how zones are structured in game state messages."""
    try:
        parser = MTGALogParser()
        print("=" * 80)
        print("Zone Structure Analysis")
        print("=" * 80)
        print(f"Log file: {parser.log_path}\n")

        with open(parser.log_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        recent_lines = lines[-10000:] if len(lines) > 10000 else lines

        # First, find all game states and analyze their zone structures
        print("Analyzing all game state messages for zones...")
        print("-" * 80)

        zone_stats = {
            'total_messages': 0,
            'messages_with_zones': 0,
            'messages_with_hands': 0,
            'messages_with_2_hands': 0,
            'zone_types_seen': set(),
            'hand_cards_per_message': []
        }

        for i, line in enumerate(recent_lines):
            event = parser.extract_card_events(line)
            if not event or event.get("type") != "game_state":
                continue

            zone_stats['total_messages'] += 1
            data = event.get("data", {})
            zones = data.get("zones", [])

            if zones:
                zone_stats['messages_with_zones'] += 1

                hand_zones = []
                for zone in zones:
                    zone_type = zone.get("type", "")
                    zone_stats['zone_types_seen'].add(zone_type)

                    if "Hand" in zone_type:
                        owner = zone.get("ownerSeatId")
                        obj_ids = zone.get("objectInstanceIds", [])
                        hand_zones.append({
                            'owner': owner,
                            'cards': len(obj_ids)
                        })

                if hand_zones:
                    zone_stats['messages_with_hands'] += 1
                    if len(hand_zones) >= 2:
                        zone_stats['messages_with_2_hands'] += 1
                        zone_stats['hand_cards_per_message'].append(
                            [(h['owner'], h['cards']) for h in hand_zones]
                        )

        print(f"Total game state messages: {zone_stats['total_messages']}")
        print(f"Messages with zones: {zone_stats['messages_with_zones']}")
        print(f"Messages with hand zones: {zone_stats['messages_with_hands']}")
        print(f"Messages with 2+ hand zones: {zone_stats['messages_with_2_hands']}")
        print(f"\nZone types seen: {zone_stats['zone_types_seen']}")

        if zone_stats['hand_cards_per_message']:
            print(f"\nHand data samples (seat, cards):")
            for sample in zone_stats['hand_cards_per_message'][:5]:
                print(f"  {sample}")

        # Look at ALL hand zones individually (not requiring 2 in same message)
        print("\n" + "=" * 80)
        print("All individual hand zones found:")
        print("-" * 80)

        all_hands = []
        instance_to_grp = {}

        # Build instance map
        for line in recent_lines:
            event = parser.extract_card_events(line)
            if not event or event.get("type") != "game_state":
                continue
            data = event.get("data", {})
            for obj in data.get("gameObjects", []):
                iid = obj.get("instanceId")
                grp = obj.get("grpId", 0)
                if iid and grp > 0:
                    instance_to_grp[iid] = grp

        # Find all hands
        for line in recent_lines:
            event = parser.extract_card_events(line)
            if not event or event.get("type") != "game_state":
                continue
            data = event.get("data", {})
            for zone in data.get("zones", []):
                zone_type = zone.get("type", "")
                if "Hand" in zone_type:
                    owner = zone.get("ownerSeatId")
                    obj_ids = zone.get("objectInstanceIds", [])
                    if obj_ids:
                        visible = sum(1 for oid in obj_ids if instance_to_grp.get(oid, 0) > 0)
                        all_hands.append({
                            'seat': owner,
                            'total': len(obj_ids),
                            'visible': visible,
                            'obj_ids': obj_ids[:5]  # First 5 for debugging
                        })

        print(f"Found {len(all_hands)} hand zones total")
        if all_hands:
            for i, h in enumerate(all_hands[:10]):
                print(f"  Hand {i+1}: Seat {h['seat']}, {h['total']} cards, {h['visible']} visible")
                print(f"           Object IDs: {h['obj_ids']}")

        # Group hands by seat and find patterns
        print("\n" + "=" * 80)
        print("Hands grouped by seat:")
        print("-" * 80)

        seat_hands = {}
        for h in all_hands:
            seat = h['seat']
            if seat not in seat_hands:
                seat_hands[seat] = []
            seat_hands[seat].append(h)

        for seat, hands in seat_hands.items():
            print(f"\nSeat {seat}: {len(hands)} hand updates")
            visible_counts = [h['visible'] for h in hands]
            print(f"  Visible card counts: {visible_counts[:10]}...")
            if any(v > 0 for v in visible_counts):
                print(f"  *** Has visible cards - likely YOUR seat ***")
            else:
                print(f"  No visible cards - likely OPPONENT's seat")

        # Determine seat based on visibility
        print("\n" + "=" * 80)
        print("DETECTION RESULT:")
        print("=" * 80)

        your_seat = None
        for seat, hands in seat_hands.items():
            if any(h['visible'] > 0 for h in hands):
                your_seat = seat
                break

        if your_seat:
            print(f"\n*** You are Seat {your_seat} ***")
        else:
            print("\nCould not determine your seat")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
