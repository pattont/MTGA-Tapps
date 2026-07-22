"""Card tracking module.

Tracks cards played by the player and opponents.
"""

from datetime import datetime
import sys
from typing import Any, Dict, List, Optional, TextIO
from .log_parser import MTGALogParser
from .card_database import CardDatabase
from .paths import DATA_DIR
from .analytics import AnalyticsStore
from .tracker_analytics import TrackerAnalyticsMixin
from .tracker_combat import TrackerCombatMixin
from .tracker_diagnostics import TrackerDiagnosticsMixin
from .tracker_events import TrackerEventsMixin
from .tracker_lifecycle import TrackerLifecycleMixin
from .tracker_opening_deck import TrackerOpeningDeckMixin
from .tracker_rendering import TrackerRenderingMixin
from .tracker_runtime import TrackerRuntimeMixin
from .tracker_state_lookup import TrackerStateLookupMixin
from .tracker_summary import TrackerSummaryMixin
from .tracker_stack import TrackerStackMixin
from .tracker_zone_transfers import TrackerZoneTransferMixin
from .rendering import ANSI_RESET, ANSI_STYLES
from .state import CardEvent, GameState


class CardTracker(
    TrackerAnalyticsMixin,
    TrackerDiagnosticsMixin,
    TrackerOpeningDeckMixin,
    TrackerLifecycleMixin,
    TrackerEventsMixin,
    TrackerStateLookupMixin,
    TrackerRenderingMixin,
    TrackerRuntimeMixin,
    TrackerCombatMixin,
    TrackerSummaryMixin,
    TrackerStackMixin,
    TrackerZoneTransferMixin,
):
    """Tracks cards played during MTGA matches."""

    def __init__(
        self,
        log_parser: Optional[MTGALogParser] = None,
        card_db: Optional[CardDatabase] = None,
        mtga_data_dir: Optional[str] = None,
        output_stream: Optional[TextIO] = None,
    ):
        """Initialize the card tracker.

        Args:
            log_parser: Optional MTGALogParser instance. If not provided, creates one.
            card_db: Optional CardDatabase instance. If not provided, creates one.
            mtga_data_dir: Optional path to MTGA data root for local card DB (Raw_CardDatabase_*.mtga).
            output_stream: Optional destination for the live tracker log. Defaults to stdout.
        """
        self.parser = log_parser or MTGALogParser()
        self.output_stream = output_stream or sys.stdout
        self.card_db = card_db or CardDatabase(
            log_path=self.parser.log_path,
            mtga_data_dir=mtga_data_dir,
        )
        self.game_state = GameState()
        self.player_cards: List[CardEvent] = []
        self.opponent_cards: List[CardEvent] = []
        self.running = False
        self.match_games: List[Dict] = []  # Track games in the match for summary
        self.waiting_for_next_game: bool = False  # True if launched mid-game, waiting for next game
        self._pending_game_summary: bool = (
            False  # Defer summary until end of line batch (so ConcedeReq can set winner)
        )
        self.session_start_time = datetime.now()
        self.session_games_played = 0
        self.session_wins = 0
        self.session_losses = 0
        self.session_draws = 0
        self.session_unknown = 0
        self.session_player_cards_played = 0
        self.session_opponent_cards_played = 0
        self.session_total_mulligans = 0
        self.session_game_runtime_seconds = 0
        self.session_player_went_first = 0
        self.session_opponent_went_first = 0
        self.session_first_unknown = 0
        self.session_deck_records: Dict[str, Dict[str, Any]] = {}
        self.session_id = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        self._session_stats_recorded_this_game = False
        self._deck_candidates: Dict[str, Dict[str, Any]] = {}
        self._active_deck_candidate_key: Optional[str] = None
        self._metadata_backfilled = False
        self._format_from_backfill = False
        self._pending_event_format: Optional[str] = None
        self._parsing_backfilled_metadata = False
        self._current_event_time: Optional[datetime] = None
        self._require_explicit_game_start: bool = False
        self._ansi_reset = ANSI_RESET
        self._ansi_styles: Dict[str, str] = ANSI_STYLES.copy()
        self.use_colors = self._should_use_colors()
        self._console_db_path = DATA_DIR / "mtga_tracker.sqlite3"
        self._diagnostic_text_path = DATA_DIR / "mtga_tracker_unhandled_annotations.log"
        self.analytics = AnalyticsStore(self._console_db_path)

    def _now(self) -> datetime:
        """Return the current source event time when available."""
        return getattr(self, "_current_event_time", None) or datetime.now()

    def get_player_cards(self) -> List[CardEvent]:
        """Get list of cards played by the player."""
        return self.player_cards.copy()

    def get_opponent_cards(self) -> List[CardEvent]:
        """Get list of cards played by opponents."""
        return self.opponent_cards.copy()

    def clear_history(self):
        """Clear card history."""
        self.player_cards.clear()
        self.opponent_cards.clear()
