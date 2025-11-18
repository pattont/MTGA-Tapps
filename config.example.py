"""Example configuration file for MTGA Tracker.

Copy this to config.py and modify as needed.
"""

# MTGA log file path (leave as None for auto-detection)
LOG_PATH = None

# Polling interval in seconds (how often to check for new log entries)
POLL_INTERVAL = 1.0

# Enable verbose logging
VERBOSE = False

# Console output format
# Options: 'simple', 'detailed', 'json'
OUTPUT_FORMAT = 'simple'

# Track specific card types only (leave empty to track all)
# Example: ['Creature', 'Instant', 'Sorcery']
TRACKED_CARD_TYPES = []

# Future GUI settings
GUI_ENABLED = False
GUI_THEME = 'dark'  # 'dark' or 'light'
GUI_POSITION = (100, 100)  # (x, y) position on screen
GUI_SIZE = (800, 600)  # (width, height)

# Database settings for future features
DB_PATH = 'data/mtga_tracker.db'
SAVE_HISTORY = True

# Match tracking settings
AUTO_DETECT_MATCH_START = True
AUTO_DETECT_MATCH_END = True
SAVE_MATCH_DATA = True
