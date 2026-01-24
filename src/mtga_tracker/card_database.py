"""Card database for resolving MTGA card IDs to names.

Uses Scryfall API with MTGJSON as backup, with local caching to avoid excessive API calls.
"""

import json
import time
from pathlib import Path
from typing import Optional, Dict
import urllib.request
import urllib.error


class CardDatabase:
    """Resolves MTGA card IDs (grpId) to card names using Scryfall API with fallback.
    
    Tries multiple methods in order:
    1. Scryfall direct lookup: /cards/arena/{grpId}
    2. Scryfall search: /cards/search?q=arena:{grpId}
    
    Uses local caching to avoid excessive API calls.
    """

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
        self.mtgjson_cache: Dict[int, str] = {}  # MTGJSON card mappings
        self.last_api_call = 0
        self.api_delay = 0.1  # Scryfall rate limit: 10 calls/second max

        self._load_cache()
        
        # Check and download MTGJSON database if it doesn't exist
        mtgjson_path = self.cache_path.parent / "mtgjson_allprintings.json"
        if not mtgjson_path.exists():
            print("\n📥 MTGJSON database not found. Downloading for better card coverage...")
            print("   (This is a one-time download, ~100MB)")
            if self.download_mtgjson_database():
                print("   ✓ Download complete!")
            else:
                print("   ⚠ Download failed - will use Scryfall API only")
        
        # Load MTGJSON database if it exists
        self.mtgjson_cache = self._load_mtgjson_database()

    def _load_cache(self):
        """Load the card cache from disk."""
        if self.cache_path.exists():
            try:
                with open(self.cache_path, "r") as f:
                    data = json.load(f)
                    # Convert string keys back to integers
                    # Filter out failed lookups (Unknown Card, Card #) - only keep successful lookups
                    self.cache = {
                        int(k): v for k, v in data.items()
                        if not v.startswith("Unknown Card") and not v.startswith("Card #")
                    }
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
        # #region agent log
        import json as json_module
        import os
        try:
            with open(os.path.join(os.path.dirname(__file__), '..', '..', '.cursor', 'debug.log'), 'a') as f:
                f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"S","location":"card_database.py:67","message":"get_card_name called","data":{"grp_id":grp_id,"in_cache":grp_id in self.cache},"timestamp":__import__('time').time()*1000})+'\n')
        except: pass
        # #endregion
        
        # Check cache first - but retry if it was previously unknown
        if grp_id in self.cache:
            cached = self.cache[grp_id]
            # If we have a real name, return it
            if not cached.startswith("Unknown Card") and not cached.startswith("Card #"):
                return cached
            # REMOVED: Don't cache failed lookups in memory - allow retry every time
            # This allows cards to be retried if Scryfall adds them later
            # Just remove from cache and continue to API lookup
            del self.cache[grp_id]

        # Check MTGJSON database first (local, fast, comprehensive MTGA coverage)
        if grp_id in self.mtgjson_cache:
            card_name = self.mtgjson_cache[grp_id]
            # Cache it for faster future lookups
            self.cache[grp_id] = card_name
            self._save_cache()
            return card_name

        # Try Scryfall API (online source)
        card_name = self._fetch_from_scryfall(grp_id)

        # If Scryfall fails, try MTGJSON as backup
        if not card_name:
            card_name = self._fetch_from_mtgjson(grp_id)

        if card_name:
            self.cache[grp_id] = card_name
            self._save_cache()
            # #region agent log
            try:
                with open(os.path.join(os.path.dirname(__file__), '..', '..', '.cursor', 'debug.log'), 'a') as f:
                    f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"S","location":"card_database.py:88","message":"Card name fetched successfully","data":{"grp_id":grp_id,"card_name":card_name},"timestamp":__import__('time').time()*1000})+'\n')
            except: pass
            # #endregion
            return card_name

        # Return the grpId as the name if all APIs failed
        # DON'T cache failed lookups at all - not in memory, not on disk
        # This allows retrying every time in case Scryfall adds the card later
        fallback = f"Card #{grp_id}"
        # #region agent log
        try:
            with open(os.path.join(os.path.dirname(__file__), '..', '..', '.cursor', 'debug.log'), 'a') as f:
                f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"S","location":"card_database.py:97","message":"Card name fetch failed - all APIs failed, not caching","data":{"grp_id":grp_id,"fallback":fallback},"timestamp":__import__('time').time()*1000})+'\n')
        except: pass
        # #endregion
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

        # #region agent log
        import json as json_module
        import os
        try:
            with open(os.path.join(os.path.dirname(__file__), '..', '..', '.cursor', 'debug.log'), 'a') as f:
                f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"Y","location":"card_database.py:115","message":"Fetching from Scryfall","data":{"grp_id":grp_id,"url":url},"timestamp":__import__('time').time()*1000})+'\n')
        except: pass
        # #endregion

        try:
            # Create request with User-Agent header (Scryfall requests this)
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'MTGA-Tracker/1.0')
            req.add_header('Accept', 'application/json')

            with urllib.request.urlopen(req, timeout=10) as response:
                self.last_api_call = time.time()
                data = json.loads(response.read())
                card_name = data.get("name", None)
                # #region agent log
                try:
                    with open(os.path.join(os.path.dirname(__file__), '..', '..', '.cursor', 'debug.log'), 'a') as f:
                        f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"Y","location":"card_database.py:130","message":"Scryfall API success","data":{"grp_id":grp_id,"card_name":card_name,"status_code":response.getcode()},"timestamp":__import__('time').time()*1000})+'\n')
                except: pass
                # #endregion
                return card_name
        except urllib.error.HTTPError as e:
            # #region agent log
            try:
                with open(os.path.join(os.path.dirname(__file__), '..', '..', '.cursor', 'debug.log'), 'a') as f:
                    f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"Y","location":"card_database.py:137","message":"Scryfall API HTTP error","data":{"grp_id":grp_id,"status_code":e.code,"reason":e.reason},"timestamp":__import__('time').time()*1000})+'\n')
            except: pass
            # #endregion
            if e.code == 404:
                # Card not found in Scryfall - might be a new or special card
                return None
            else:
                # Don't print errors to avoid cluttering output
                return None
        except Exception as e:
            # #region agent log
            try:
                with open(os.path.join(os.path.dirname(__file__), '..', '..', '.cursor', 'debug.log'), 'a') as f:
                    f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"Y","location":"card_database.py:147","message":"Scryfall API exception","data":{"grp_id":grp_id,"error_type":type(e).__name__,"error_message":str(e)},"timestamp":__import__('time').time()*1000})+'\n')
            except: pass
            # #endregion
            # Network errors, timeouts, etc - fail silently
            return None

    def _fetch_from_mtgjson(self, grp_id: int) -> Optional[str]:
        """Fetch card name from MTGJSON API (backup to Scryfall).

        Args:
            grp_id: The MTGA card group ID.

        Returns:
            Card name if found, None otherwise.
        """
        # Rate limiting - use same delay as Scryfall
        current_time = time.time()
        time_since_last_call = current_time - self.last_api_call
        if time_since_last_call < self.api_delay:
            time.sleep(self.api_delay - time_since_last_call)

        # MTGJSON doesn't have a direct grpId REST API
        # Try Scryfall's search endpoint as an alternative fallback
        # Search for cards with this arena ID
        url = f"https://api.scryfall.com/cards/search?q=arena%3A{grp_id}"
        
        # #region agent log
        import json as json_module
        import os
        try:
            with open(os.path.join(os.path.dirname(__file__), '..', '..', '.cursor', 'debug.log'), 'a') as f:
                f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"Z","location":"card_database.py:190","message":"Trying Scryfall search as fallback","data":{"grp_id":grp_id,"url":url},"timestamp":__import__('time').time()*1000})+'\n')
        except: pass
        # #endregion

        try:
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'MTGA-Tracker/1.0')
            req.add_header('Accept', 'application/json')

            with urllib.request.urlopen(req, timeout=10) as response:
                self.last_api_call = time.time()
                data = json.loads(response.read())
                
                # Scryfall search returns a list of cards in 'data' field
                if data.get("data") and len(data["data"]) > 0:
                    card_name = data["data"][0].get("name")
                    # #region agent log
                    try:
                        with open(os.path.join(os.path.dirname(__file__), '..', '..', '.cursor', 'debug.log'), 'a') as f:
                            f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"Z","location":"card_database.py:205","message":"Scryfall search success","data":{"grp_id":grp_id,"card_name":card_name},"timestamp":__import__('time').time()*1000})+'\n')
                    except: pass
                    # #endregion
                    return card_name
                return None
        except urllib.error.HTTPError as e:
            # #region agent log
            try:
                with open(os.path.join(os.path.dirname(__file__), '..', '..', '.cursor', 'debug.log'), 'a') as f:
                    f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"Z","location":"card_database.py:214","message":"Scryfall search HTTP error","data":{"grp_id":grp_id,"status_code":e.code,"reason":e.reason},"timestamp":__import__('time').time()*1000})+'\n')
            except: pass
            # #endregion
            return None
        except Exception as e:
            # #region agent log
            try:
                with open(os.path.join(os.path.dirname(__file__), '..', '..', '.cursor', 'debug.log'), 'a') as f:
                    f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"Z","location":"card_database.py:222","message":"Scryfall search exception","data":{"grp_id":grp_id,"error_type":type(e).__name__,"error_message":str(e)},"timestamp":__import__('time').time()*1000})+'\n')
            except: pass
            # #endregion
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
    
    def download_mtgjson_database(self, force: bool = False) -> bool:
        """Download MTGJSON AllPrintings database for better MTGA card coverage.
        
        This downloads the full MTGJSON database which includes MTGA card IDs.
        The file is large (~100MB+) but provides comprehensive card coverage.
        
        Args:
            force: If True, re-download even if file exists.
            
        Returns:
            True if download successful, False otherwise.
        """
        mtgjson_path = self.cache_path.parent / "mtgjson_allprintings.json"
        
        if mtgjson_path.exists() and not force:
            print(f"MTGJSON database already exists at {mtgjson_path}")
            return True
        
        print("Downloading MTGJSON AllPrintings database...")
        print("This may take a few minutes (file is ~100MB+)...")
        
        url = "https://mtgjson.com/api/v5/AllPrintings.json"
        
        try:
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'MTGA-Tracker/1.0')
            
            with urllib.request.urlopen(req, timeout=300) as response:
                total_size = int(response.headers.get('Content-Length', 0))
                downloaded = 0
                
                with open(mtgjson_path, 'wb') as f:
                    while True:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            percent = (downloaded / total_size) * 100
                            print(f"\rDownloaded: {percent:.1f}%", end='', flush=True)
                
                print(f"\n✓ MTGJSON database downloaded to {mtgjson_path}")
                return True
        except Exception as e:
            print(f"\n✗ Failed to download MTGJSON database: {e}")
            return False
    
    def _load_mtgjson_database(self) -> Dict[int, str]:
        """Load MTGJSON database and extract MTGA card mappings.
        
        Uses a pre-processed cache file for fast loading. If cache doesn't exist
        or is older than the MTGJSON file, rebuilds it.
        
        Returns:
            Dictionary mapping grpId to card name.
        """
        mtgjson_path = self.cache_path.parent / "mtgjson_allprintings.json"
        cache_path = self.cache_path.parent / "mtgjson_cache.json"
        
        if not mtgjson_path.exists():
            return {}
        
        # Check if we have a cached version that's up to date
        if cache_path.exists():
            mtgjson_mtime = mtgjson_path.stat().st_mtime
            cache_mtime = cache_path.stat().st_mtime
            
            # If cache is newer than MTGJSON file, use the cache
            if cache_mtime >= mtgjson_mtime:
                try:
                    print("Loading MTGJSON cache (fast)...")
                    with open(cache_path, 'r', encoding='utf-8') as f:
                        card_map = {int(k): v for k, v in json.load(f).items()}
                    print(f"✓ Loaded {len(card_map)} MTGA cards from cache")
                    return card_map
                except Exception as e:
                    print(f"⚠ Cache load failed, rebuilding: {e}")
        
        # Need to rebuild cache from full MTGJSON file
        print("Loading MTGJSON database (this may take a few seconds)...")
        card_map = {}
        
        try:
            with open(mtgjson_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # MTGJSON structure: data -> set_code -> cards -> [card objects]
            # Each card has "identifiers" -> "mtgArenaId" (grpId)
            count = 0
            for set_code, set_data in data.get("data", {}).items():
                cards = set_data.get("cards", [])
                for card in cards:
                    identifiers = card.get("identifiers", {})
                    arena_id = identifiers.get("mtgArenaId")
                    card_name = card.get("name")
                    
                    if arena_id and card_name:
                        try:
                            grp_id = int(arena_id)
                            card_map[grp_id] = card_name
                            count += 1
                        except (ValueError, TypeError):
                            continue
            
            # Save the processed cache for next time
            try:
                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump(card_map, f, indent=2)
                print(f"✓ Processed and cached {count} MTGA cards")
            except Exception as e:
                print(f"⚠ Failed to save cache: {e}")
            
            print(f"✓ Loaded {count} MTGA cards from MTGJSON database")
            return card_map
        except Exception as e:
            print(f"✗ Failed to load MTGJSON database: {e}")
            return {}