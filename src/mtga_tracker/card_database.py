"""Card database for resolving MTGA card IDs to names.

Uses Scryfall API with MTGJSON as backup, with local caching to avoid excessive API calls.
Supports 17Lands CSV (17LandsCards.csv), Scryfall bulk file, and MTGJSON for offline lookups.
"""

import csv
import json
import time
import os
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
import urllib.request
import urllib.error
from .paths import DATA_DIR, get_mtga_raw_card_db_folders

try:
    import ijson
except ImportError:
    ijson = None  # type: ignore


class CardDatabase:
    """Resolves MTGA card IDs (grpId) to card names using Scryfall API with fallback.
    
    Tries multiple methods in order:
    1. Scryfall direct lookup: /cards/arena/{grpId}
    2. Scryfall search: /cards/search?q=arena:{grpId}
    
    Uses local caching to avoid excessive API calls.
    """

    def __init__(self, cache_path: Optional[str] = None, log_path: Optional[str] = None,
                 mtga_data_dir: Optional[str] = None):
        """Initialize the card database.

        Args:
            cache_path: Path to cache file. Defaults to data/card_cache.json
            log_path: Optional path to MTGA Player.log for extracting card names
            mtga_data_dir: Optional path to MTGA data root (for Raw_CardDatabase_*.mtga / data_cards_*.mtga)
        """
        if cache_path is None:
            cache_path = DATA_DIR / "card_cache.json"
        else:
            cache_path = Path(cache_path)

        self.cache_path = cache_path
        # Session-only in-memory cache: avoid re-querying the same card in one run (e.g. same deck)
        self.cache: Dict[int, str] = {}
        self.log_path = log_path
        self._mtga_data_dir = mtga_data_dir
        # Unused now (card names from local SQLite only); kept so other methods don't break if called
        self.lands17_cache: Dict[int, str] = {}
        self.mtgjson_cache: Dict[int, str] = {}
        self.scryfall_arena_index: Dict[int, str] = {}
        self.log_cache: Dict[int, str] = {}
        self.last_api_call = 0
        self.api_delay = 0.1
        # Local MTGA SQLite DB: path resolved on first lookup (no preload)
        self._mtga_db_path: Optional[Path] = None
        self._mtga_db_resolved: bool = False
        self._ability_text_cache: Dict[int, Dict[int, str]] = {}

    _17LANDS_CSV_URL = "https://17lands-public.s3.amazonaws.com/analysis_data/cards/cards.csv"

    def _ensure_17lands_csv(self) -> None:
        """Download 17Lands cards CSV on startup if missing or to refresh (~1.5MB).

        Writes to data/17LandsCards.csv. On download failure, any existing file is left
        unchanged. Uses urllib; no extra dependencies.
        """
        csv_path = self.cache_path.parent / "17LandsCards.csv"
        try:
            req = urllib.request.Request(self._17LANDS_CSV_URL)
            req.add_header("User-Agent", "MTGA-Tracker/1.0")
            with urllib.request.urlopen(req, timeout=60) as response:
                data = response.read()
            # Write atomically via temp file
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = csv_path.with_suffix(".csv.tmp")
            with open(tmp, "wb") as f:
                f.write(data)
            tmp.replace(csv_path)
        except Exception as e:
            if not csv_path.exists():
                print(f"⚠ Could not download 17Lands cards list: {e}")

    def _load_17lands_cards(self) -> None:
        """Load id -> name from 17LandsCards.csv in the data folder.

        CSV format: id,expansion,name,rarity,... — id is MTGA grpId, name is card name.
        Used right after card_cache for Arena coverage (17Lands often has arena_id where
        MTGJSON/Scryfall are missing).
        """
        csv_path = self.cache_path.parent / "17LandsCards.csv"
        if not csv_path.exists():
            return
        try:
            with open(csv_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                if "id" not in (reader.fieldnames or []) or "name" not in (reader.fieldnames or []):
                    return
                for row in reader:
                    id_str = row.get("id", "").strip()
                    name = (row.get("name") or "").strip()
                    if id_str and name:
                        try:
                            self.lands17_cache[int(id_str)] = name
                        except (ValueError, TypeError):
                            continue
            if self.lands17_cache:
                print(f"✓ Loaded {len(self.lands17_cache)} cards from 17LandsCards.csv")
        except Exception as e:
            print(f"Warning: Could not load 17LandsCards.csv: {e}")

    def _find_mtga_card_database_paths(self) -> List[tuple]:
        """Find Raw_CardDatabase_*.mtga in com.wizards.mtga/Downloads/RAW (or MTGA_DATA_DIR override)."""
        out = []
        for folder in get_mtga_raw_card_db_folders(self._mtga_data_dir):
            for p in folder.glob("Raw_CardDatabase_*.mtga"):
                if p.is_file() and not p.name.endswith(".mtga.dat"):
                    out.append((p, None))
        out.sort(key=lambda x: x[0].stat().st_mtime, reverse=True)
        return out

    def _resolve_mtga_db_path(self) -> Optional[Path]:
        """Resolve path to Raw_CardDatabase_*.mtga once; cache in self._mtga_db_path."""
        if self._mtga_db_resolved:
            if self._mtga_db_path and self._mtga_db_path.exists():
                return self._mtga_db_path
            # Arena can download/update Raw_CardDatabase after the tracker process starts.
            # A previous miss must not poison card-name resolution for the whole session.
        self._mtga_db_resolved = True
        paths = self._find_mtga_card_database_paths()
        if paths:
            self._mtga_db_path = paths[0][0]
            return self._mtga_db_path
        self._mtga_db_path = None
        return None

    def _query_mtga_local_db(self, grp_id: int) -> Optional[str]:
        """Look up card name for grp_id from local MTGA SQLite (Cards ⋈ Localizations_enUS). On-demand only."""
        import sqlite3
        db_path = self._resolve_mtga_db_path()
        if not db_path:
            return None
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            # Cards.TitleId = Localizations_enUS.LocId; get name for this GrpId
            cur.execute(
                'SELECT l."loc" FROM "Cards" c '
                'JOIN "Localizations_enUS" l ON c."TitleId" = l."LocId" '
                'WHERE c."GrpId" = ?',
                (grp_id,),
            )
            row = cur.fetchone()
            conn.close()
            if row and row[0]:
                return (row[0] or "").strip()
        except Exception:
            pass
        return None

    @staticmethod
    def _parse_ability_mapping(raw: Optional[str]) -> Dict[int, int]:
        """Parse MTGA AbilityIds/HiddenAbilityIds text into {abilityGrpId: localizationId}."""
        out: Dict[int, int] = {}
        if not isinstance(raw, str) or not raw.strip():
            return out
        for part in raw.split(","):
            if ":" not in part:
                continue
            left, right = part.split(":", 1)
            try:
                out[int(left.strip())] = int(right.strip())
            except (TypeError, ValueError):
                continue
        return out

    def _query_mtga_local_ability_texts(self, grp_id: int) -> Dict[int, str]:
        """Look up ability text mappings for one card grpId from local MTGA SQLite."""
        import sqlite3

        if grp_id in self._ability_text_cache:
            return self._ability_text_cache[grp_id]

        db_path = self._resolve_mtga_db_path()
        if not db_path:
            self._ability_text_cache[grp_id] = {}
            return {}

        resolved: Dict[int, str] = {}
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute(
                'SELECT "AbilityIds", "HiddenAbilityIds" FROM "Cards" WHERE "GrpId" = ?',
                (grp_id,),
            )
            row = cur.fetchone()
            if row:
                ability_map = self._parse_ability_mapping(row[0])
                hidden_map = self._parse_ability_mapping(row[1])
                all_loc_ids = {**ability_map, **hidden_map}
                for ability_grp_id, loc_id in all_loc_ids.items():
                    cur.execute(
                        'SELECT "Loc" FROM "Localizations_enUS" WHERE "LocId" = ?',
                        (loc_id,),
                    )
                    loc_row = cur.fetchone()
                    if loc_row and loc_row[0]:
                        resolved[int(ability_grp_id)] = str(loc_row[0]).strip()
            conn.close()
        except Exception:
            resolved = {}

        self._ability_text_cache[grp_id] = resolved
        return resolved

    def get_card_ability_text(self, grp_id: int, ability_grp_id: int) -> Optional[str]:
        """Return localized ability text for one card's abilityGrpId when available."""
        if grp_id is None or ability_grp_id is None:
            return None
        ability_texts = self._query_mtga_local_ability_texts(int(grp_id))
        text = ability_texts.get(int(ability_grp_id))
        return text.strip() if isinstance(text, str) and text.strip() else None

    def get_ability_text(self, ability_grp_id: int) -> Optional[str]:
        """Return localized ability text by abilityGrpId, independent of source card."""
        import sqlite3

        if ability_grp_id is None:
            return None
        db_path = self._resolve_mtga_db_path()
        if not db_path:
            return None
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute(
                """
                SELECT l."Loc"
                FROM "Abilities" a
                JOIN "Localizations_enUS" l ON a."TextId" = l."LocId"
                WHERE a."Id" = ?
                ORDER BY l."Formatted" DESC
                LIMIT 1
                """,
                (int(ability_grp_id),),
            )
            row = cur.fetchone()
            conn.close()
            if row and row[0]:
                return str(row[0]).strip()
        except Exception:
            return None
        return None

    def get_card_name(self, grp_id: int) -> str:
        """Get the card name for a given MTGA grpId.

        Args:
            grp_id: The MTGA card group ID.

        Returns:
            Card name, or "Unknown Card (ID: grp_id)" if not found.
        """
        
        # Session cache: same deck/cards looked up many times in one run
        if grp_id in self.cache:
            return self.cache[grp_id]

        # On-demand lookup from local MTGA SQLite (Cards ⋈ Localizations_enUS)
        card_name = self._query_mtga_local_db(grp_id)
        if card_name:
            self.cache[grp_id] = card_name
            return card_name

        fallback = f"Card #{grp_id}"
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
                card_name = data.get("name", None)
                return card_name
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # Card not found in Scryfall - might be a new or special card
                return None
            else:
                # Don't print errors to avoid cluttering output
                return None
        except Exception as e:
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
                    return card_name
                return None
        except urllib.error.HTTPError as e:
            return None
        except Exception as e:
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
    
    def _find_scryfall_bulk_file(self) -> Optional[Path]:
        """Find Scryfall bulk file in data dir. Prefers all-cards*.json, then default-cards*.json."""
        data_dir = self.cache_path.parent
        for pattern in ("all-cards*.json", "default-cards*.json"):
            matches: List[Path] = list(data_dir.glob(pattern))
            if matches:
                return max(matches, key=lambda p: p.stat().st_mtime)
        return None
    
    def _build_scryfall_arena_index(self, bulk_path: Path) -> Dict[int, str]:
        """Stream-parse Scryfall bulk JSON and build arena_id -> name index. Requires ijson.

        Only cards with a non-null arena_id (on MTG Arena) go into the arena index.
        Cards like "Quantum Riddler" are in the bulk file but have arena_id: null,
        so they are omitted from scryfall_arena_index.json. A separate name-index
        file (scryfall_name_to_arena_id.json) is written with every card name ->
        arena_id so you can search any card; null means not on Arena.
        """
        if ijson is None:
            print("⚠ Scryfall bulk index requires 'ijson'; pip install ijson")
            return {}
        data_dir = self.cache_path.parent
        index_path = data_dir / "scryfall_arena_index.json"
        name_index_path = data_dir / "scryfall_name_to_arena_id.json"
        card_map: Dict[int, str] = {}
        name_to_arena: Dict[str, Optional[int]] = {}
        count = 0
        report_interval = 50_000
        print(f"Building Scryfall arena index from {bulk_path.name} (streaming, one-time)...")
        try:
            with open(bulk_path, "rb") as f:
                for card in ijson.items(f, "item"):
                    arena_id = card.get("arena_id")
                    name = card.get("name")
                    if name:
                        aid_int: Optional[int] = int(arena_id) if arena_id is not None else None
                        # Prefer keeping an arena_id when we've seen multiple printings
                        if name not in name_to_arena or aid_int is not None:
                            name_to_arena[name] = aid_int
                    if arena_id is not None and name:
                        try:
                            card_map[int(arena_id)] = name
                            count += 1
                        except (ValueError, TypeError):
                            pass
                    if count > 0 and count % report_interval == 0:
                        print(f"   ... {count} Arena cards indexed")
            with open(index_path, "w", encoding="utf-8") as out:
                json.dump({str(k): v for k, v in card_map.items()}, out, indent=0, separators=(",", ":"))
            with open(name_index_path, "w", encoding="utf-8") as out:
                json.dump(name_to_arena, out, indent=0, separators=(",", ":"))
            print(f"✓ Scryfall index built: {len(card_map)} Arena cards → {index_path.name}")
            print(f"✓ Full name index: {len(name_to_arena)} cards (all names) → {name_index_path.name}")
            return card_map
        except Exception as e:
            print(f"✗ Failed to build Scryfall index: {e}")
            return {}
    
    def _load_or_build_scryfall_arena_index(self) -> None:
        """Load Scryfall arena index from data/scryfall_arena_index.json, or build it from all-cards*.json."""
        data_dir = self.cache_path.parent
        index_path = data_dir / "scryfall_arena_index.json"
        bulk_path = self._find_scryfall_bulk_file()
        if index_path.exists():
            if bulk_path is None or index_path.stat().st_mtime >= bulk_path.stat().st_mtime:
                try:
                    with open(index_path, "r", encoding="utf-8") as f:
                        self.scryfall_arena_index = {int(k): v for k, v in json.load(f).items()}
                    if self.scryfall_arena_index:
                        print(f"✓ Loaded {len(self.scryfall_arena_index)} cards from Scryfall index")
                    return
                except Exception as e:
                    print(f"⚠ Scryfall index load failed: {e}")
        if bulk_path is not None:
            self.scryfall_arena_index = self._build_scryfall_arena_index(bulk_path)
    
    def _extract_cards_from_log(self) -> None:
        """Extract card name mappings from Player.log file.
        
        Scans the log file for card objects that contain both grpId and name fields,
        building a local database of card IDs to names. This helps identify cards
        that aren't in MTGJSON or Scryfall yet.
        """
        if not self.log_path or not Path(self.log_path).exists():
            return
        
        log_cache_path = self.cache_path.parent / "log_card_cache.json"
        
        # Try to load cached log extractions first
        if log_cache_path.exists():
            try:
                log_mtime = Path(self.log_path).stat().st_mtime
                cache_mtime = log_cache_path.stat().st_mtime
                
                # If cache is newer than log file, use cache
                if cache_mtime >= log_mtime:
                    with open(log_cache_path, 'r', encoding='utf-8') as f:
                        self.log_cache = {int(k): v for k, v in json.load(f).items()}
                    if self.log_cache:
                        print(f"✓ Loaded {len(self.log_cache)} card names from log cache")
                    return
            except Exception as e:
                # If cache load fails, continue to scan log
                pass
        
        # Scan the log file for card objects
        print("Scanning Player.log for card names...")
        card_map = {}
        scanned_lines = 0
        max_scan_lines = 200000  # Increased to scan more lines for better coverage
        
        try:
            with open(self.log_path, 'r', encoding='utf-8', errors='ignore') as f:
                # Read last N lines (most recent cards)
                lines = f.readlines()
                lines_to_scan = lines[-max_scan_lines:] if len(lines) > max_scan_lines else lines
                
                for line in lines_to_scan:
                    scanned_lines += 1
                    if scanned_lines % 10000 == 0:
                        print(f"  Scanned {scanned_lines} lines, found {len(card_map)} cards...")
                    
                    # Look for JSON objects that might contain card data
                    # Check for grpId, cardId (deck data), or gameObjects (game state)
                    if '{' not in line or ('grpId' not in line and 'cardId' not in line and 'gameObjects' not in line):
                        continue
                    
                    # Try to parse JSON from the line
                    try:
                        # Extract JSON object
                        json_match = re.search(r'\{.*\}', line)
                        if not json_match:
                            continue
                        
                        data = json.loads(json_match.group(0))
                        
                        # Recursively search for card objects with grpId and name
                        self._extract_cards_from_json(data, card_map)
                    except (json.JSONDecodeError, ValueError):
                        continue
            
            self.log_cache = card_map
            
            # Save the extracted mappings
            if card_map:
                try:
                    with open(log_cache_path, 'w', encoding='utf-8') as f:
                        json.dump(card_map, f, indent=2)
                    print(f"✓ Extracted {len(card_map)} card names from Player.log")
                except Exception as e:
                    print(f"⚠ Failed to save log cache: {e}")
            else:
                print("  No card names found in recent log entries")
        except Exception as e:
            print(f"⚠ Failed to scan Player.log: {e}")
    
    def _extract_cards_from_json(self, obj: Any, card_map: Dict[int, str]) -> None:
        """Recursively extract card objects from JSON structure.
        
        Args:
            obj: JSON object to search (dict, list, or primitive)
            card_map: Dictionary to store grpId -> card name mappings
        """
        if isinstance(obj, dict):
            # Check if this dict has both grpId and name/cardName (or overlayGrpId for alt-set IDs)
            grp_id = obj.get("grpId") or obj.get("cardId")  # Also check cardId (used in deck data)
            overlay_grp_id = obj.get("overlayGrpId")
            
            # Try multiple name fields - skip "name" if it's numeric (localization ID)
            potential_name = None
            for name_field in ["cardName", "displayName", "title", "cardTitle", "name"]:
                if name_field in obj:
                    val = obj.get(name_field)
                    # Skip if it's numeric (likely a localization ID)
                    if isinstance(val, str) and not val.isdigit() and len(val) > 1:
                        potential_name = val
                        break
                    # Also check if it's a number but we can use it as a last resort
                    # (some cards might have numeric names, but very rare)
            
            if potential_name and isinstance(potential_name, str) and not potential_name.isdigit() and len(potential_name) > 1:
                try:
                    if grp_id:
                        grp_id_int = int(grp_id)
                        if grp_id_int not in card_map or len(potential_name) > len(card_map.get(grp_id_int, "")):
                            card_map[grp_id_int] = potential_name
                    if overlay_grp_id is not None:
                        overlay_id_int = int(overlay_grp_id)
                        if overlay_id_int not in card_map or len(potential_name) > len(card_map.get(overlay_id_int, "")):
                            card_map[overlay_id_int] = potential_name
                except (ValueError, TypeError):
                    pass
            
            # Recursively search nested structures
            for value in obj.values():
                self._extract_cards_from_json(value, card_map)
        elif isinstance(obj, list):
            for item in obj:
                self._extract_cards_from_json(item, card_map)
