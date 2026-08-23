"""Settings dialog for the menu-bar app.

Two tabs: "Deck AI" (provider / API key / model for opponent-deck
identification) and "Deck Finder" (the creator lists the Moxfield,
Aetherhub, and TCGplayer sites follow).
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import deck_llm

#: (internal name, display label, settings key for the key, settings key for the model, default model)
_PROVIDERS = (
    ("openai", "OpenAI", "CHATGPT_API_KEY", "DECK_LLM_OPENAI_MODEL", "gpt-4o-mini"),
    ("claude", "Anthropic (Claude)", "CLAUDE_API_KEY", "DECK_LLM_CLAUDE_MODEL", "claude-3-5-haiku-20241022"),
    ("gemini", "Gemini", "GEMINI_API_KEY", "DECK_LLM_GEMINI_MODEL", "gemini-2.0-flash"),
)

#: (config key, tab label) for the Deck Finder creator lists.
_CREATOR_SITES = (
    ("moxfield", "Moxfield:"),
    ("aetherhub", "Aetherhub:"),
    ("tcgplayer", "TCGplayer:"),
)


class DeckAISettingsDialog(QDialog):
    """Tracker settings: Deck AI identification and Deck Finder creators.

    Deck AI values save into the "deck_ai" section of settings.json in the
    tracker data dir; a running tracker picks the change up on the next game
    (no restart). Creator lists save into deckfinder_config.json.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("MTGA Tracker Settings")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_deck_ai_tab(), "Deck AI")
        tabs.addTab(self._build_deck_finder_tab(), "Deck Finder")
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_deck_ai_values()
        self._creators_loaded = self._load_creator_fields()

    # ------------------------------------------------------------------
    # Deck AI tab

    def _build_deck_ai_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        intro = QLabel(
            "Identify your opponent's deck with an AI provider. One small, "
            "cheap request per completed game — tracking never waits on it."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.enabled_box = QCheckBox("Enable AI deck identification")
        form.addRow(self.enabled_box)

        self.provider_combo = QComboBox()
        for _internal, label, _k, _m, _d in _PROVIDERS:
            self.provider_combo.addItem(label)
        form.addRow("Provider:", self.provider_combo)

        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("API key")
        self.key_edit.setMinimumHeight(30)
        form.addRow("API key:", self.key_edit)

        self.model_edit = QLineEdit()
        self.model_edit.setMinimumHeight(30)
        form.addRow("Model:", self.model_edit)
        layout.addLayout(form)

        note = QLabel(
            "OpenAI, Anthropic, and Gemini keys are supported. The key is "
            "stored in settings.json (top level of the tracker folder, next "
            "to config.py) and is only ever sent to the provider you choose."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(note)
        layout.addStretch(1)
        return tab

    def _load_deck_ai_values(self) -> None:
        # Per-provider field values, kept while the user switches providers.
        self._keys: Dict[str, str] = {}
        self._models: Dict[str, str] = {}
        stored = deck_llm.load_settings()
        for internal, _label, key_name, model_name, _default in _PROVIDERS:
            # Prefill from settings.json first, then whatever config.py/env
            # currently resolves to, so existing setups show up as-is.
            self._keys[internal] = str(
                stored.get(key_name) or deck_llm._get_api_key(internal) or ""
            )
            self._models[internal] = str(stored.get(model_name) or deck_llm._get_model(internal) or "")

        self.enabled_box.setChecked(deck_llm.is_deck_llm_enabled())
        current = deck_llm._get_provider()
        index = next((i for i, p in enumerate(_PROVIDERS) if p[0] == current), 0)
        self.provider_combo.setCurrentIndex(index)
        self._showing = _PROVIDERS[index][0]
        self._load_provider_fields(index)
        self.provider_combo.currentIndexChanged.connect(self._provider_changed)

    def _load_provider_fields(self, index: int) -> None:
        internal, _label, _key_name, _model_name, default_model = _PROVIDERS[index]
        self.key_edit.setText(self._keys.get(internal, ""))
        self.model_edit.setText(self._models.get(internal, ""))
        self.model_edit.setPlaceholderText(default_model)

    def _stash_current_fields(self) -> None:
        self._keys[self._showing] = self.key_edit.text().strip()
        self._models[self._showing] = self.model_edit.text().strip()

    def _provider_changed(self, index: int) -> None:
        self._stash_current_fields()
        self._showing = _PROVIDERS[index][0]
        self._load_provider_fields(index)

    # ------------------------------------------------------------------
    # Deck Finder tab

    def _build_deck_finder_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        intro = QLabel(
            "Which creators the Deck Finder's Moxfield, Aetherhub, and "
            "TCGplayer sites follow. One creator per line. Add a short "
            "display name after a pipe — “Ashlizzlle | Ash” makes imported "
            "decks show up as “Jeskai Artifacts (Ash)” in Arena."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self._creator_edits: Dict[str, QPlainTextEdit] = {}
        for key, label in _CREATOR_SITES:
            edit = QPlainTextEdit()
            edit.setTabChangesFocus(True)
            edit.setMinimumHeight(110)
            edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self._creator_edits[key] = edit
            form.addRow(label, edit)
        layout.addLayout(form)
        return tab

    def _load_creator_fields(self) -> bool:
        """Prefill the creator editors; False disables them on error."""
        try:
            from .deckfinder_api import read_creator_config

            config = read_creator_config()
        except Exception:
            for edit in self._creator_edits.values():
                edit.setEnabled(False)
                edit.setPlaceholderText("Deck Finder configuration unavailable")
            return False
        for key, edit in self._creator_edits.items():
            lines = []
            for creator in config.get(key) or []:
                name = str(creator.get("name") or "").strip()
                if not name:
                    continue
                short = str(creator.get("short_name") or "").strip()
                lines.append(f"{name} | {short}" if short else name)
            edit.setPlainText("\n".join(lines))
            # Size each box to its content so nothing scrolls out of view.
            line_count = max(len(lines) + 1, 4)
            metrics = edit.fontMetrics()
            edit.setMinimumHeight(min(line_count * metrics.lineSpacing() + 18, 320))
        return True

    def _creator_entries(self, key: str) -> List[Dict[str, Optional[str]]]:
        entries: List[Dict[str, Optional[str]]] = []
        for line in self._creator_edits[key].toPlainText().splitlines():
            name, _, short = line.partition("|")
            name = name.strip()
            if not name:
                continue
            entries.append({"name": name, "short_name": short.strip() or None})
        return entries

    def _save_creators(self) -> None:
        if not self._creators_loaded:
            return
        try:
            from .deckfinder_api import write_creator_config

            write_creator_config(
                {key: self._creator_entries(key) for key in self._creator_edits}
            )
        except Exception:
            # Creator-list problems must never block saving the AI settings.
            pass

    # ------------------------------------------------------------------
    # Save

    def _save(self) -> None:
        self._stash_current_fields()
        index = self.provider_combo.currentIndex()
        internal, _label, key_name, model_name, default_model = _PROVIDERS[index]
        values: Dict[str, object] = {
            "DECK_LLM_ENABLED": self.enabled_box.isChecked(),
            "DECK_LLM_PROVIDER": internal,
            key_name: self._keys.get(internal, ""),
            model_name: self._models.get(internal, "") or default_model,
        }
        # Keep edits the user made to non-selected providers too.
        for other, _l, other_key, other_model, _d in _PROVIDERS:
            if other != internal:
                if self._keys.get(other):
                    values[other_key] = self._keys[other]
                if self._models.get(other):
                    values[other_model] = self._models[other]
        deck_llm.save_settings(values)
        self._save_creators()
        self.accept()


def open_settings_dialog(parent: Optional[QWidget] = None) -> bool:
    """Show the Settings dialog modally; True when the user saved."""
    dialog = DeckAISettingsDialog(parent)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    return dialog.exec() == QDialog.DialogCode.Accepted
