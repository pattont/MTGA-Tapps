# Troubleshooting Guide

## Player vs Opponent Showing Backwards

**Symptoms:**
- When you play a card, it shows as "Opponent"
- When opponent plays a card, it shows as "You"

**Solution:**
The tracker now auto-detects which seat ID you are. This should happen automatically at startup.

To verify seat detection:
```bash
python debug_seats.py
```

This will show:
- Your detected seat ID
- Opponent's seat ID
- Player data from game state
- Card play examples with seat info

**If detection fails:**
1. Make sure you've played at least one match in MTGA since opening it
2. Restart the tracker
3. Start a new match (seat assignment happens at match start)

## Life Totals Not Tracking

**Symptoms:**
- Life totals don't change during the game
- Life shown as 20-20 throughout

**Possible Causes:**

1. **Seat ID not detected** - See above section
2. **Not in an active match** - Life tracking only works during matches
3. **Spectating** - Life tracking may not work when spectating

**Debug Steps:**

Run the debug script while in an active game:
```bash
python debug_seats.py
```

Look for:
- "✓ Found player data structure" - Shows life totals are being read
- Life values for each seat
- Which seat is marked as YOU vs OPPONENT

## Cards Not Showing

**Symptoms:**
- No cards displayed when playing
- Only turn announcements show

**Possible Causes:**

1. **Tracker started mid-match** - Start tracker before the match begins
2. **No card events in log** - Some game modes may not log events
3. **Log file location wrong** - Verify log path

**Debug Steps:**

Check if events are being logged:
```bash
python debug_log.py
```

This will show:
- Recent log entries
- Whether JSON is being parsed
- Card-related events detected

## Card Names Show as "Unknown Card (ID)"

**Symptoms:**
- Cards display as `Unknown Card (12345)` instead of real names

**Causes:**
- Card ID not in Scryfall database (new card)
- Network issue preventing Scryfall API calls
- API rate limiting

**Solutions:**

1. **Check internet connection** - Scryfall API requires network access
2. **Wait a moment** - First lookup takes time, then cached
3. **Check cache** - Look at `data/card_cache.json`

To clear cache and retry:
```bash
rm data/card_cache.json
```

## Performance Issues

**Symptoms:**
- Tracker is slow
- High CPU usage
- Delayed card announcements

**Solutions:**

1. **Large log file** - MTGA logs can get huge over time
   - MTGA automatically rotates logs, but you can manually delete old ones
   - Location: Same as Player.log

2. **Too many API calls** - Should only happen on first run
   - Check that cache is working: `ls -lh data/card_cache.json`
   - Cache should grow over time

3. **Slow disk I/O** - Check disk space
   ```bash
   df -h
   ```

## Nothing Happens

**Symptoms:**
- Tracker starts but shows nothing
- No events detected

**Debug Checklist:**

1. **Is MTGA running?**
   ```bash
   # Check if log file exists and is being written to
   ls -lh ~/Library/Logs/Wizards\ Of\ The\ Coast/MTGA/Player.log  # macOS
   ```

2. **Is tracker monitoring the right file?**
   - Check the path shown when tracker starts
   - Verify it matches your MTGA log location

3. **Are you in an active game?**
   - Tracker only shows events during matches
   - Main menu / deck building won't generate card events

4. **Try the debug script:**
   ```bash
   python debug_log.py
   ```
   This will wait 10 seconds for new log entries.
   Play a card in MTGA during this time to test.

## Advanced: Manual Seat Configuration

If auto-detection consistently fails, you can manually set your seat ID:

Edit `src/mtga_tracker/tracker.py` and find the `GameState.__init__()` method.
Change:
```python
self.player_seat_id: Optional[int] = None
self.opponent_seat_id: Optional[int] = None
```

To (use your actual seat IDs from debug_seats.py):
```python
self.player_seat_id: Optional[int] = 1  # or 2
self.opponent_seat_id: Optional[int] = 2  # or 1
```

## Getting More Help

If you're still having issues:

1. Run all debug scripts and save output
2. Check the CHANGELOG.md for known issues
3. Open an issue on GitHub with:
   - Debug script output
   - What you expected to see
   - What actually happened
   - Your OS (macOS/Windows)
