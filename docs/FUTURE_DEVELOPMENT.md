# Future Development

This document outlines considerations and recommendations for future development of MTGA Tracker.

## UI Framework Options

### Option 1: PyQt6/PySide6 (Recommended)

**Pros:**
- Native Python integration
- Cross-platform (macOS, Windows, Linux)
- Professional, native-looking UI
- Excellent documentation and community
- Built-in widgets for complex UIs
- Good performance
- Can create overlay windows (important for game trackers)

**Cons:**
- Larger application size
- Steeper learning curve than web technologies
- GPL/LGPL licensing (PySide6 is LGPL, more permissive)

**Installation:**
```bash
pip install PyQt6 pyqt6-tools
```

### Option 2: Web-based (FastAPI/Flask + React/Vue)

**Pros:**
- Modern, familiar web technologies
- Easy to create beautiful UIs
- Can be accessed from any device (local network)
- Easier to find developers familiar with web tech
- Great for data visualization (Chart.js, D3.js)

**Cons:**
- Requires running a local server
- More complex architecture (frontend + backend)
- Harder to create overlay windows
- Potentially slower than native

**Tech Stack:**
```
Backend: FastAPI (Python)
Frontend: React or Vue
Communication: WebSockets for real-time updates
```

### Option 3: Tkinter

**Pros:**
- Built-in with Python (no extra dependencies)
- Simple to learn
- Cross-platform

**Cons:**
- Limited styling options
- Looks dated
- Less suitable for complex UIs
- Not recommended for modern applications

### Option 4: Dear PyGui

**Pros:**
- Fast, GPU-accelerated
- Good for real-time data visualization
- Easy to learn
- Great performance

**Cons:**
- Less mature ecosystem
- Smaller community
- Limited widget selection

## Recommended Architecture

### Phase 1: Console MVP (Current)
```
User -> main.py -> CardTracker -> MTGALogParser -> Player.log
                      |
                      v
                  Console Output
```

### Phase 2: Add Data Persistence
```
User -> main.py -> CardTracker -> MTGALogParser -> Player.log
                      |
                      v
                  SQLite Database
                      |
                      v
                  Console Output
```

### Phase 3: Add GUI (PyQt6 Recommended)
```
Player.log -> MTGALogParser -> CardTracker (Core Logic)
                                    |
                    +---------------+---------------+
                    |                               |
                Database                         GUI (PyQt6)
                    |                               |
                    +--------> Statistics <---------+
                                Reports
                                Export
```

## Feature Roadmap

### MVP (Current Phase)
- [x] Log file parsing
- [x] Real-time monitoring
- [x] Console output for card plays
- [x] Basic player vs opponent tracking

### Phase 2: Enhanced Tracking
- [ ] Card name resolution (grpId -> card name via Scryfall API)
- [ ] Match start/end detection
- [ ] Game outcome tracking (win/loss)
- [ ] Deck recognition
- [ ] SQLite database for persistence

### Phase 3: Statistics & Analysis
- [ ] Win rate by deck
- [ ] Card play frequency
- [ ] Mana curve analysis
- [ ] Match history
- [ ] Export to CSV/JSON

### Phase 4: GUI Implementation
- [ ] Real-time card tracking display
- [ ] Match history browser
- [ ] Statistics dashboard
- [ ] Overlay mode (transparent window over MTGA)
- [ ] Deck builder integration
- [ ] Settings/configuration UI

### Phase 5: Advanced Features
- [ ] Draft tracking (17Lands style)
- [ ] Deck recommendations
- [ ] Meta analysis
- [ ] Cloud sync (optional)
- [ ] Mobile companion app

## Key Design Considerations

### 1. Separation of Concerns
Keep the core logic (log parsing, card tracking) separate from the UI. This allows:
- Easy testing
- Swapping out UI frameworks
- Running in headless mode
- API/library usage

### 2. Real-time Updates
The UI needs to update in real-time as cards are played. Consider:
- **PyQt6**: Use signals/slots for thread-safe updates
- **Web**: Use WebSockets for real-time communication
- Event-driven architecture

### 3. Overlay Mode
Many MTGA trackers use an overlay window. Requirements:
- Transparent background
- Always on top
- Click-through option
- Configurable position/size

**PyQt6 Example:**
```python
window.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
window.setAttribute(Qt.WA_TranslucentBackground)
```

### 4. Performance
- Log parsing should be efficient (don't re-parse entire file)
- UI updates should be throttled if needed
- Database queries should be optimized
- Consider using indexes for large datasets

### 5. Card Database
You'll need to map MTGA's internal card IDs to card names. Options:

**Option A: Scryfall API**
```python
import requests

def get_card_name(grp_id: int) -> str:
    url = f"https://api.scryfall.com/cards/arena/{grp_id}"
    response = requests.get(url)
    if response.ok:
        return response.json()["name"]
    return f"Unknown ({grp_id})"
```

**Option B: Local Database**
- Download card database from MTG JSON
- Store in SQLite
- Faster, no internet required
- Needs periodic updates

### 6. Cross-Platform Considerations

**File Paths:**
- Already handled in `log_parser.py`
- Use `pathlib.Path` for cross-platform compatibility

**UI Scaling:**
- Consider high-DPI displays
- PyQt6 handles this automatically with `QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)`

**Installer:**
- Use PyInstaller or cx_Freeze for distribution
- Create platform-specific installers (MSI for Windows, DMG for macOS)

## Database Schema (Future)

```sql
-- Matches table
CREATE TABLE matches (
    id INTEGER PRIMARY KEY,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    result TEXT,  -- 'win', 'loss', 'draw'
    opponent_deck_archetype TEXT,
    format TEXT   -- 'standard', 'historic', etc.
);

-- Cards played table
CREATE TABLE cards_played (
    id INTEGER PRIMARY KEY,
    match_id INTEGER,
    card_name TEXT,
    grp_id INTEGER,
    player TEXT,  -- 'player' or 'opponent'
    turn_number INTEGER,
    timestamp TIMESTAMP,
    FOREIGN KEY (match_id) REFERENCES matches(id)
);

-- Decks table
CREATE TABLE decks (
    id INTEGER PRIMARY KEY,
    name TEXT,
    format TEXT,
    created_at TIMESTAMP
);

-- Deck cards table
CREATE TABLE deck_cards (
    deck_id INTEGER,
    card_name TEXT,
    quantity INTEGER,
    FOREIGN KEY (deck_id) REFERENCES decks(id)
);
```

## Testing Strategy

1. **Unit Tests**: Test individual components (parser, tracker)
2. **Integration Tests**: Test component interactions
3. **Mock Data**: Create sample MTGA log files for testing
4. **UI Tests**: Use PyQt's testing framework or Selenium for web

## Deployment

### Development Mode
```bash
pip install -e .
mtga-tracker
```

### Production Build
```bash
pyinstaller --name "MTGA Tracker" \
            --windowed \
            --icon=icon.ico \
            --add-data "data:data" \
            src/mtga_tracker/main.py
```

## Next Steps

1. Implement card database integration
2. Add match detection
3. Create SQLite database layer
4. Build basic PyQt6 GUI
5. Add statistics module
6. Implement overlay mode
