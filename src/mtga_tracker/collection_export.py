"""Read your MTGA card collection out of the running game and export it.

Arena stopped writing the collection to Player.log, and there is no file on
disk or sanctioned API that lists what you own — so the collection is read
from the **running game's process memory**. The extraction technique (anchor
patterns, stride-walk block extraction, block scoring/validation) is adapted
from NthPhantom10's MTGA-collection-exporter (MIT):
https://github.com/NthPhantom10/MTGA-collection-exporter

This module is stdlib-only. It never modifies the game — it only reads
memory. macOS requires elevated rights to read another process's memory, so
the actual scan runs as a short-lived elevated helper (see
``run_scan_cli`` / the dashboard's export endpoint); Windows reads
same-user memory without elevation.

Pieces:
- ``MacOSMemory`` / ``WindowsMemory`` — platform readers (ctypes; no deps).
- ``extract_blocks`` / ``score_and_validate`` — the pure scan core, unit
  tested against synthetic memory images.
- ``derive_anchors`` — locator (arena_id, qty) pairs from the tracker's own
  recorded decklists, so nothing has to be typed.
- ``scan_collection`` — attach, scan, return ``{arena_id: quantity}``.
- ``aggregate`` + ``write_json``/``write_csv``/``write_txt`` — format the
  scanned collection into importable files.
"""

from __future__ import annotations

import ctypes
import json
import struct
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple


# --- Scan tuning (ported from mtg.py v3.4) ---------------------------------

MIN_ARENA_ID = 1000
MAX_ARENA_ID = 900_000
MIN_QTY = 1
MAX_QTY = 400
MIN_BLOCK_SIZE = 50
MAX_GAP = 64
STRIDES_WORDS = (2, 3, 4)
SCAN_WINDOW_BYTES = 8 * 1024 * 1024  # ±4 MB read around each anchor hit
MAX_REGION_BYTES = 256 * 1024 * 1024  # skip huge regions to bound the scan

ProgressFn = Callable[[str], None]


def _noop(_message: str) -> None:
    pass


# --- Platform memory readers ------------------------------------------------


class MacOSMemory:
    """Read another process's memory on macOS via the Mach VM API.

    Ported nearly verbatim from mtg.py's MacOSMem (already pure ctypes).
    Requires elevated rights (``task_for_pid``), so this runs inside the
    elevated helper only.
    """

    _KERN_SUCCESS = 0
    _VM_REGION_BASIC_INFO_64 = 9
    _VM_REGION_BASIC_INFO_COUNT_64 = 9
    _VM_PROT_READ = 0x01

    def __init__(self, process_name: str = "MTGA"):
        self._lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        self._setup_funcs()
        self.process_id = _find_pid_macos(process_name)
        if not self.process_id:
            raise ProcessNotFound(process_name)
        self_task = ctypes.c_uint.in_dll(self._lib, "mach_task_self_").value
        self._task = ctypes.c_uint(0)
        kr = self._lib.task_for_pid(self_task, self.process_id, ctypes.byref(self._task))
        if kr != self._KERN_SUCCESS:
            raise PermissionError(
                f"task_for_pid failed (err={kr}); memory read needs elevated rights"
            )

    def _setup_funcs(self) -> None:
        lib = self._lib
        lib.task_for_pid.restype = ctypes.c_int
        lib.task_for_pid.argtypes = [
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint),
        ]
        lib.mach_vm_read.restype = ctypes.c_int
        lib.mach_vm_read.argtypes = [
            ctypes.c_uint,
            ctypes.c_uint64,
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint),
        ]
        lib.mach_vm_region.restype = ctypes.c_int
        lib.mach_vm_region.argtypes = [
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
        ]

    def read_bytes(self, address: int, length: int) -> bytes:
        if address < 0 or length <= 0:
            return b""
        data_ptr = ctypes.c_uint64(0)
        data_cnt = ctypes.c_uint(0)
        kr = self._lib.mach_vm_read(
            self._task.value, address, length, ctypes.byref(data_ptr), ctypes.byref(data_cnt)
        )
        if kr != self._KERN_SUCCESS:
            raise OSError(f"mach_vm_read failed: {kr}")
        return ctypes.string_at(data_ptr.value, data_cnt.value)

    def readable_regions(self):
        addr = ctypes.c_uint64(0)
        while True:
            size = ctypes.c_uint64(0)
            info = _MachRegionInfo()
            cnt = ctypes.c_uint(self._VM_REGION_BASIC_INFO_COUNT_64)
            obj = ctypes.c_uint(0)
            kr = self._lib.mach_vm_region(
                self._task.value,
                ctypes.byref(addr),
                ctypes.byref(size),
                self._VM_REGION_BASIC_INFO_64,
                ctypes.byref(info),
                ctypes.byref(cnt),
                ctypes.byref(obj),
            )
            if kr != self._KERN_SUCCESS:
                break
            if info.protection & self._VM_PROT_READ:
                yield addr.value, size.value
            addr.value += size.value


class _MachRegionInfo(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("protection", ctypes.c_int32),
        ("max_protection", ctypes.c_int32),
        ("inheritance", ctypes.c_uint32),
        ("shared", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
        ("offset", ctypes.c_uint64),
        ("behavior", ctypes.c_int32),
        ("user_wired_count", ctypes.c_uint16),
        ("_pad", ctypes.c_uint16),
    ]


class WindowsMemory:
    """Read another process's memory on Windows via ctypes kernel32 calls.

    Replaces mtg.py's pymem dependency with the same three Win32 calls the
    macOS reader hand-rolls: OpenProcess / VirtualQueryEx / ReadProcessMemory.
    Same-user PROCESS_VM_READ needs no elevation.
    """

    _PROCESS_QUERY_INFORMATION = 0x0400
    _PROCESS_VM_READ = 0x0010
    _MEM_COMMIT = 0x1000
    _PAGE_READABLE = 0x02 | 0x04 | 0x20 | 0x40  # RO, RW, EXEC_READ, EXEC_RW

    def __init__(self, process_name: str = "MTGA.exe"):
        self._k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        self.process_id = _find_pid_windows(process_name)
        if not self.process_id:
            raise ProcessNotFound(process_name)
        access = self._PROCESS_QUERY_INFORMATION | self._PROCESS_VM_READ
        self._handle = self._k32.OpenProcess(access, False, self.process_id)
        if not self._handle:
            raise PermissionError("OpenProcess failed; cannot read MTGA memory")

    def read_bytes(self, address: int, length: int) -> bytes:
        if address < 0 or length <= 0:
            return b""
        buf = ctypes.create_string_buffer(length)
        read = ctypes.c_size_t(0)
        ok = self._k32.ReadProcessMemory(
            self._handle,
            ctypes.c_void_p(address),
            buf,
            ctypes.c_size_t(length),
            ctypes.byref(read),
        )
        if not ok:
            raise OSError("ReadProcessMemory failed")
        return buf.raw[: read.value]

    def readable_regions(self):
        address = 0
        max_address = 0x7FFFFFFFFFFF
        info = _MemoryBasicInformation()
        while address < max_address:
            got = self._k32.VirtualQueryEx(
                self._handle,
                ctypes.c_void_p(address),
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            if not got:
                break
            region_size = int(info.RegionSize)
            if (
                info.State == self._MEM_COMMIT
                and (info.Protect & self._PAGE_READABLE)
            ):
                yield int(info.BaseAddress), region_size
            address = int(info.BaseAddress) + max(region_size, 0x1000)


class _MemoryBasicInformation(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", ctypes.c_uint32),
        ("__alignment1", ctypes.c_uint32),
        ("RegionSize", ctypes.c_size_t),
        ("State", ctypes.c_uint32),
        ("Protect", ctypes.c_uint32),
        ("Type", ctypes.c_uint32),
        ("__alignment2", ctypes.c_uint32),
    ]


class ProcessNotFound(RuntimeError):
    """MTGA is not running (or its process could not be found)."""

    def __init__(self, process_name: str):
        super().__init__(f"Process not found: {process_name}")
        self.process_name = process_name


def _find_pid_macos(process_name: str) -> Optional[int]:
    """PID of a running process by exact name — pgrep, no psutil."""
    try:
        out = subprocess.run(
            ["pgrep", "-x", process_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.stdout.split():
        try:
            return int(line)
        except ValueError:
            continue
    return None


def _find_pid_windows(process_name: str) -> Optional[int]:
    """PID of a running process by image name — tasklist, no psutil."""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {process_name}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for row in out.stdout.splitlines():
        parts = [p.strip('"') for p in row.split('","')]
        if len(parts) >= 2 and parts[0].lower() == process_name.lower():
            try:
                return int(parts[1])
            except ValueError:
                continue
    return None


# --- The pure scan core (unit-tested; no process access) --------------------


@dataclass
class Anchor:
    arena_id: int
    quantity: int
    name: str = ""


def extract_blocks(data: bytes) -> List[Tuple[Dict[int, int], int]]:
    """Extract candidate ``{arena_id: quantity}`` blocks from a memory image.

    Arena stores the collection as a run of (arena_id, quantity) integer
    pairs. The container's word stride has changed across client versions,
    so we walk the buffer at strides 2/3/4 words and every offset within
    each stride, accumulating plausible pairs into a block until MAX_GAP
    consecutive misses end it. Duplicate ids within a block are counted
    (not summed) as a dirty-block signal for scoring.

    Returns ``(block, duplicate_count)`` tuples. Pure: bytes in, dicts out.
    """
    n_ints = len(data) // 4
    if n_ints < 2:
        return []
    try:
        ints = struct.unpack_from(f"<{n_ints}I", data)
    except struct.error:
        return []

    blocks: List[Tuple[Dict[int, int], int]] = []
    for stride in STRIDES_WORDS:
        for offset in range(stride):
            current: Dict[int, int] = {}
            duplicates = 0
            misses = 0
            i = offset
            while i + 1 < n_ints:
                k, v = ints[i], ints[i + 1]
                if MIN_ARENA_ID <= k < MAX_ARENA_ID and MIN_QTY <= v <= MAX_QTY:
                    if k in current:
                        duplicates += 1
                    else:
                        current[k] = v
                    misses = 0
                else:
                    misses += 1
                    if misses > MAX_GAP:
                        if len(current) >= MIN_BLOCK_SIZE:
                            blocks.append((current, duplicates))
                        current = {}
                        duplicates = 0
                        misses = 0
                i += stride
            if len(current) >= MIN_BLOCK_SIZE:
                blocks.append((current, duplicates))
    return blocks


def score_and_validate(
    blocks: Sequence[Tuple[Dict[int, int], int]],
    anchors: Sequence[Anchor],
    known_ids: Set[int],
    *,
    strict: bool = False,
) -> Optional[Dict[int, int]]:
    """Pick the best candidate block and validate it, or return None.

    Scoring (ported from mtg.py v3.4) rewards a high known-id ratio, exact
    (id, qty) anchor matches, anchor ids present, size, and few duplicates —
    with zero-duplicate blocks preferred outright in the tiebreak. The winner
    must clear sanity checks: enough entries, mostly-known ids, a believable
    total quantity, and a low duplicate rate. ``strict`` raises the bar for
    the anchorless fallback path.
    """
    anchor_pairs = {(a.arena_id, a.quantity) for a in anchors}
    anchor_ids = {a.arena_id for a in anchors}
    n_anchors = max(1, len(anchors))

    scored: List[Tuple[Dict[int, int], float, int, int, int]] = []
    for block, dupes in blocks:
        if not block:
            continue
        known = sum(1 for k in block if k in known_ids)
        known_ratio = known / len(block)
        anchors_exact = sum(1 for k, v in block.items() if (k, v) in anchor_pairs)
        anchors_id = sum(1 for k in block if k in anchor_ids)
        size_score = min(len(block) / 5000, 1.0)
        dup_ratio = dupes / max(1, len(block) + dupes)
        score = (
            known_ratio * 0.35
            + (anchors_exact / n_anchors) * 0.35
            + (anchors_id / n_anchors) * 0.10
            + size_score * 0.10
            + (1.0 - dup_ratio) * 0.10
        )
        scored.append((block, score, anchors_exact, known, dupes))

    if not scored:
        return None

    scored.sort(
        key=lambda x: (x[4] == 0, x[1], x[2], x[3], len(x[0])),
        reverse=True,
    )
    best_block, _score, _exact, _known, best_dupes = scored[0]
    if _validate_block(best_block, best_dupes, known_ids, anchor_ids, strict=strict):
        return best_block
    return None


def _validate_block(
    block: Dict[int, int],
    duplicates: int,
    known_ids: Set[int],
    anchor_ids: Set[int] = frozenset(),
    *,
    strict: bool,
) -> bool:
    if not block:
        return False
    min_entries = 500 if strict else 10
    if len(block) < min_entries or len(block) > 100_000:
        return False
    if sum(block.values()) > 500_000:
        return False
    if duplicates > max(25, int(len(block) * 0.05)):
        return False
    # Several of the player's OWN cards clustered in one block is decisive
    # even when the block is mostly cards the tracker has never seen played —
    # which is the normal shape of a full collection (lots of unplayed junk),
    # and exactly what made the old 30%-known-ratio bar reject the real block.
    anchors_present = sum(1 for k in block if k in anchor_ids)
    if not strict and anchors_present >= 3:
        return True
    known = sum(1 for k in block if k in known_ids)
    ratio = known / len(block)
    return ratio >= (0.60 if strict else 0.18)


# --- Anchors from the tracker's own decklists -------------------------------


def derive_anchors(conn, limit: int = 16) -> List[Anchor]:
    """Locator arena_ids from cards the player's decklists prove they own.

    Cards that appear as 4-ofs in the player's submitted decklists are cards
    they definitely own — reliable memory locators, no typing, no saved
    file. Ranked by how many distinct decks agree, so the most confidently
    owned cards are tried first.

    The scan matches on the arena_id ALONE (checking that a plausible
    quantity follows), so it locates the card at whatever quantity it's
    actually owned — a card run as a 4-of but owned as a full playset of 4,
    or opened six times, is found either way. The quantity here is only a
    hint for the (unused) exact-match scoring bonus.
    """
    try:
        rows = conn.execute(
            """
            SELECT dc.arena_id, COUNT(DISTINCT dc.game_id) AS decks, MAX(dc.display_name)
            FROM game_deck_cards dc
            JOIN participants p ON p.id = dc.participant_id AND p.role = 'player'
            WHERE dc.deck_zone = 'deck' AND dc.quantity = 4
              AND dc.arena_id BETWEEN ? AND ?
            GROUP BY dc.arena_id
            ORDER BY decks DESC, dc.arena_id
            LIMIT ?
            """,
            (MIN_ARENA_ID, MAX_ARENA_ID - 1, limit),
        ).fetchall()
    except Exception:
        return []
    return [Anchor(int(aid), 4, str(name or "")) for aid, _decks, name in rows]


def known_arena_ids(conn) -> Set[int]:
    """Every arena_id the tracker has ever recorded — the 'known-id' set the
    scan scores candidate blocks against."""
    ids: Set[int] = set()
    for table, column in (
        ("game_deck_cards", "arena_id"),
        ("cards", "arena_id"),
    ):
        try:
            for (value,) in conn.execute(
                f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL"
            ):
                try:
                    ids.add(int(value))
                except (TypeError, ValueError):
                    continue
        except Exception:
            continue
    return ids


# --- Attach + scan ----------------------------------------------------------


def open_process_memory():
    """Return a platform memory reader, or raise ProcessNotFound/RuntimeError."""
    if sys.platform == "darwin":
        return MacOSMemory("MTGA")
    if sys.platform == "win32":
        return WindowsMemory("MTGA.exe")
    raise RuntimeError("Collection export is supported only on macOS and Windows.")


def scan_collection(
    conn,
    *,
    memory=None,
    progress: ProgressFn = _noop,
) -> Dict[int, int]:
    """Attach to MTGA and return the collection as ``{arena_id: quantity}``.

    Single pass over memory: each readable region is read once, searched for
    every anchor pattern, and — around any hit — has candidate blocks
    extracted. The best block that validates wins. If no anchor hits (or none
    validates), an anchorless full-region sweep with a stricter bar runs as
    a fallback. Reports percentage progress so the UI can show real motion.

    Raises ProcessNotFound when MTGA is not running, PermissionError when its
    memory can't be read, and CollectionNotFound when no valid block is found.
    """
    progress("Attaching to MTG Arena…")
    mem = memory if memory is not None else open_process_memory()

    known = known_arena_ids(conn)
    anchors = derive_anchors(conn)
    # Match on the 4-byte arena_id alone — the collection stores it followed
    # by the owned quantity, so verifying a plausible qty in the next 4 bytes
    # finds the card at whatever amount it's owned (not just as a 4-of).
    id_patterns = [struct.pack("<I", a.arena_id) for a in anchors]

    progress("Reading Arena's memory…")
    regions = [(addr, size) for addr, size in mem.readable_regions() if 0 < size <= MAX_REGION_BYTES]
    total = len(regions) or 1

    # Pass 1: locate the collection near where the player's own cards cluster,
    # validating region-by-region so a hit returns without scanning the rest.
    blocks: List[Tuple[Dict[int, int], int]] = []
    for index, (addr, size) in enumerate(regions):
        if index % 4 == 0:
            progress(f"Scanning Arena's memory… {int(100 * index / total)}%")
        try:
            data = mem.read_bytes(addr, size)
        except OSError:
            continue
        hits: List[int] = []
        for pattern in id_patterns:
            start = 0
            while True:
                pos = data.find(pattern, start)
                if pos == -1:
                    break
                # Only count it if a plausible quantity follows — that's what
                # distinguishes a real (id, qty) pair from a coincidental int.
                if pos + 8 <= len(data):
                    qty = int.from_bytes(data[pos + 4 : pos + 8], "little")
                    if MIN_QTY <= qty <= MAX_QTY:
                        hits.append(pos)
                start = pos + 1
        if not hits:
            continue
        for pos in _cluster_positions(hits):
            lo = max(0, pos - SCAN_WINDOW_BYTES // 2)
            hi = min(len(data), pos + SCAN_WINDOW_BYTES // 2)
            blocks.extend(extract_blocks(data[lo:hi]))
        result = score_and_validate(blocks, anchors, known)
        if result is not None:
            progress(f"Mapping {len(result)} cards…")
            return result

    # Pass 2: anchorless full sweep — only reached when nothing matched an
    # anchor (e.g. no recorded decklists). Slow; the UI warns it can take a
    # while.
    blocks = []
    for index, (addr, size) in enumerate(regions):
        if index % 4 == 0:
            progress(f"Deep scan of Arena's memory… {int(100 * index / total)}%")
        try:
            data = mem.read_bytes(addr, size)
        except OSError:
            continue
        blocks.extend(extract_blocks(data))
    result = score_and_validate(blocks, anchors, known, strict=True)
    if result is not None:
        progress(f"Mapping {len(result)} cards…")
        return result

    raise CollectionNotFound()


def _cluster_positions(positions: List[int]) -> List[int]:
    """Collapse hit offsets within one read window — one extract covers them."""
    out: List[int] = []
    for pos in sorted(set(positions)):
        if not out or pos - out[-1] > SCAN_WINDOW_BYTES // 2:
            out.append(pos)
    return out


class CollectionNotFound(RuntimeError):
    """No valid collection block was found in MTGA's memory."""


# --- Formatting -------------------------------------------------------------


@dataclass
class CollectionEntry:
    count: int
    name: str
    set: str = ""
    collector_number: str = ""
    arena_ids: List[int] = field(default_factory=list)


def aggregate(
    collection: Dict[int, int],
    metadata: Dict[int, Tuple[str, str, str]],
    *,
    keep_a_prefix: bool = False,
) -> List[CollectionEntry]:
    """Turn ``{arena_id: qty}`` into export entries, keyed by (name, set).

    Alchemy ``A-`` rebalances collapse onto the base card when the base name
    is known (unless keep_a_prefix). Ids the metadata can't resolve are
    skipped — a name is required to import. Blank-set duplicates merge into
    the single known printing of the same name when there is exactly one,
    mirroring the original's dedup.
    """
    all_names = {name.lower() for name, _s, _n in metadata.values()}

    def norm(name: str) -> str:
        if not keep_a_prefix and name.startswith("A-"):
            base = name[2:].strip()
            if base and base.lower() in all_names:
                return base
        return name

    raw: Dict[Tuple[str, str], CollectionEntry] = {}
    for arena_id, qty in collection.items():
        meta = metadata.get(arena_id)
        if not meta:
            continue
        name, set_code, collector = meta
        name = norm(name)
        if not name:
            continue
        key = (name, set_code.upper())
        entry = raw.get(key)
        if entry is None:
            entry = CollectionEntry(0, name, set_code.upper(), collector, [])
            raw[key] = entry
        entry.count += qty
        if arena_id not in entry.arena_ids:
            entry.arena_ids.append(arena_id)

    merged = dict(raw)
    by_name: Dict[str, List[Tuple[Tuple[str, str], CollectionEntry]]] = {}
    for key, entry in raw.items():
        by_name.setdefault(entry.name, []).append((key, entry))
    for _name, items in by_name.items():
        empty = [(k, e) for k, e in items if not k[1]]
        nonempty = [(k, e) for k, e in items if k[1]]
        if empty and len(nonempty) == 1:
            _target_key, target = nonempty[0]
            for key, entry in empty:
                target.count += entry.count
                for aid in entry.arena_ids:
                    if aid not in target.arena_ids:
                        target.arena_ids.append(aid)
                if not target.collector_number and entry.collector_number:
                    target.collector_number = entry.collector_number
                merged.pop(key, None)

    return sorted(merged.values(), key=lambda e: (e.name, e.set))


def write_json(entries: List[CollectionEntry], path, *, database_size: int = 0, now: str = "") -> None:
    data = {
        "export_date": now,
        "total_unique": len(entries),
        "total_cards": sum(e.count for e in entries),
        "database_size": database_size,
        "cards": [
            {
                "count": e.count,
                "name": e.name,
                "set": e.set,
                "collector_number": e.collector_number,
                "arena_ids": e.arena_ids,
            }
            for e in entries
        ],
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)


def write_csv(entries: List[CollectionEntry], path) -> None:
    """Moxfield's collection-import CSV dialect (matches mtg.py's writer)."""
    import csv

    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Count", "Name", "Edition", "Condition", "Language", "Foil", "Tag"])
        for e in entries:
            writer.writerow([e.count, e.name, e.set, "Near Mint", "English", "", ""])


def write_txt(entries: List[CollectionEntry], path) -> None:
    """Arena/Moxfield deck-line format, no header — pastes straight in."""
    with open(path, "w", encoding="utf-8") as handle:
        for e in entries:
            parts = [f"{e.count} {e.name}"]
            if e.set:
                parts.append(f"({e.set})")
                if e.collector_number:
                    parts.append(e.collector_number)
            handle.write(" ".join(parts) + "\n")


WRITERS: Dict[str, Tuple[Callable[..., None], str]] = {
    "json": (write_json, "json"),
    "csv": (write_csv, "csv"),
    "txt": (write_txt, "txt"),
}


# --- Elevated helper CLI (macOS) --------------------------------------------


def run_scan_cli(argv: Optional[Sequence[str]] = None) -> int:
    """``python -m mtga_tracker.collection_export --scan-json <db> <out>``.

    The macOS elevated helper: attaches to MTGA, scans, and writes the raw
    ``{arena_id: quantity}`` JSON to <out>. Runs under ``osascript ... with
    administrator privileges`` so the memory read has the rights it needs;
    the unprivileged dashboard then reads <out>, maps, and formats. Prints a
    machine-readable ``ERROR <code>`` line and exits non-zero on failure.
    """
    import argparse
    import sqlite3

    parser = argparse.ArgumentParser(prog="mtga_tracker.collection_export")
    parser.add_argument("--scan-json", nargs=2, metavar=("DB", "OUT"), required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    db_path, out_path = args.scan_json

    # Progress goes to a sidecar file the (unprivileged) dashboard polls while
    # this elevated helper runs — osascript's blocking call hides our stdout.
    progress_path = out_path + ".progress"

    def progress(message: str) -> None:
        try:
            with open(progress_path, "w", encoding="utf-8") as handle:
                handle.write(message)
        except OSError:
            pass

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        print("ERROR db_unreadable", file=sys.stderr)
        return 3
    try:
        collection = scan_collection(conn, progress=progress)
    except ProcessNotFound:
        print("ERROR arena_not_running", file=sys.stderr)
        return 4
    except PermissionError:
        print("ERROR permission_denied", file=sys.stderr)
        return 5
    except CollectionNotFound:
        print("ERROR no_collection", file=sys.stderr)
        return 6
    except Exception as exc:  # noqa: BLE001 - helper must not leak a traceback
        print(f"ERROR scan_failed {exc}", file=sys.stderr)
        return 7
    finally:
        conn.close()

    try:
        with open(out_path, "w", encoding="utf-8") as handle:
            json.dump({str(k): v for k, v in collection.items()}, handle)
    except OSError:
        print("ERROR out_unwritable", file=sys.stderr)
        return 8
    print(f"OK {len(collection)}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(run_scan_cli())
