"""Tests for text-based removal / board-wipe / mass-bounce classification."""

from mtga_tracker.removal_classifier import (
    ROLE_BOUNCE,
    ROLE_REMOVAL,
    ROLE_WIPE,
    RemovalClassifier,
    classify_ability_texts,
)


def test_targeted_destroy_is_removal():
    assert classify_ability_texts(["Destroy target creature."]) == {ROLE_REMOVAL}
    assert classify_ability_texts(["Exile target permanent."]) == {ROLE_REMOVAL}
    assert classify_ability_texts(["Destroy up to two target creatures."]) == {ROLE_REMOVAL}


def test_damage_based_removal():
    # Lightning Strike-style: damage to any target counts as removal.
    assert classify_ability_texts(["Lightning Strike deals 3 damage to any target."]) == {
        ROLE_REMOVAL
    }
    assert classify_ability_texts(["Deals 5 damage to target creature."]) == {ROLE_REMOVAL}
    assert classify_ability_texts(["Target creature gets -3/-3 until end of turn."]) == {
        ROLE_REMOVAL
    }
    assert classify_ability_texts(["This creature fights target creature you don't control."]) == {
        ROLE_REMOVAL
    }


def test_board_wipes():
    # Day of Judgment
    assert classify_ability_texts(["Destroy all creatures."]) == {ROLE_WIPE}
    # Damage sweepers are conditional — judged by outcome at runtime
    # (2026-08-29 ruling): threshold_wipe, not a plain wipe.
    assert classify_ability_texts(["Deals 3 damage to each creature."]) == {"threshold_wipe"}
    # Split Up: a state-qualified sweeper usually kills half a board, not the
    # board — ruled REMOVAL, not wipe (2026-08-29 design review).
    assert classify_ability_texts(
        ["Choose one — Destroy all tapped creatures. Destroy all untapped creatures."]
    ) == {ROLE_REMOVAL}
    # Mass exile clears the board no matter the destination zone.
    assert classify_ability_texts(["Exile all creatures."]) == {ROLE_WIPE}
    # Mass -X/-X only wipes what its number can kill — conditional.
    assert classify_ability_texts(["All creatures get -2/-2 until end of turn."]) == {"threshold_wipe"}


def test_mass_bounce_is_its_own_role():
    assert classify_ability_texts(
        ["Return all creatures to their owners' hands."]
    ) == {ROLE_BOUNCE}
    assert classify_ability_texts(
        ["Return each nonland permanent to its owner's hand."]
    ) == {ROLE_BOUNCE}


def test_wipe_wins_over_removal_for_modal_cards():
    roles = classify_ability_texts(
        ["Choose one — Destroy target creature. Destroy all creatures."]
    )
    assert roles == {ROLE_WIPE}


def test_non_removal_text_classifies_empty():
    assert classify_ability_texts(["Draw two cards."]) == frozenset()
    assert classify_ability_texts(["Destroy target land."]) == frozenset()
    assert classify_ability_texts([]) == frozenset()
    # Creature pump is not removal.
    assert classify_ability_texts(["Target creature gets +2/+2 until end of turn."]) == frozenset()


class _FakeCardDb:
    def __init__(self, texts_by_grp):
        self.texts_by_grp = texts_by_grp
        self.calls = 0

    def get_card_ability_texts(self, grp_id):
        self.calls += 1
        return self.texts_by_grp.get(grp_id, [])


def test_classifier_caches_per_grp():
    db = _FakeCardDb({7: ["Destroy target creature."]})
    classifier = RemovalClassifier(db)
    assert classifier.roles_for(7) == {ROLE_REMOVAL}
    assert classifier.roles_for(7) == {ROLE_REMOVAL}
    assert db.calls == 1
    assert classifier.roles_for(None) == frozenset()


def test_counter_magic_classification():
    from mtga_tracker.removal_classifier import ROLE_COUNTER

    # Hard counter.
    assert classify_ability_texts(["Counter target spell."]) == {ROLE_COUNTER}
    # Soft counter — still counter magic; landing is tracked from game events.
    assert classify_ability_texts(
        ["Counter target spell unless its controller pays {2}."]
    ) == {ROLE_COUNTER}
    assert classify_ability_texts(["Counter target noncreature spell."]) == {ROLE_COUNTER}
    assert classify_ability_texts(["Counter target activated ability."]) == {ROLE_COUNTER}
    # Counters-the-counters wording.
    assert classify_ability_texts(
        ["When you cast this spell, counter it unless you pay {1}."]
    ) == {ROLE_COUNTER}
    # "Counter" as in +1/+1 counters must NOT classify.
    assert classify_ability_texts(["Put a +1/+1 counter on target creature."]) == frozenset()

def test_targeted_bounce_is_bounce():
    assert classify_ability_texts(
        ["Return target creature to its owner's hand."]
    ) == {ROLE_BOUNCE}
    assert classify_ability_texts(
        ["Return up to two target nonland permanents to their owners' hands."]
    ) == {ROLE_BOUNCE}
    # Land bounce and graveyard recursion stay out.
    assert classify_ability_texts(["Return target land to its owner's hand."]) == frozenset()
    assert classify_ability_texts(
        ["Return target creature card from your graveyard to your hand."]
    ) == frozenset()


def test_graveyard_hate_is_not_removal():
    """"Exile target card from a graveyard" counted as removal for months —
    battlefield removal never targets a "card", only zone effects do."""
    from mtga_tracker.removal_classifier import classify_ability_texts

    assert classify_ability_texts(["{2}: Exile target card from a graveyard."]) == frozenset()
    assert classify_ability_texts(["Destroy target card in a graveyard."]) == frozenset()
    # Real battlefield removal still classifies.
    assert "removal" in classify_ability_texts(["Exile target creature."])
    assert "removal" in classify_ability_texts(["Destroy target nonblack creature."])


def test_design_review_rulings_2026_08():
    """The 2026-08-29 classification review (docs/REMOVAL_CLASSIFICATION.md)."""
    from mtga_tracker.removal_classifier import classify_ability_texts as c

    # Edicts are removal (Strategic Betrayal, Tribute to Hunger).
    assert "removal" in c(["Target opponent exiles a creature they control and their graveyard."])
    assert "removal" in c(["Target opponent sacrifices a creature of their choice."])
    assert "removal" in c(["Each opponent sacrifices a nontoken creature of their choice."])
    # State-qualified sweeps are removal, not wipes (Split Up).
    assert c(["Choose one —\n• Destroy all tapped creatures.\n• Destroy all untapped creatures."]) == frozenset({"removal"})
    # Unconditional wipes stay wipes; conditional sweepers are judged by
    # outcome (threshold_wipe) per the later 2026-08-29 refinement.
    assert "wipe" in c(["Destroy all artifacts and creatures. End the turn."])
    assert c(["Desolation of Smaug deals 3 damage to each non-Dragon creature."]) == frozenset({"threshold_wipe"})
    # Land destruction stays out, even nonbasic (Demolition Field).
    assert c(["{2}, {T}, Sacrifice this land: Destroy target nonbasic land an opponent controls."]) == frozenset()
    # O-Ring temporary exile is removal; self-blink is not.
    assert "removal" in c(["When this enchantment enters, exile up to one other target nonland permanent until this enchantment leaves the battlefield."])
    assert "removal" in c(["Choose target creature an opponent controls. Exile that creature until this creature leaves the battlefield."])
    assert c(["When this creature enters, exile up to one other target creature you control. Return that card to the battlefield at the beginning of the next end step."]) == frozenset()
    # Airbend is bounce, targeted or mass.
    assert "bounce" in c(["When Aang enters, airbend up to one other target creature or spell."])
    assert "bounce" in c(["Choose up to one target creature, then airbend all other creatures."])
    # Subset mass bounce is bounce (Aetherize).
    assert "bounce" in c(["Return all attacking creatures to their owner's hand."])
    # Hand disruption is not removal.
    assert c(["Target opponent exiles a card from their hand."]) == frozenset()


def test_threshold_sweepers_are_their_own_role():
    """Conditional sweepers (Fire Magic, Desolation of Smaug, mass -X/-X) are
    judged by outcome at runtime — classified threshold_wipe, not wipe.
    Unconditional destruction stays a plain wipe: no toughness beats Ultima."""
    from mtga_tracker.removal_classifier import classify_ability_texts as c

    assert c(["Fire Magic deals 4 damage to each creature."]) == frozenset({"threshold_wipe"})
    assert c(["Desolation of Smaug deals 3 damage to each non-Dragon creature."]) == frozenset({"threshold_wipe"})
    assert c(["All creatures get -2/-2 until end of turn."]) == frozenset({"threshold_wipe"})
    assert c(["Destroy each non-Human creature."]) == frozenset({"threshold_wipe"})
    assert c(["Destroy all artifacts and creatures. End the turn."]) == frozenset({"wipe"})
    assert c(["Exile all creatures."]) == frozenset({"wipe"})
