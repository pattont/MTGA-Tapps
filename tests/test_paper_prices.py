"""Buy on Paper store price lists: indexing, cache lifetime and the endpoint.

Offline: downloads are replaced by fixture rows, so nothing reaches a store.
"""

import json
import threading

import pytest

from mtga_tracker import paper_prices


CARD_KINGDOM_ROWS = [
    {
        "name": "Opt",
        "sku": "INV-064",
        "edition": "Invasion",
        "variation": "",
        "is_foil": "false",
        "price_retail": "1.99",
        "qty_retail": 44,
        "url": "mtg/invasion/opt",
    },
    {
        "name": "Opt",
        "sku": "DOM-060",
        "edition": "Dominaria",
        "variation": "",
        "is_foil": "false",
        "price_retail": "0.35",
        "qty_retail": 20,
        "url": "mtg/dominaria/opt",
    },
    # Cheaper, but sold out: in-stock copies win.
    {
        "name": "Opt",
        "sku": "FXLN-065",
        "edition": "Ixalan",
        "variation": "",
        "is_foil": "true",
        "price_retail": "0.25",
        "qty_retail": 0,
        "url": "mtg/ixalan/opt-foil",
    },
    # Card Kingdom names a double-faced card by its front face.
    {
        "name": "Fable of the Mirror-Breaker",
        "sku": "NEO-141",
        "edition": "Kamigawa: Neon Dynasty",
        "variation": "",
        "is_foil": "false",
        "price_retail": "9.49",
        "qty_retail": 8,
        "url": "mtg/neo/fable",
    },
    {
        "name": "Lightning Bolt",
        "sku": "FM10-146",
        "edition": "Magic 2010",
        "variation": "",
        "is_foil": "true",
        "price_retail": "7.99",
        "qty_retail": 0,
        "url": "mtg/m10/bolt-foil",
    },
    # Not a playable printing.
    {
        "name": "Lightning Bolt",
        "sku": "CED-161",
        "edition": "Collectors' Edition",
        "variation": "",
        "is_foil": "false",
        "price_retail": "0.50",
        "qty_retail": 3,
        "url": "mtg/ced/bolt",
    },
]

MANA_POOL_ROWS = [
    {
        "name": "Opt",
        "set_code": "DOM",
        "number": "60",
        "available_quantity": 1927,
        "price_cents": 15,
        "price_cents_foil": 36,
        "price_cents_etched": None,
        "url": "https://manapool.com/card/dom/60/opt",
    },
    {
        "name": "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki",
        "set_code": "NEO",
        "number": "141",
        "available_quantity": 20,
        "price_cents": 547,
        "price_cents_foil": 410,
        "price_cents_etched": None,
        "url": "https://manapool.com/card/neo/141/fable",
    },
    {
        "name": "Unpriced",
        "set_code": "XYZ",
        "number": "1",
        "available_quantity": 0,
        "price_cents": None,
        "price_cents_foil": None,
        "price_cents_etched": None,
        "url": None,
    },
]


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_prices, "DATA_DIR", tmp_path)
    paper_prices._reset_for_tests()
    yield tmp_path
    paper_prices._reset_for_tests()


def fake_download(rows, meta=None, calls=None):
    def download(vendor, workdir):
        if calls is not None:
            calls.append(vendor)
        return (
            meta
            or {"created_at": "2026-10-18 19:08:27", "base_url": "https://www.cardkingdom.com/"},
            iter(rows),
            None,
        )

    return download


def wait_for_refresh(vendor="cardkingdom"):
    for thread in threading.enumerate():
        if thread.name == f"paper-prices-{vendor}":
            thread.join(timeout=5)


def test_card_kingdom_index_prefers_in_stock_then_cheapest_and_skips_memorabilia():
    index = paper_prices.build_index(
        paper_prices._card_kingdom_entries(CARD_KINGDOM_ROWS, "https://www.cardkingdom.com/")
    )
    opt = index["opt"]
    assert (opt["usd"], opt["set"], opt["collector_number"], opt["finish"], opt["in_stock"]) == (
        0.35,
        "DOM",
        "60",
        "nonfoil",
        True,
    )
    assert opt["url"] == "https://www.cardkingdom.com/mtg/dominaria/opt"
    # The only playable Bolt is sold out: still listed, flagged out of stock.
    bolt = index["lightning bolt"]
    assert (bolt["set"], bolt["finish"], bolt["in_stock"]) == ("M10", "foil", False)

    found = paper_prices.lookup(
        index, ["Fable of the Mirror-Breaker // Reflection of Kiki-Jiki", "Nope"]
    )
    assert found["Fable of the Mirror-Breaker // Reflection of Kiki-Jiki"]["usd"] == 9.49
    assert found["Nope"] is None


def test_mana_pool_index_uses_the_cheapest_finish_and_matches_face_names():
    index = paper_prices.build_index(paper_prices._mana_pool_entries(MANA_POOL_ROWS, ""))
    assert index["opt"]["usd"] == 0.15
    fable = paper_prices.lookup(index, ["Fable of the Mirror-Breaker"])[
        "Fable of the Mirror-Breaker"
    ]
    assert (fable["usd"], fable["finish"], fable["set"]) == (4.1, "foil", "NEO")
    assert "unpriced" not in index


def test_first_request_loads_in_the_background_then_serves_from_the_cache_file(isolated_cache):
    calls = []
    status, body = paper_prices.get_prices(
        "cardkingdom", ["Opt", "Opt", " "], download=fake_download(CARD_KINGDOM_ROWS, calls=calls)
    )
    assert (status, body["status"]) == (202, "loading")
    wait_for_refresh()

    status, body = paper_prices.get_prices(
        "cardkingdom", ["Opt"], download=fake_download([], calls=calls)
    )
    assert status == 200
    assert body["as_of"] == "2026-10-18 19:08:27"
    assert body["prices"]["Opt"]["usd"] == 0.35
    assert calls == ["cardkingdom"]

    # A restart reads the cache file instead of downloading again.
    cached = json.loads((isolated_cache / "paper_prices" / "cardkingdom.json").read_text())
    assert cached["cards"]["opt"]["set"] == "DOM"
    paper_prices._reset_for_tests()
    status, body = paper_prices.get_prices(
        "cardkingdom", ["Opt"], download=fake_download([], calls=calls)
    )
    assert status == 200 and body["stale"] is False
    assert calls == ["cardkingdom"]


def test_a_stale_list_still_answers_while_it_refreshes():
    paper_prices.get_prices("cardkingdom", [], download=fake_download(CARD_KINGDOM_ROWS))
    wait_for_refresh()
    later = paper_prices.time.time() + paper_prices.REFRESH_SECONDS + 1
    calls = []
    status, body = paper_prices.get_prices(
        "cardkingdom", ["Opt"], now=later, download=fake_download(CARD_KINGDOM_ROWS, calls=calls)
    )
    assert status == 200 and body["stale"] is True and body["prices"]["Opt"]["usd"] == 0.35
    wait_for_refresh()
    assert calls == ["cardkingdom"]


def test_a_failed_download_is_reported_and_not_retried_at_once():
    attempts = []

    def failing(vendor, workdir):
        attempts.append(vendor)
        raise OSError("network down")

    assert paper_prices.get_prices("manapool", ["Opt"], download=failing)[0] == 202
    wait_for_refresh("manapool")
    status, body = paper_prices.get_prices("manapool", ["Opt"], download=failing)
    assert status == 502 and "network down" in body["error"]
    assert attempts == ["manapool"]


def test_unknown_vendor_and_route():
    assert paper_prices.get_prices("starcitygames", ["Opt"])[0] == 404
    assert paper_prices.handle_get("/api/other", {}) is None
