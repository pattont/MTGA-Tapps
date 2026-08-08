from __future__ import annotations

import contextlib
import io
import unittest

from mtga_deck_downloader import __main__ as cli


class CLITests(unittest.TestCase):
    def test_diagnostics_loads_packaged_contract_without_network(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = cli.main(["--diagnose"])

        rendered = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("Providers (6):", rendered)
        self.assertIn("aetherhub.com", rendered)
        self.assertIn("magic.gg", rendered)
        self.assertIn("moxfield.com", rendered)
        self.assertIn("mtgo.com", rendered)
        self.assertIn("tcgplayer.com", rendered)
        self.assertIn("untapped.gg", rendered)


if __name__ == "__main__":
    unittest.main()
