import json

import mtga_tracker.card_database as cdb
from mtga_tracker import card_art, replay_builder as rb


def test_tile_art_prefers_the_image_server_then_the_printing(tmp_path, monkeypatch):
    cache = tmp_path / "scryfall_id_cache.json"
    cache.write_text(json.dumps({"fin|30": "494e68e9-ecba-4482-82bc-207ad59144c1"}))
    monkeypatch.setattr(rb, "_scryfall_cache_path", lambda: cache)
    index = {
        95884: ("Restoration Magic", "FIN", "30"),
        106487: ("Ajani Unrelenting", "FRA", "242"),
        7: ("Fable of the Mirror-Breaker // Reflection of Kiki-Jiki", "NEO", "141"),
    }
    monkeypatch.setattr(card_art, "_index", None)
    monkeypatch.setattr(cdb.CardDatabase, "export_index_by_arena_id", lambda self: index)

    # A cached printing goes straight to the image server (no API request limit).
    assert card_art.tile_art(95884) == {
        "art_url": "https://cards.scryfall.io/art_crop/front/4/9/494e68e9-ecba-4482-82bc-207ad59144c1.jpg",
        "art_print": "fin/30",
    }
    # A new set not in the cache yet: its set/number, never a name lookup first.
    assert card_art.tile_art(106487) == {"art_url": None, "art_print": "fra/242"}
    # A pasted list has no ids: the card name finds a printing, by front face too.
    assert card_art.tile_art(None, "Restoration Magic")["art_print"] == "fin/30"
    assert card_art.tile_art(None, "Fable of the Mirror-Breaker")["art_print"] == "neo/141"
    # A list's own printing comes first.
    assert card_art.tile_art(None, "Restoration Magic", "FRA", "9")["art_print"] == "fra/9"
    assert card_art.tile_art(None, "No Such Card") == {"art_url": None, "art_print": None}
