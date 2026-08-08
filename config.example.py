"""Example configuration file for MTGA Tracker.

Copy this to config.py and modify as needed.
"""

# MTGA log file path (leave as None for auto-detection)
LOG_PATH = None

# Folder containing Raw_CardDatabase_*.mtga (optional override).
# Default on macOS: ~/Library/Application Support/com.wizards.mtga/Downloads/RAW
# Set this to override, e.g. if the file lives elsewhere on your machine.
MTGA_DATA_DIR = None

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

# Desktop window settings live in data/settings.json when running from source,
# or in the installed app's data folder. Use "Open Data Folder" from the menu bar.

# Database settings for future features
DB_PATH = 'data/mtga_tracker.db'
SAVE_HISTORY = True

# Match tracking settings
AUTO_DETECT_MATCH_START = True
AUTO_DETECT_MATCH_END = True
SAVE_MATCH_DATA = True

# AI deck identification (opponent archetype naming) is configured from the
# menu bar: Settings… — saved to settings.json at the top level of this folder.
