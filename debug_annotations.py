#!/usr/bin/env python3
"""Debug script to see all annotations and categories in game events."""

import json
import sys
from pathlib import Path
from src.mtga_tracker.log_parser import MTGALogParser
from src.mtga_tracker.card_database import CardDatabase


def main():
    """Analyze annotations to understand instant and destruction tracking."""
    try:
        parser = MTGALogParser()
        card_db = CardDatabase()

        print("=" * 80)
        print("MTGA Annotation Analyzer")
        print("=" * 80)
        print(f"Log file: {parser.log_path}\n")
        print("Analyzing recent game events for annotations...")
        print("Looking for: Instants, Sorceries, Destruction, Zone Transfers")
        print("=" * 80 + "\n")

        # Read recent log entries
        with open(parser.log_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            recent_lines = lines[-3000:] if len(lines) > 3000 else lines

        annotations_found = []

        for line in recent_lines:
            event = parser.extract_card_events(line)
            if event and event.get("type") == "game_state":
                data = event.get("data", {})

                if "annotations" in data:
                    game_objects = data.get("gameObjects", [])

                    for annotation in data["annotations"]:
                        ann_type = annotation.get("type", [])
                        affected_ids = annotation.get("affectedIds", [])
                        details = annotation.get("details", [])

                        # Extract details
                        category = None
                        zone_src = None
                        zone_dest = None

                        for detail in details:
                            key = detail.get("key", "")
                            if key == "category":
                                category = detail.get("valueString", [None])[0]
                            elif key == "zone_src":
                                zone_src = detail.get("valueInt32", [None])[0]
                            elif key == "zone_dest":
                                zone_dest = detail.get("valueInt32", [None])[0]

                        # Get card info
                        card_info = []
                        for instance_id in affected_ids:
                            for obj in game_objects:
                                if obj.get("instanceId") == instance_id:
                                    grp_id = obj.get("grpId")
                                    card_name = card_db.get_card_name(grp_id) if grp_id else "Unknown"
                                    card_types = obj.get("cardTypes", [])
                                    owner_seat = obj.get("ownerSeatId")

                                    card_info.append({
                                        "name": card_name,
                                        "grpId": grp_id,
                                        "types": card_types,
                                        "owner": owner_seat,
                                        "instance": instance_id
                                    })
                                    break

                        # Store annotation
                        if card_info:  # Only store if we found card info
                            annotations_found.append({
                                "types": ann_type,
                                "category": category,
                                "zone_src": zone_src,
                                "zone_dest": zone_dest,
                                "cards": card_info
                            })

        # Analyze and display
        if not annotations_found:
            print("⚠ No annotations found in recent log.")
            print("   Try playing some cards and run this again.")
            return

        print(f"✓ Found {len(annotations_found)} annotations\n")

        # Group by category
        by_category = {}
        for ann in annotations_found:
            cat = ann["category"] or "None"
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(ann)

        print("=" * 80)
        print("ANNOTATIONS BY CATEGORY")
        print("=" * 80 + "\n")

        for category in sorted(by_category.keys()):
            anns = by_category[category]
            print(f"Category: {category} ({len(anns)} occurrences)")
            print("-" * 80)

            # Show examples
            for i, ann in enumerate(anns[:5]):  # Show first 5 of each category
                types = ", ".join(ann["types"]) if ann["types"] else "None"
                print(f"\n  Example {i+1}:")
                print(f"    Annotation Types: {types}")
                print(f"    Zone: {ann['zone_src']} → {ann['zone_dest']}")

                for card in ann["cards"]:
                    card_types_str = ", ".join([t.replace("CardType_", "") for t in card["types"]])
                    print(f"    Card: {card['name']} ({card_types_str})")
                    print(f"          Owner Seat: {card['owner']}, Instance: {card['instance']}")

            if len(anns) > 5:
                print(f"\n  ... and {len(anns) - 5} more")
            print()

        # Check specifically for instants
        print("=" * 80)
        print("INSTANT/SORCERY ANALYSIS")
        print("=" * 80 + "\n")

        instant_count = 0
        sorcery_count = 0

        for ann in annotations_found:
            for card in ann["cards"]:
                if "CardType_Instant" in card["types"]:
                    instant_count += 1
                    print(f"✓ Instant: {card['name']}")
                    print(f"  Category: {ann['category']}")
                    print(f"  Types: {', '.join(ann['types'])}")
                    print(f"  Zone: {ann['zone_src']} → {ann['zone_dest']}")
                    print()
                elif "CardType_Sorcery" in card["types"]:
                    sorcery_count += 1
                    print(f"✓ Sorcery: {card['name']}")
                    print(f"  Category: {ann['category']}")
                    print(f"  Types: {', '.join(ann['types'])}")
                    print(f"  Zone: {ann['zone_src']} → {ann['zone_dest']}")
                    print()

        print(f"Total instants found: {instant_count}")
        print(f"Total sorceries found: {sorcery_count}\n")

        # Check for destroy/exile patterns
        print("=" * 80)
        print("DESTRUCTION/REMOVAL ANALYSIS")
        print("=" * 80 + "\n")

        removal_categories = ["Destroy", "Exile", "Countered", "Discard", "Sacrifice"]

        for cat in removal_categories:
            if cat in by_category:
                print(f"\n{cat} ({len(by_category[cat])} occurrences):")
                for ann in by_category[cat][:3]:  # Show first 3
                    for card in ann["cards"]:
                        print(f"  • {card['name']} (Owner: Seat {card['owner']})")

        print("\n" + "=" * 80)
        print("RECOMMENDATIONS")
        print("=" * 80)

        if instant_count == 0:
            print("\n⚠ No instants found in recent log.")
            print("   Cast some instants and re-run this script.")
        else:
            print(f"\n✓ Found {instant_count} instants with these categories:")
            instant_categories = set()
            for ann in annotations_found:
                for card in ann["cards"]:
                    if "CardType_Instant" in card["types"]:
                        instant_categories.add(ann["category"])
            for cat in instant_categories:
                print(f"   - {cat}")

        if "Destroy" in by_category:
            print("\n✓ Destroy events detected - these should show destruction interactions")

        print("\nAll unique categories found:")
        for cat in sorted(by_category.keys()):
            print(f"  - {cat}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
