# Active implementation plans

Reviewed against the source on 2026-09-10. This folder contains unfinished
work; the root README describes delivered behavior and links to reference
or operational documentation only.

| Plan | Current status | Remaining work |
| --- | --- | --- |
| [Linux support](linux_implementation.md) | Not implemented as a supported distribution | Prefix discovery/rotation, tray-free controller, overlay, packaging and desktop validation |
| [Install discovery](MTGA_INSTALL_DISCOVERY.md) | Unity-header discovery and Settings path display implemented | Editable overrides/validation; evidence-driven platform fallbacks |
| [Surveil and scry validation](SCRY_TRACKING.md) | Scry implemented, migration 29 present | Surveil log capture/handler/UI and real opponent-scry validation |
| [Opponent deck matching](opponent_deck_research.md) | Proposal; no corpus/matcher tables or modules | Evidence-aware matching against cached decklists; review observed-copy assumptions first |
| [Format legality](valid_cards_per_format.md) | Proposal; no legality cache/filter | Revalidate data source and historical legality semantics before implementation |

The completed release plan was replaced by [the release guide](../RELEASING.md).
The completed overlay plan was removed; [the overlay guide](../../overlay/README.md)
and changelog describe the actual implementation. The old plan included
superseded choices (off by default, its own tray, no card art, known-top
odds) and unverified performance targets; those are not outstanding promises.
Original `overlay-mockup.html` and `overlay-mockup.png` remain as historical
visual assets, not implementation specifications.

When a plan is completed, move durable behavioral information into the
appropriate reference, record the delivered feature in the changelog, remove
the obsolete plan, and update this index and its incoming links. Partially
completed plans should describe only the remaining work and link to the
current behavior for context.
