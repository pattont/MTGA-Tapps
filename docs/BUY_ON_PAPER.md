# Buy on Paper

**Buy on Paper** prices an Arena deck in paper and opens it in a store's cart
or deck builder. The button sits beside the Arena export on three screens:

- **Deck Finder**: in the selected deck's title row, next to Export to Arena.
- **Deck Manager**: in a saved deck's dialog header, next to Copy deck list.
- **Deck page**: in the heading of the Deck List & Card Performance section.
  It uses the newest submitted decklist, including a Brawl commander.

The dialog works like Moxfield's Buy dialog, without selling or a paper
collection. Pick a store, untick any card or board you already own, and the
total updates as you go. The tracker doesn't record what you own or buy.

Each store prices the cart from its own list where one exists. **Compare
stores** shows every store's total for the current selection; clicking a row
switches stores. When the store changes, each card's new price fades in one
row after another and the total counts to its new value. While a list loads,
prices shimmer.

| Store | Prices |
| --- | --- |
| TCGplayer | Scryfall's TCGplayer market price |
| Card Kingdom | Card Kingdom's published price list |
| Mana Pool | Mana Pool's published price list |
| StarCityGames, CoolStuffInc | No public list: the TCGplayer estimate, marked "est." |

## Store price lists

Card Kingdom (`api.cardkingdom.com/api/v2/pricelist`, about 70 MB) and Mana
Pool (`manapool.com/api/v1/prices/singles`, about 50 MB) publish their whole
singles lists as public JSON. That's too large to fetch in the browser each
time, and Mana Pool's list doesn't allow cross-origin reads.

Instead, `src/mtga_tracker/paper_prices.py` downloads each list on a background
thread when the dialog first asks for it, at most once a day. It stream-parses
the list with ijson and keeps each card's cheapest copy. In-stock copies come
first, then the lowest price across finishes and conditions. Not-tournament-legal
printings (Collectors' Edition, World Championship decks, 30th Anniversary,
oversized and art cards) are skipped. The result, about 8 MB, is saved as
`<data dir>/paper_prices/<store>.json`.

`GET /api/paper-prices?vendor=cardkingdom&name=…` answers in one of three ways:

- **`ready`** with the matched entries. A list older than a day still answers
  while it refreshes.
- **`loading`** (202) while the first download runs. The dialog polls.
- **`error`** (502). A failed download is retried after ten minutes at the
  earliest.

Names match on the full name or any face, because Card Kingdom names
double-faced cards by their front face.

In the dialog, a card the chosen store doesn't list keeps its TCGplayer
estimate, tagged "Not listed · TCGplayer est.". A card the store lists but has
sold out is tagged "Sold out" and priced at its listing. The summary counts
both.

## TCGplayer prices (Scryfall)

TCGplayer prices come from Scryfall in the browser, the same dependency the card
art and mana-cost lookups use. Scryfall also decides which cards have no paper
printing. `ui/src/cardPrices.ts` makes two passes:

1. One `/cards/collection` request per 75 names shows which cards exist and
   gives a first price from Scryfall's default printing.
2. Searches of up to 20 cards each, such as
   `(!"Opt" or !"Negate") game:paper lang:en -is:oversized -set_type:memorabilia`
   sorted by `usd`, find each card's cheapest English paper printing. That
   printing's price replaces the first one. Basic lands get their own search,
   because their hundreds of printings would push pricier cards onto later
   result pages.

A 60-card deck takes about four requests. Scryfall limits search and
collection requests to 2 per second, and a 429 locks the caller out. Its 429
has no CORS header, so the browser reports it as a network error.
`ui/src/scryfallQueue.ts` spaces these requests, and after any failure it
pauses Scryfall calls for a minute. The dialog then keeps the first-pass
prices and offers **Try again**. Settled results are cached in localStorage
for 24 hours, the interval at which Scryfall updates prices.

Scryfall's `usd` prices are TCGplayer market prices. Cards are shown as follows:

- **Arena-only cards** (no paper printing) are labeled and left out of the cart.
- **Rebalanced `A-` cards** map to the paper original, which has the original
  card text.
- **Cards that exist only as foil promos** get that printing's price.

## Stores

`ui/src/paperVendors.ts` holds one entry per store. These formats match what
EDHREC and Cube Cobra send today:

| Store | How the list gets there | Affiliate parameter |
| --- | --- | --- |
| TCGplayer | `store.tcgplayer.com/massentry?c=` with entries joined by `\|\|`. With set codes on, each entry reads `qty Name [SET] number`. | Impact tracking link with the Mass Entry URL as `u` |
| Card Kingdom | `cardkingdom.com/builder?c=`, one card per line | `partner` (in-house program) |
| Mana Pool | `manapool.com/add-deck?deck=`, the list as UTF-8 base64 | `ref` |
| StarCityGames | The list is copied to the clipboard and the deck builder opens for pasting | none found |
| CoolStuffInc | The list is copied to the clipboard and the deck builder opens for pasting | none found |

StarCityGames and CoolStuffInc document no way to prefill their deck builders.
Someone needs to inspect their forms in a browser before a direct handoff is
added. Double-faced and split cards are sent by their front face name.

## Turning on affiliate links

Fill in `AFFILIATE` in `ui/src/paperVendors.ts`. An empty value sends a plain
link. A store whose code is set gets the tracked link, and the dialog then
shows a commission disclosure for that store.

- **TCGplayer**: join through Impact. See the
  [affiliate docs](https://docs.tcgplayer.com/docs/tcgplayer-affiliate-program).
  Set the tracking link without a query, for example
  `https://partner.tcgplayer.com/c/<publisher>/1830156/21018`, and copy the
  exact IDs from the Impact dashboard.
- **Card Kingdom**: there's no public signup page; ask Card Kingdom for a
  partner code.
- **Mana Pool**: apply at [affiliates.manapool.com](https://affiliates.manapool.com).

The affiliate code is in the page source, so anyone running a build can see it.
That's normal for affiliate links.
