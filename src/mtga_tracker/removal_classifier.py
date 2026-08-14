"""Classify cards as removal / board wipes / mass bounce from rules text.

Classification is text-based (per design discussion): a card's role comes
from what its Arena ability text says, not from what it happened to do in a
particular game. That keeps counts stable and lets drawn-but-unplayed
removal count from the first game. Roles:

- ``wipe``: clears the board — destroy/exile/sacrifice all creatures, damage
  to each creature, mass -X/-X. Mass exile counts (the board is cleared no
  matter which zone the creatures end up in).
- ``bounce``: mass bounce — "return all/each creatures to their owners'
  hands". Tracked separately from wipes.
- ``removal``: targeted elimination — destroy/exile target creature,
  damage to a target, targeted -X/-X, fight effects.

Land destruction is intentionally NOT a role here: it is detected from game
events (a land actually dying to an enemy card), not from text.
"""

from __future__ import annotations

import re
from typing import Dict, FrozenSet, Iterable

ROLE_REMOVAL = "removal"
ROLE_WIPE = "wipe"
ROLE_BOUNCE = "bounce"

_CREATUREISH = r"(?:creatures?|permanents?|nonland permanents?|other permanents?|artifacts? and creatures?|creatures? and planeswalkers?)"

_WIPE_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        rf"destroys? all (?:other )?(?:tapped |untapped |attacking |blocking )?{_CREATUREISH}",
        rf"destroys? each {_CREATUREISH}",
        rf"exiles? all (?:other )?{_CREATUREISH}",
        rf"exiles? each {_CREATUREISH}",
        r"deals? \d+ damage to each creature",
        r"deals? \d+ damage to each (?:other )?creature",
        r"deals? damage to each creature",
        r"all creatures get -\d+/-\d+",
        r"each (?:other )?creature gets -\d+/-\d+",
        r"each player sacrifices all",
        rf"sacrifices? all {_CREATUREISH}",
        r"each player sacrifices (?:all|the rest)",
        r"destroy the rest",
    )
)

_BOUNCE_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        rf"returns? all (?:other )?{_CREATUREISH} to their owners?['’]?s? hands?",
        rf"returns? each (?:other )?{_CREATUREISH} to (?:its|their) owners?['’]?s? hands?",
    )
)

_REMOVAL_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"destroys? (?:up to \w+ )?target (?!land)",
        r"destroys? another target",
        r"exiles? (?:up to \w+ )?target (?!land)",
        r"exiles? another target",
        r"deals? \d+ damage to any target",
        r"deals? \d+ damage(?:,| to) (?:up to \w+ )?target creature",
        r"deals? \d+ damage to target (?:attacking|blocking|tapped)",
        r"deals? damage equal to [^.]* to (?:any target|target creature)",
        r"target creature gets -\d+/-\d+",
        r"target creature gets [-+]\d+/-\d+",
        r"fights? (?:up to \w+ )?(?:another )?target creature",
        r"fights? target creature",
        r"target player sacrifices an? (?:creature|permanent)",
        r"its controller sacrifices (?:it|a creature)",
        r"put target creature (?:on|into) (?:the|its owner)",
    )
)


def classify_ability_texts(texts: Iterable[str]) -> FrozenSet[str]:
    """Return the set of roles a card's ability texts imply."""
    roles = set()
    for text in texts:
        lowered = " ".join(str(text or "").lower().split())
        if not lowered:
            continue
        if any(pattern.search(lowered) for pattern in _WIPE_PATTERNS):
            roles.add(ROLE_WIPE)
        if any(pattern.search(lowered) for pattern in _BOUNCE_PATTERNS):
            roles.add(ROLE_BOUNCE)
        if any(pattern.search(lowered) for pattern in _REMOVAL_PATTERNS):
            roles.add(ROLE_REMOVAL)
    # A sweeper is a sweeper; don't double-count it as spot removal
    # (modal cards that do both keep the wipe classification).
    if ROLE_WIPE in roles:
        roles.discard(ROLE_REMOVAL)
    return frozenset(roles)


class RemovalClassifier:
    """Caches per-card role classification backed by the local card DB."""

    def __init__(self, card_db) -> None:
        self._card_db = card_db
        self._cache: Dict[int, FrozenSet[str]] = {}

    def roles_for(self, grp_id) -> FrozenSet[str]:
        if grp_id is None:
            return frozenset()
        try:
            key = int(grp_id)
        except (TypeError, ValueError):
            return frozenset()
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            texts = self._card_db.get_card_ability_texts(key)
        except Exception:
            texts = []
        roles = classify_ability_texts(texts)
        self._cache[key] = roles
        return roles
