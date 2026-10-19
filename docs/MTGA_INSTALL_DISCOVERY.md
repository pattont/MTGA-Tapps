# Finding Arena files

The tracker finds `Player.log` and Arena's local card database through `src/mtga_tracker/paths.py`. It looks in the standard macOS and Windows log folders and, for the card database, the install locations reported by Arena and the available Steam libraries or Epic installation. The Settings page shows the resolved paths. On Windows, Steam libraries outside the default Program Files location are included.

If the log cannot be found, first open Arena and enable **Detailed Logs (Plugin Support)** in its Account options, then restart Arena. A source run can pass `--log-path` to point to a specific `Player.log`. `MTGA_DATA_DIR` overrides the card-data search directory when Arena's card database is installed elsewhere. The log parser does not depend on the card database for game results, but local card names, colors and mana costs may be incomplete without it.

The [remaining discovery plan](plans/MTGA_INSTALL_DISCOVERY.md) covers editable overrides and further platform fallbacks. Keep OS-specific path logic in `paths.py`.
