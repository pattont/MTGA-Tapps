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

# Deck LLM (identify opponent deck archetype at game end)
# DECK_LLM_PROVIDER: Gemini | OpenAI | Claude (default: Gemini).
DECK_LLM_ENABLED = True
# Model per provider (optional; defaults: gemini-2.0-flash, gpt-4o-mini, claude-3-5-haiku)
DECK_LLM_PROVIDER = 'Gemini'
#DECK_LLM_OPENAI_MODEL = 'gpt-5-mini'
DECK_LLM_GEMINI_MODEL = 'gemini-2.0-flash'   # or e.g. gemini-1.5-flash
#DECK_LLM_CLAUDE_MODEL = 'claude-3-5-haiku-20241022'

GEMINI_API_KEY = ''
# CHATGPT_API_KEY = ''
# CLAUDE_API_KEY = ''