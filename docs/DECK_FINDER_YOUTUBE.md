# YouTube creators in Deck Finder

Choose **youtube.com → Creators** in Deck Finder, then **Hello Good Game** or
**Sloth**. The tracker checks the latest 15 public entries in that channel's
Videos tab sorted by Latest. Separate Shorts and Live tabs are not scanned.
Videos without a usable decklist in their description are skipped; the tracker
does not keep walking older videos to fill the table.

No API key, YouTube account, browser extension, or extra executable is needed.
Opening Deck Finder loads only site metadata and local creator configuration;
it does not contact YouTube. Scraper libraries and HTTP clients initialize on
first use. Selecting a YouTube creator starts the video lookup.
Fetching runs in a background job with a simple loading message. Opening a
result uses its already fetched list. **Export to Arena** copies the import
text; **Source** opens the original video.

## Add another creator

In **Settings → Deck Finder Creators → YouTube**, enter one creator per line:

```text
@HelloGoodGame | HGG
@SlothMtg | Sloth
https://www.youtube.com/@AnotherCreator | Short name
```

Channel URLs ending in `/videos` and canonical `/channel/UC…` URLs also work.
The short name is optional; without one, the channel's display name is used
for the import suffix. Removing every line removes every YouTube creator.

The shared `deckfinder_config.json` stores these as `YouTubeCreators` entries
with `Channel`, `Name`, and `ShortName`. Existing configs without that key get
HGG and Sloth by default. An explicit empty array disables the defaults. Older
settings save payloads that omit YouTube preserve its existing configuration.

## Titles and import text

Description headings `Deck`, `Decklist`, and `Deck list` are accepted without
case sensitivity and with an optional colon. The exported main-deck heading
is always `Deck`. Explicit Commander, Companion, and Sideboard sections, card
quantities, apostrophes, Unicode names, and Arena set/collector fields are
preserved. Trailing hashtags, links, prose, and video chapter timestamps are
excluded. Incomplete or ambiguous lists produce a warning rather than a guessed
or combined list.

Imported deck names remove Unicode emoji and trailing platform/format segments,
including `| MTG Arena Standard` and `| Reality Fracture MTG Arena`. Meaningful
pipes and ordinary Unicode text in the title remain. The creator suffix is
appended once: `Ramp 5 Lands at Once (HGG)` or `Example Deck (Sloth)`.
YouTube titles can change; the tracker uses the current fetched title.

YouTube has a Creators picker rather than a Bo1/Bo3 selector. Display format is
read from explicit title/description text and stays Unknown when unavailable;
a sideboard does not imply Bo3. Parsing does not verify current format legality.

## Speed, caching, and failures

The channel page supplies the ordered video IDs and public client context.
The tracker reads small player-metadata responses with three workers, each
reusing its own HTTP connection. If the full description is missing, it falls
back to embedded JSON in the public watch page. No media is downloaded.
The metadata endpoint is unofficial, so changes or rate limits can interrupt
retrieval. Requests have timeouts and a per-channel lookup budget.

Live local checks on 2026-09-30 returned 15 usable lists each from HGG and Sloth
in approximately 0.9 and 0.7 seconds. These are observations, not guaranteed
load times. The dashboard reuses its existing **10-minute memory cache**;
restarting clears it, and **Refresh** fetches again. No disk cache is created.

When some videos fail, completed lists remain available with a warning. Such
partial results are not cached as a successful complete scan. If every read
fails, Deck Finder shows an error. A successful scan without any usable lists
shows an empty table.

## Developer validation

Fixtures for both motivating descriptions live in
`tests/deck_downloader/fixtures/youtube/`; each contains 60 main-deck cards.
Parser, listing, metadata fallback, creator ownership, settings compatibility,
cache/refresh, and UI regression coverage runs in the normal Python/frontend
suites described in AGENTS.md. Provider discovery includes YouTube in the
frozen-build fallback list; the terminal `--deck-finder` mode uses the same
provider and parser.
