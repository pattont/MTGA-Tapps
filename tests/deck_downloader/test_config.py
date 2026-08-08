from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mtga_deck_downloader import config as config_module


class ConfigTests(unittest.TestCase):
    def test_load_config_supports_moxfield_short_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "MoxfieldNames": [
                            {"Name": "Ashlizzlle", "ShortName": "Ash"},
                            "SwayzeMTG",
                        ],
                        "AtherhubCreators": [
                            {"Name": "MTGMalone", "ShortName": "Malone"},
                        ],
                        "TcgplayerCreators": [
                            {"Name": "Arne Huschenbeth", "ShortName": "Arne"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            config = config_module.load_config(config_path)

        self.assertEqual(
            [(creator.name, creator.short_name, creator.label) for creator in config.moxfield_creators],
            [
                ("Ashlizzlle", "Ash", "Ash"),
                ("SwayzeMTG", None, "SwayzeMTG"),
            ],
        )
        self.assertEqual(config.moxfield_names, ("Ashlizzlle", "SwayzeMTG"))
        self.assertEqual(
            [(creator.name, creator.short_name, creator.label) for creator in config.aetherhub_creators],
            [("MTGMalone", "Malone", "Malone")],
        )
        self.assertEqual(
            [(creator.name, creator.short_name, creator.label) for creator in config.tcgplayer_creators],
            [("Arne Huschenbeth", "Arne", "Arne")],
        )

    def test_explicit_config_path_wins(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text('{"MoxfieldNames": ["Explicit"]}', encoding="utf-8")

            resolved = config_module.resolve_config_path(config_path)
            config = config_module.load_config(config_path)

        self.assertEqual(resolved, config_path.resolve())
        self.assertEqual(config.moxfield_names, ("Explicit",))


if __name__ == "__main__":
    unittest.main()
