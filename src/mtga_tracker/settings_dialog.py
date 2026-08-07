"""Settings dialog for the menu-bar app (Deck AI provider / key / model)."""

from __future__ import annotations

from typing import Dict, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
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


class DeckAISettingsDialog(QDialog):
    """Configure the AI opponent-deck identification.

    Saves into the "deck_ai" section of settings.json in the tracker data
    dir; a running tracker picks the change up on the next game (no restart).
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("MTGA Tracker Settings")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
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
        form.addRow("API key:", self.key_edit)

        self.model_edit = QLineEdit()
        form.addRow("Model:", self.model_edit)
        layout.addLayout(form)

        note = QLabel(
            "OpenAI, Anthropic, and Gemini keys are supported. The key is "
            "stored in settings.json in your tracker data folder and is only "
            "ever sent to the provider you choose."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

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
        self.accept()


def open_settings_dialog(parent: Optional[QWidget] = None) -> bool:
    """Show the Settings dialog modally; True when the user saved."""
    dialog = DeckAISettingsDialog(parent)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    return dialog.exec() == QDialog.DialogCode.Accepted
