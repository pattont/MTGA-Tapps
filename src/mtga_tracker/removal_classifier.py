"""Classify cards as removal / board wipes / mass bounce from rules text.

Classification is text-based (per design discussion): a card's role comes
from what its Arena ability text says, not from what it happened to do in a
particular game. That keeps counts stable and lets drawn-but-unplayed
removal count from the first game. Roles:

- ``wipe``: clears the board — destroy/exile/sacrifice all creatures, damage
  to each creature, mass -X/-X. Mass exile counts (the board is cleared no
  matter which zone the creatures end up in).
- ``bounce``: bounce — targeted ("return target creature to its owner's
  hand") or mass ("return all/each creatures to their owners' hands").
  Tracked separately from wipes and spot removal.
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
ROLE_COUNTER = "counter"

_CREATUREISH = r"(?:creatures?|permanents?|nonland permanents?|other permanents?|artifacts? and creatures?|creatures? and planeswalkers?)"

_WIPE_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        rf"destroys? all (?:other )?{_CREATUREISH}",
        rf"destroys? each (?:other )?{_CREATUREISH}",
        # One-sided type wipes ("each non-Dragon creature") clear the whole
        # board bar the caster's tribe — that is a wipe. State-qualified
        # subsets (all TAPPED creatures) are removal instead, per design
        # review: Split Up usually kills half a board, not the board.
        r"destroys? (?:all|each) non-[\w-]+ creatures?",
        rf"exiles? all (?:other )?{_CREATUREISH}",
        rf"exiles? each (?:other )?{_CREATUREISH}",
        r"deals? \d+ damage to each creature",
        r"deals? \d+ damage to each (?:other )?creature",
        r"deals? \d+ damage to each non-[\w-]+ creature",
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
        # Targeted bounce (Unsummon and friends). "(?!land)" keeps land-cycling
        # tricks out; owner phrasing keeps "return ... from your graveyard to
        # your hand" recursion from matching.
        r"returns? (?:up to \w+ )?(?:another )?target (?!land)[^.]{0,60}to (?:its|their) owners?['’]?s? hands?",
        # Subset mass bounce (Aetherize: "all attacking creatures").
        r"returns? all (?:tapped |untapped |attacking |blocking )creatures to their owners?['’]?s? hands?",
        # Avatar's airbend exiles with a recast tax — on the battlefield it
        # plays like bounce (design review ruling). On the stack it acts as a
        # counterspell; logged as an open case in docs/REMOVAL_CLASSIFICATION.
        r"airbend (?:up to \w+ )?(?:one )?(?:other )?target",
        r"airbend (?:all|each)",
    )
)

# Counter magic: hard counters and soft "unless its controller pays" ones
# both classify — whether it lands is tracked separately from game events.
_COUNTER_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"counters? target .{0,60}spell",
        r"counters? target (?:activated |triggered )?abilit",
        r"counters? that spell",
        r"counters? it unless",
    )
)

_REMOVAL_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        # The lookahead keeps land destruction out ("target land", "target
        # nonbasic land") and graveyard/hand/library effects out — battlefield
        # removal targets a creature/permanent/artifact/..., never a "card"
        # ("exile target card from a graveyard" is graveyard hate). "you
        # control" effects (self-blink like Ennis, The Mind Stone) are the
        # caster protecting their own permanents, not removal.
        r"destroys? (?:up to \w+ )?(?:other |another )?target (?!(?:[\w-]+ )?land\b|card\b)(?![^.]{0,40}you control)",
        r"exiles? (?:up to \w+ )?(?:other |another )?target (?!(?:[\w-]+ )?land\b|card\b)(?![^.]{0,40}you control)",
        # State-qualified sweeps are removal, not wipes (the Split Up rule).
        r"destroys? all (?:tapped|untapped|attacking|blocking) creatures",
        # Edicts: the opponent loses a permanent of their choice — removal
        # (Strategic Betrayal, Tribute to Hunger, Pick Your Poison, Sothera).
        r"(?:target|each) (?:opponent|player) (?:exiles?|sacrifices?) (?:a|an|one|up to one) [^.]{0,50}?(?:creature|permanent|planeswalker|artifact|enchantment)",
        r"each (?:opponent|player) chooses a [^.]{0,40}they control[^.]{0,30}exiles? it",
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
        # Temporary exile (O-Ring shells): removes the threat while it lasts.
        # "you control" flicker effects are excluded by the pattern above.
        r"exiles? (?:up to \w+ )?(?:other |another )?target (?!(?:[\w-]+ )?land\b|card\b)[^.]{0,60}until [^.]{0,40}leaves the battlefield",
        # Same O-Ring shell with "choose target ... exile that creature until".
        r"exiles? (?:that|those) creatures? [^.]{0,40}until [^.]{0,40}leaves the battlefield",
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
        if any(pattern.search(lowered) for pattern in _COUNTER_PATTERNS):
            roles.add(ROLE_COUNTER)
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
