#!/usr/bin/env python3
# DEPRECATED (2026-08): early-development debug relic, kept for reference only.
# Not maintained and likely broken — see tests/deprecated/README.md.
"""Simulate a MTGA game to preview tracker output.

This script simulates what the tracker output would look like during a game,
showing cards in hand, on battlefield, and being played.
"""

import time
from datetime import datetime
from typing import List, Dict


class GameSimulator:
    """Simulates a MTGA game for preview purposes."""

    def __init__(self):
        self.player_hand: List[str] = []
        self.opponent_hand: List[str] = []
        self.player_battlefield: List[str] = []
        self.opponent_battlefield: List[str] = []
        self.player_graveyard: List[str] = []
        self.opponent_graveyard: List[str] = []
        self.turn = 1
        self.current_player = "You"

    def print_header(self):
        """Print the tracker header."""
        print("=" * 80)
        print("MTGA Card Tracker - Game Simulation")
        print("=" * 80)
        print()

    def print_separator(self):
        """Print a visual separator."""
        print("-" * 80)

    def print_game_state(self):
        """Print the current game state."""
        print()
        print(f"Turn {self.turn} - {self.current_player}'s Turn")
        print()
        
        # Opponent's side (top)
        print("┌─ OPPONENT ─────────────────────────────────────────────────────────────┐")
        print(f"│ Hand: {len(self.opponent_hand)} cards" + " " * (67 - len(f"Hand: {len(self.opponent_hand)} cards")) + "│")
        if self.opponent_battlefield:
            battlefield_str = ", ".join(self.opponent_battlefield)
            # Wrap long battlefield lists
            if len(battlefield_str) > 70:
                parts = battlefield_str.split(", ")
                for i, part in enumerate(parts):
                    if i == 0:
                        print(f"│ Battlefield: {part}" + " " * (67 - len(f"Battlefield: {part}")) + "│")
                    else:
                        print(f"│             {part}" + " " * (67 - len(f"             {part}")) + "│")
            else:
                print(f"│ Battlefield: {battlefield_str}" + " " * (67 - len(f"Battlefield: {battlefield_str}")) + "│")
        else:
            print("│ Battlefield: (empty)" + " " * 58 + "│")
        print("└──────────────────────────────────────────────────────────────────────┘")
        print()
        
        # Your side (bottom)
        print("┌─ YOU ─────────────────────────────────────────────────────────────────┐")
        if self.player_battlefield:
            battlefield_str = ", ".join(self.player_battlefield)
            # Wrap long battlefield lists
            if len(battlefield_str) > 70:
                parts = battlefield_str.split(", ")
                for i, part in enumerate(parts):
                    if i == 0:
                        print(f"│ Battlefield: {part}" + " " * (67 - len(f"Battlefield: {part}")) + "│")
                    else:
                        print(f"│             {part}" + " " * (67 - len(f"             {part}")) + "│")
            else:
                print(f"│ Battlefield: {battlefield_str}" + " " * (67 - len(f"Battlefield: {battlefield_str}")) + "│")
        else:
            print("│ Battlefield: (empty)" + " " * 58 + "│")
        print(f"│ Hand: {len(self.player_hand)} cards" + " " * (67 - len(f"Hand: {len(self.player_hand)} cards")) + "│")
        if self.player_hand:
            hand_str = ", ".join(self.player_hand)
            if len(hand_str) > 70:
                parts = hand_str.split(", ")
                for i, part in enumerate(parts):
                    if i == 0:
                        print(f"│             {part}" + " " * (67 - len(f"             {part}")) + "│")
                    else:
                        print(f"│             {part}" + " " * (67 - len(f"             {part}")) + "│")
            else:
                print(f"│             {hand_str}" + " " * (67 - len(f"             {hand_str}")) + "│")
        print("└──────────────────────────────────────────────────────────────────────┘")
        print()

    def print_card_play(self, player: str, card: str, action: str = "played"):
        """Print a card play event."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        player_label = "YOU" if player == "You" else "OPPONENT"
        print(f"[{timestamp}] {player_label:9} {action.upper():8} → {card}")

    def simulate_turn(self, player: str, actions: List[Dict]):
        """Simulate a turn with given actions."""
        self.current_player = player
        self.print_game_state()
        
        for action in actions:
            time.sleep(1.5)  # Pause between actions for readability
            
            action_type = action.get("type")
            card = action.get("card")
            
            if action_type == "play":
                self.print_card_play(player, card, "played")
                # Check if it's an instant or sorcery (goes to graveyard)
                is_instant_sorcery = card in [
                    "Shock", "Lightning Bolt", "Opt", "Counterspell", 
                    "Cryptic Command", "Serum Visions", "Lava Spike"
                ]
                
                if player == "You":
                    if card in self.player_hand:
                        self.player_hand.remove(card)
                    if is_instant_sorcery:
                        self.player_graveyard.append(card)
                    else:
                        self.player_battlefield.append(card)
                else:
                    if card in self.opponent_hand:
                        self.opponent_hand.remove(card)
                    if is_instant_sorcery:
                        self.opponent_graveyard.append(card)
                    else:
                        self.opponent_battlefield.append(card)
            
            elif action_type == "draw":
                self.print_card_play(player, card, "drew")
                if player == "You":
                    self.player_hand.append(card)
                else:
                    self.opponent_hand.append(card)
            
            elif action_type == "attack":
                self.print_card_play(player, card, "attacks")
            
            elif action_type == "block":
                self.print_card_play(player, card, "blocks")
            
            elif action_type == "destroy":
                target = action.get("target")
                if target:
                    self.print_card_play(player, target, "destroyed")
                    if target in self.player_battlefield:
                        self.player_battlefield.remove(target)
                        self.player_graveyard.append(target)
                    elif target in self.opponent_battlefield:
                        self.opponent_battlefield.remove(target)
                        self.opponent_graveyard.append(target)
                else:
                    self.print_card_play(player, card, "destroyed")
                    if player == "You":
                        if card in self.player_battlefield:
                            self.player_battlefield.remove(card)
                            self.player_graveyard.append(card)
                    else:
                        if card in self.opponent_battlefield:
                            self.opponent_battlefield.remove(card)
                            self.opponent_graveyard.append(card)
            
            self.print_game_state()
            time.sleep(0.5)
        
        self.turn += 1
        print()

    def run_simulation(self):
        """Run a complete game simulation."""
        self.print_header()
        
        # Initial hands
        self.player_hand = [
            "Lightning Bolt",
            "Mountain",
            "Mountain",
            "Shock",
            "Goblin Guide",
            "Monastery Swiftspear",
            "Eidolon of the Great Revel"
        ]
        
        self.opponent_hand = [
            "Island",
            "Island",
            "Counterspell",
            "Snapcaster Mage",
            "Cryptic Command",
            "Serum Visions",
            "Opt"
        ]
        
        # Turn 1 - You
        self.simulate_turn("You", [
            {"type": "play", "card": "Mountain"},
            {"type": "play", "card": "Goblin Guide"}
        ])
        
        # Turn 1 - Opponent
        self.simulate_turn("Opponent", [
            {"type": "draw", "card": "Lightning Bolt"},
            {"type": "play", "card": "Island"},
            {"type": "play", "card": "Opt"}
        ])
        
        # Turn 2 - You
        self.simulate_turn("You", [
            {"type": "draw", "card": "Lightning Bolt"},
            {"type": "play", "card": "Mountain"},
            {"type": "play", "card": "Monastery Swiftspear"},
            {"type": "attack", "card": "Goblin Guide"}
        ])
        
        # Turn 2 - Opponent
        self.simulate_turn("Opponent", [
            {"type": "draw", "card": "Jace, the Mind Sculptor"},
            {"type": "play", "card": "Island"},
            {"type": "play", "card": "Snapcaster Mage"}
        ])
        
        # Turn 3 - You
        self.simulate_turn("You", [
            {"type": "draw", "card": "Mountain"},
            {"type": "play", "card": "Mountain"},
            {"type": "play", "card": "Eidolon of the Great Revel"},
            {"type": "attack", "card": "Goblin Guide"},
            {"type": "attack", "card": "Monastery Swiftspear"}
        ])
        
        # Turn 3 - Opponent
        self.simulate_turn("Opponent", [
            {"type": "draw", "card": "Force of Will"},
            {"type": "play", "card": "Island"},
            {"type": "play", "card": "Counterspell"},
            {"type": "attack", "card": "Snapcaster Mage"}
        ])
        
        # Turn 4 - You
        self.simulate_turn("You", [
            {"type": "draw", "card": "Lava Spike"},
            {"type": "play", "card": "Shock"},
            {"type": "destroy", "card": "Shock", "target": "Snapcaster Mage"},
            {"type": "attack", "card": "Goblin Guide"},
            {"type": "attack", "card": "Monastery Swiftspear"},
            {"type": "attack", "card": "Eidolon of the Great Revel"}
        ])
        
        # Final summary
        print("=" * 80)
        print("Game Summary")
        print("=" * 80)
        print(f"\nYour cards played: {len(self.player_graveyard) + len(self.player_battlefield)}")
        print(f"Opponent cards played: {len(self.opponent_graveyard) + len(self.opponent_battlefield)}")
        print(f"\nCards in graveyard:")
        print(f"  You: {', '.join(self.player_graveyard) if self.player_graveyard else '(none)'}")
        print(f"  Opponent: {', '.join(self.opponent_graveyard) if self.opponent_graveyard else '(none)'}")
        print("=" * 80)


if __name__ == "__main__":
    simulator = GameSimulator()
    simulator.run_simulation()

