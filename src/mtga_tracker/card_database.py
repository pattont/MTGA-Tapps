"""Card database for resolving MTGA card IDs to names.

Uses Scryfall API with local caching to avoid excessive API calls.
"""

import json
import time
from pathlib import Path
from typing import Optional, Dict
import urllib.request
import urllib.error


class CardDatabase:
    """Resolves MTGA card IDs (grpId) to card names using Scryfall API."""

    def __init__(self, cache_path: Optional[str] = None):
        """Initialize the card database.

        Args:
            cache_path: Path to cache file. Defaults to data/card_cache.json
        """
        if cache_path is None:
            cache_path = Path(__file__).parent.parent.parent / "data" / "card_cache.json"
        else:
            cache_path = Path(cache_path)

        self.cache_path = cache_path
        self.cache: Dict[int, str] = {}
        self.last_api_call = 0
        self.api_delay = 0.1  # Scryfall rate limit: 10 calls/second max

        self._load_cache()

    def _load_cache(self):
        """Load the card cache from disk."""
        if self.cache_path.exists():
            try:
                with open(self.cache_path, "r") as f:
                    data = json.load(f)
                    # Convert string keys back to integers
                    self.cache = {int(k): v for k, v in data.items()}
                print(f"Loaded {len(self.cache)} cards from cache")
            except Exception as e:
                print(f"Warning: Could not load cache: {e}")
                self.cache = {}

    def _save_cache(self):
        """Save the card cache to disk."""
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_path, "w") as f:
                json.dump(self.cache, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save cache: {e}")

    def get_card_name(self, grp_id: int) -> str:
        """Get the card name for a given MTGA grpId.

        Args:
            grp_id: The MTGA card group ID.

        Returns:
            Card name, or "Unknown Card (ID: grp_id)" if not found.
        """
        # Check cache first - but retry if it was previously unknown
        if grp_id in self.cache:
            cached = self.cache[grp_id]
            # If we have a real name, return it
            if not cached.startswith("Unknown Card") and not cached.startswith("Card #"):
                return cached
            # Don't retry during this session to avoid spamming API
            return cached

        # Fetch from Scryfall API
        card_name = self._fetch_from_scryfall(grp_id)

        if card_name:
            self.cache[grp_id] = card_name
            self._save_cache()
            return card_name

        # Return the grpId as the name if fetch failed
        # Cache in memory only so it can be retried next session
        fallback = f"Card #{grp_id}"
        self.cache[grp_id] = fallback
        return fallback

    def _fetch_from_scryfall(self, grp_id: int) -> Optional[str]:
        """Fetch card name from Scryfall API.

        Args:
            grp_id: The MTGA card group ID.

        Returns:
            Card name if found, None otherwise.
        """
        # Rate limiting
        current_time = time.time()
        time_since_last_call = current_time - self.last_api_call
        if time_since_last_call < self.api_delay:
            time.sleep(self.api_delay - time_since_last_call)

        url = f"https://api.scryfall.com/cards/arena/{grp_id}"

        try:
            # Create request with User-Agent header (Scryfall requests this)
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'MTGA-Tracker/1.0')
            req.add_header('Accept', 'application/json')

            with urllib.request.urlopen(req, timeout=10) as response:
                self.last_api_call = time.time()
                data = json.loads(response.read())
                return data.get("name", None)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # Card not found in Scryfall - might be a new or special card
                return None
            else:
                # Don't print errors to avoid cluttering output
                return None
        except Exception:
            # Network errors, timeouts, etc - fail silently
            return None

    def preload_cards(self, grp_ids: list[int]):
        """Preload multiple cards to minimize API calls during gameplay.

        Args:
            grp_ids: List of MTGA card group IDs to preload.
        """
        missing_ids = [gid for gid in grp_ids if gid not in self.cache]

        if not missing_ids:
            return

        print(f"Preloading {len(missing_ids)} cards...")
        for grp_id in missing_ids:
            self.get_card_name(grp_id)
        print("Preload complete!")

    def clear_cache(self):
        """Clear the card cache."""
        self.cache = {}
        if self.cache_path.exists():
            self.cache_path.unlink()
