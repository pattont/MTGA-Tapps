"""Store price lists for the dashboard's Buy on Paper dialog.

Card Kingdom and Mana Pool publish their whole singles price lists as public
JSON (about 70 MB and 50 MB). That is too large for the browser to fetch each
time the dialog opens, and Mana Pool's list doesn't allow cross-origin reads,
so the dashboard downloads each list at most once a day, keeps only every
card's cheapest in-stock printing (a few MB), and answers lookups locally.

Nothing here runs unless the Buy on Paper dialog asks for a store's prices.
Downloads happen on a background thread; until a list is ready the endpoint
answers ``loading`` and the dialog polls. A failed download is retried after
ten minutes at the earliest.

GET /api/paper-prices?vendor=cardkingdom&name=Opt&name=Negate
    200 {"status": "ready", "vendor", "as_of", "prices": {name: entry | null}}
    202 {"status": "loading"}
    502 {"status": "error", "error"}
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

from .paths import DATA_DIR

REFRESH_SECONDS = 24 * 60 * 60
RETRY_AFTER_ERROR_SECONDS = 10 * 60
DOWNLOAD_TIMEOUT = (15, 180)
USER_AGENT = "TappsTracker (local MTG Arena tracker; Buy on Paper prices)"
#: Longest name list one lookup accepts (a 100-card deck with sideboard fits).
MAX_NAMES = 250

Entry = Dict[str, Any]


def _number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(value)  # ijson yields Decimal; Card Kingdom sends strings.
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


#: Printings that aren't playable cards: gold-bordered, oversized, art cards.
_CK_SKIP_EDITIONS = (
    "not tournament legal",
    "oversized",
    "art series",
    "collectors' edition",
    "world championship",
    "gold border",
)
_SKIP_SET_CODES = {"CED", "CEI", "30A", "PTC"}


def _skip_set(set_code: str) -> bool:
    code = set_code.upper()
    return code in _SKIP_SET_CODES or code.startswith("WC") or code.startswith("OVERSIZED")


def _card_kingdom_entries(
    rows: Iterable[Dict[str, Any]], base_url: str
) -> Iterator[Tuple[str, Entry]]:
    """One entry per Card Kingdom SKU: SKU "FINV-064" is a foil, set INV, number 64."""
    for row in rows:
        name = str(row.get("name") or "").strip()
        price = _number(row.get("price_retail"))
        if not name or price is None or price == 0:
            continue
        foil = str(row.get("is_foil")).lower() == "true"
        sku = str(row.get("sku") or "")
        set_code, _, number = sku.partition("-")
        if foil and set_code.startswith("F"):
            set_code = set_code[1:]
        edition = str(row.get("edition") or "")
        variation = str(row.get("variation") or "").strip()
        label = f"{edition} {variation}".lower()
        if _skip_set(set_code) or any(word in label for word in _CK_SKIP_EDITIONS):
            continue
        yield name, {
            "usd": round(price, 2),
            "set": set_code.upper(),
            "set_name": f"{edition} ({variation})" if variation else edition,
            "collector_number": number.lstrip("0") or number,
            "finish": "foil" if foil else "nonfoil",
            "in_stock": int(row.get("qty_retail") or 0) > 0,
            "url": (
                base_url.rstrip("/") + "/" + str(row.get("url") or "").lstrip("/")
                if row.get("url")
                else None
            ),
        }


def _mana_pool_entries(
    rows: Iterable[Dict[str, Any]], base_url: str
) -> Iterator[Tuple[str, Entry]]:
    """One entry per Mana Pool printing, at its cheapest listed finish (any condition)."""
    del base_url  # Mana Pool rows carry absolute URLs.
    for row in rows:
        name = str(row.get("name") or "").strip()
        if not name or _skip_set(str(row.get("set_code") or "")):
            continue
        finishes = [
            ("nonfoil", _number(row.get("price_cents"))),
            ("foil", _number(row.get("price_cents_foil"))),
            ("etched", _number(row.get("price_cents_etched"))),
        ]
        priced = [(cents, finish) for finish, cents in finishes if cents]
        if not priced:
            continue
        cents, finish = min(priced)
        yield name, {
            "usd": round(cents / 100, 2),
            "set": str(row.get("set_code") or "").upper(),
            "set_name": "",
            "collector_number": str(row.get("number") or ""),
            "finish": finish,
            "in_stock": int(row.get("available_quantity") or 0) > 0,
            "url": row.get("url"),
        }


FEEDS: Dict[
    str, Tuple[str, Callable[[Iterable[Dict[str, Any]], str], Iterator[Tuple[str, Entry]]]]
] = {
    "cardkingdom": ("https://api.cardkingdom.com/api/v2/pricelist", _card_kingdom_entries),
    "manapool": ("https://manapool.com/api/v1/prices/singles", _mana_pool_entries),
}


def name_keys(name: str) -> List[str]:
    """Lookup keys: the full name and each face ("Fable of the Mirror-Breaker")."""
    lower = name.strip().lower()
    keys = [lower]
    if " // " in lower:
        keys.extend(part.strip() for part in lower.split(" // ") if part.strip())
    return keys


def _better(candidate: Entry, current: Optional[Entry]) -> bool:
    """In stock beats out of stock; then the lower price wins."""
    if current is None:
        return True
    if candidate["in_stock"] != current["in_stock"]:
        return bool(candidate["in_stock"])
    return candidate["usd"] < current["usd"]


def build_index(entries: Iterable[Tuple[str, Entry]]) -> Dict[str, Entry]:
    """Cheapest in-stock printing per lowercase name and face name."""
    index: Dict[str, Entry] = {}
    for name, entry in entries:
        entry = {**entry, "name": name}
        for key in name_keys(name):
            if _better(entry, index.get(key)):
                index[key] = entry
    return index


def lookup(index: Dict[str, Entry], names: Iterable[str]) -> Dict[str, Optional[Entry]]:
    found: Dict[str, Optional[Entry]] = {}
    for name in names:
        entry = None
        for key in name_keys(name):
            entry = index.get(key)
            if entry is not None:
                break
        found[name] = entry
    return found


# --------------------------------------------------------------------------
# Download and cache


def _cache_dir() -> Path:
    return DATA_DIR / "paper_prices"


def _cache_file(vendor: str) -> Path:
    return _cache_dir() / f"{vendor}.json"


def _download_rows(
    vendor: str, workdir: Path
) -> Tuple[Dict[str, Any], Iterator[Dict[str, Any]], Path]:
    """Stream the feed to a temp file, then stream-parse it (never all in memory)."""
    import ijson
    import requests

    url, _ = FEEDS[vendor]
    fd, temp_name = tempfile.mkstemp(prefix=f"{vendor}-", suffix=".download", dir=workdir)
    temp_path = Path(temp_name)
    with os.fdopen(fd, "wb") as handle:
        with requests.get(
            url, stream=True, timeout=DOWNLOAD_TIMEOUT, headers={"User-Agent": USER_AGENT}
        ) as response:
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=1 << 20):
                handle.write(chunk)
    with temp_path.open("rb") as handle:
        meta = next(ijson.items(handle, "meta"), {}) or {}
    rows = _iter_rows(temp_path)
    return meta, rows, temp_path


def _iter_rows(path: Path) -> Iterator[Dict[str, Any]]:
    import ijson

    with path.open("rb") as handle:
        yield from ijson.items(handle, "data.item")


def refresh(vendor: str, download: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    """Download one store's list, index it and write the cache file."""
    workdir = _cache_dir()
    workdir.mkdir(parents=True, exist_ok=True)
    meta, rows, temp_path = (download or _download_rows)(vendor, workdir)
    try:
        _, entries = FEEDS[vendor]
        base_url = str(meta.get("base_url") or "")
        index = build_index(entries(rows, base_url))
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    if not index:
        raise ValueError(f"{vendor} price list was empty")
    data = {
        "vendor": vendor,
        "as_of": str(meta.get("created_at") or meta.get("as_of") or ""),
        "fetched_at": time.time(),
        "cards": index,
    }
    target = _cache_file(vendor)
    fd, temp_name = tempfile.mkstemp(prefix=f"{vendor}-", suffix=".json.tmp", dir=workdir)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, separators=(",", ":"))
    os.replace(temp_name, target)
    return data


_LOCK = threading.Lock()
_LOADED: Dict[str, Dict[str, Any]] = {}
_REFRESHING: set = set()
_ERRORS: Dict[str, Tuple[float, str]] = {}


def _load_cached(vendor: str) -> Optional[Dict[str, Any]]:
    data = _LOADED.get(vendor)
    if data is not None:
        return data
    try:
        with _cache_file(vendor).open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("cards"), dict):
        return None
    _LOADED[vendor] = data
    return data


def _refresh_in_background(vendor: str, download: Optional[Callable[..., Any]]) -> None:
    def run() -> None:
        try:
            data = refresh(vendor, download)
        except Exception as exc:  # noqa: BLE001 - reported to the dialog, retried later
            with _LOCK:
                _ERRORS[vendor] = (time.time(), f"{type(exc).__name__}: {exc}")
                _REFRESHING.discard(vendor)
            return
        with _LOCK:
            _LOADED[vendor] = data
            _ERRORS.pop(vendor, None)
            _REFRESHING.discard(vendor)

    _REFRESHING.add(vendor)
    threading.Thread(target=run, name=f"paper-prices-{vendor}", daemon=True).start()


def get_prices(
    vendor: str,
    names: List[str],
    *,
    now: Optional[float] = None,
    download: Optional[Callable[..., Any]] = None,
) -> Tuple[int, Dict[str, Any]]:
    """Prices for ``names`` at ``vendor``. A stale list still answers while it refreshes."""
    if vendor not in FEEDS:
        return 404, {"status": "error", "error": f"No price list for {vendor!r}."}
    names = [name for name in dict.fromkeys(n.strip() for n in names) if name][:MAX_NAMES]
    now = time.time() if now is None else now
    with _LOCK:
        data = _load_cached(vendor)
        fresh = data is not None and now - float(data.get("fetched_at") or 0) < REFRESH_SECONDS
        error = _ERRORS.get(vendor)
        recent_error = error is not None and now - error[0] < RETRY_AFTER_ERROR_SECONDS
        if not fresh and vendor not in _REFRESHING and not recent_error:
            _refresh_in_background(vendor, download)
        refreshing = vendor in _REFRESHING
    if data is not None:
        return 200, {
            "status": "ready",
            "vendor": vendor,
            "as_of": data.get("as_of") or "",
            "stale": not fresh,
            "prices": lookup(data["cards"], names),
        }
    if refreshing:
        return 202, {"status": "loading", "vendor": vendor}
    return 502, {
        "status": "error",
        "vendor": vendor,
        "error": error[1] if error else "Price list unavailable.",
    }


def handle_get(path: str, query: Dict[str, List[str]]) -> Optional[Tuple[int, Dict[str, Any]]]:
    if path != "/api/paper-prices":
        return None
    vendor = (query.get("vendor") or [""])[0]
    return get_prices(vendor, query.get("name") or [])


def _reset_for_tests() -> None:
    with _LOCK:
        _LOADED.clear()
        _REFRESHING.clear()
        _ERRORS.clear()
