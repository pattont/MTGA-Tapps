# Flood impact (functional flood)

Status: planned, not built. Requested in community feedback after 0.7.4.

## Goal

Draw Quality says whether a game saw more lands than the deck should see (Flood)
and whether the lands came in an unlikely run (Land streak). Neither says whether
those lands **hurt**. A player who discards lands to hand attack, or who needs
seven mana for their finisher, can see many lands and lose nothing.

Flood impact would estimate, for one game, whether extra lands cost the player
something, with a confidence level. It would sit beside Flood on Game Detail as
its own finding. It would never replace or change Flood, Land streak or Mana
Screw, and it would not feed the deck page's Normal / Flood / Screw split until
it has been validated.

## Ground rule: measure against the deck, not a fixed number

Decks need very different amounts of mana. A low-curve aggro deck is hurt by its
fifth land; a ramp or control deck with 7–10 mana cards needs those lands. Any
rule of the form "N lands in hand is flood" is wrong for one of them.

**Rejected: a mana ceiling from printed costs.** An earlier draft counted a land
as extra once the player had enough lands for the deck's most expensive card.
Printed mana value doesn't say what a deck needs. Many expensive cards cost far
less in play:
- Emrakul-style cards turn lands into extra mana.
- Some costs drop for each Forest you control.
- Some drop for the total power of your creatures, or how many creatures you have.
- Affinity, convoke, delve and similar mechanics change the cost too.

Reading all of that from card text is not reliable, so the plan must not depend
on what cards cost on paper.

Two directions that don't read card costs, to compare during validation:

1. **What the player actually did.** Replay rows record every land tapped, so
   the mana used each turn is observed, cost reductions included. Signals are
   built from behavior: lands left in hand turn after turn while lands in play
   also sit untapped, and turns whose only new card was a land that changed
   nothing. Held-up mana (instants, flash) is the main false positive here.
2. **The deck's own history.** Compare this game to the same deck's other
   recorded games: lands in hand and untapped lands per turn, and how they
   relate to winning. A deck that always ends with lands to spare is built that
   way; the finding is when a game is clearly worse than that deck's normal.
   This needs enough recorded games per deck (a minimum to be agreed), and says
   nothing for a new deck.

If neither holds up in the hand review below, the honest outcome is to not ship
this feature.

## Data

Only games recorded with replay data (`games.replay_version` not NULL) have what
this needs: the hand at every point, land plays, taps and untaps. The replay
stream (`replay_builder.replay_for_game`, about 8 ms per game once card facts
are cached) already models the opening hand, mulligan bottoms, draws, casts,
discards and taps. Older games get no Flood impact at all rather than a guess
from the text timeline. In the development database, 121 of 1,231 games are
recorded; every new game is.

Per own turn, at the moment the opponent's turn starts:

- lands in play, lands in hand, nonland cards in hand (with their mana values);
- whether a land was played this turn and what this turn's draw was;
- untapped lands left over;
- lands discarded this turn (to the player's own or the opponent's effects).

The last turn of the game is skipped: the game ended inside it.

## Candidate signals

Signals should come from what happened rather than from card costs:

- turns ending with lands in hand and lands in play left untapped, while no
  nonland card left the hand that turn;
- the same pattern repeating over consecutive turns (one quiet turn is normal);
- how far this game sits from the same deck's usual numbers, when the deck has
  enough recorded games.

Counted as **useful**, never flood: lands discarded to an effect (discard
fodder), lands sacrificed or exiled for value, and lands tapped for an
activated ability.

Verdict: **Hurt**, **Some** or **None**, with a **confidence** (High / Medium /
Low). Confidence depends on:
- how many turns the player had;
- how many recorded games the deck has to compare against;
- whether the stream has limitations;
- whether any hand card was unknown.

Thresholds come from validation, not from this document.

## Risks to resolve before building

- **Held-up mana.** Untapped lands with instants in hand look like waste.
  Signal 2 only counts turns with no castable nonland card, but flash creatures
  and counterspells kept for the opponent's turn need checking.
- **Modal double-faced cards** (spell // land) and pathway lands: counted by the
  face actually played. A spell // land kept in hand is not a dead land.
- **Landfall and land-count payoffs** turn extra lands into value without tapping
  them. The deck-history comparison should absorb this; check it on such decks.
- **New or rarely played decks** have no history to compare against; behavior
  signals alone, at lower confidence, or nothing.
- **Mulligans and cards put back**: rely on the stream's opening-hand handling;
  confirm on recorded mulligan games.

## Validation before shipping

1. Compute the per-turn snapshots for every recorded game in a copy of a real
   database, read-only, and print them beside the replay for a sample of games
   flagged Hurt, Some and None.
2. Review at least 30 games by hand across aggro, midrange, control and ramp,
   including Brawl, and agree on thresholds from that review.
3. Check that Flood-with-no-impact and Hurt-without-Flood games read sensibly
   (the second can happen: a normal land count can still strand a hand).
4. Only then show it on Game Detail, with the reasons and the confidence spelled
   out, and decide separately whether deck pages should summarize it.

## Where it would go

- A new `src/mtga_tracker/flood_impact.py` that walks a replay stream (and the
  deck's other recorded games for the comparison), with focused tests using
  small streams.
- `game_detail` adds `flood_impact` for recorded games, computed with a
  read-only connection and never allowed to fail the page.
- Game Detail → Draw Quality: a "Flood impact" card and an evidence line, e.g.
  "Hurt (high confidence): 4 of 9 turns ended with lands stuck in hand and
  mana unused, more than this deck's usual 1".
