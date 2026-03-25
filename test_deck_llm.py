#!/usr/bin/env python3
"""Test deck LLM: config loading and API call. Run from project root: python test_deck_llm.py

This test uses the same prompt as at game end: send a list of card names and ask the LLM
for exactly one short deck archetype (e.g. "Izzet Control", "Mono-Red Aggro"). If the LLM
returns "Unknown" or nothing, the tracker shows no "Opponent deck" line.
"""

import sys
from pathlib import Path

# Run from project root: add src so mtga_tracker is found, and root so config.py is found
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
for p in (str(SRC), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

def main():
    from mtga_tracker.deck_llm import diagnose, test_call

    print("Deck LLM diagnostic")
    print("=" * 50)
    d = diagnose()
    for k, v in d.items():
        print(f"  {k}: {v}")
    print()

    if not d["enabled"]:
        print("DECK_LLM_ENABLED is False or not set. Set DECK_LLM_ENABLED = True in config.py or env.")
        return
    if not d["has_api_key"]:
        print("No API key found. Set GEMINI_API_KEY (or CHATGPT_API_KEY / CLAUDE_API_KEY) in config.py or env.")
        if not d["config_loaded"]:
            print("Config did not load. Run this script from the project root: python test_deck_llm.py")
        return

    # Same prompt as at game end: card names -> one short deck archetype
    cards = ["Lightning Bolt", "Counterspell", "Island", "Mountain", "Steam Vents"]
    print("Test: send card names, ask for one short deck archetype (same as game end)")
    print("  Prompt: You are an expert on MTGA deck archetypes. Given cards seen, reply with")
    print('  exactly one short deck name (e.g. "Izzet Control", "Mono-Red Aggro") or "Unknown".')
    print()
    print("  Cards sent:")
    for c in cards:
        print(f"    - {c}")
    print()
    print("  Calling API...")
    result, err = test_call(cards)
    if err:
        print(f"  Error: {err}")
    elif result:
        print(f"  Archetype: {result}")
    else:
        print("  Archetype: (none)")
        print("  The LLM returned nothing or 'Unknown', so the tracker would not show")
        print('  "Opponent deck: ..." at game end.')

if __name__ == "__main__":
    main()
