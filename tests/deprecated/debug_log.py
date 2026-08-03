#!/usr/bin/env python3
# DEPRECATED (2026-08): early-development debug relic, kept for reference only.
# Not maintained and likely broken — see tests/deprecated/README.md.
"""Debug script to see what's in the MTGA log file."""

import sys
from pathlib import Path
from src.mtga_tracker.log_parser import MTGALogParser

def main():
    try:
        parser = MTGALogParser()
        print(f"Log file: {parser.log_path}")
        print(f"File exists: {Path(parser.log_path).exists()}")
        print(f"File size: {Path(parser.log_path).stat().st_size} bytes")
        print("\n" + "="*80)
        print("Reading last 20 lines from log file:")
        print("="*80 + "\n")
        
        # Read last 20 lines
        with open(parser.log_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            for line in lines[-20:]:
                line = line.rstrip()
                if line:
                    print(f"Line: {line[:200]}...")
                    
                    # Try to parse JSON
                    json_data = parser.parse_json_from_line(line)
                    if json_data:
                        print(f"  ✓ Contains JSON with keys: {list(json_data.keys())[:5]}")
                        
                        # Check for game state messages
                        if "greToClientEvent" in json_data:
                            print(f"  ✓ Contains greToClientEvent!")
                            gre_event = json_data["greToClientEvent"]
                            if "greToClientMessages" in gre_event:
                                for msg in gre_event["greToClientMessages"]:
                                    msg_type = msg.get("type", "unknown")
                                    print(f"    - Message type: {msg_type}")
                    
                    # Check for card-related patterns
                    if any(term in line.lower() for term in ["card", "cast", "play", "zone", "grpid"]):
                        print(f"  ⚠ Contains card-related terms")
                    
                    print()
        
        print("\n" + "="*80)
        print("Testing real-time reading:")
        print("="*80 + "\n")
        
        parser.reset_position()
        print("Waiting for new log entries (10 seconds)...")
        import time
        start_time = time.time()
        lines_read = 0
        
        while time.time() - start_time < 10:
            for line in parser.read_new_lines():
                lines_read += 1
                print(f"[{lines_read}] New line: {line[:150]}...")
                
                # Try to extract events
                event = parser.extract_card_events(line)
                if event:
                    print(f"  ✓ Card event detected: {event}")
                
                if lines_read >= 5:
                    break
            
            if lines_read >= 5:
                break
            time.sleep(0.5)
        
        if lines_read == 0:
            print("⚠ No new lines detected. Make sure MTGA is running and you're in a game.")
        else:
            print(f"\n✓ Read {lines_read} new lines")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

