"""Diagnostic logging helpers for CardTracker."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .log_sanitize import scrub_raw_log


class TrackerDiagnosticsMixin:
    """Unhandled annotation and parser diagnostic helpers used by CardTracker."""

    def _append_diagnostic_log(self, message: str, annotation: Dict[str, Any]) -> None:
        """Best-effort append of unhandled mechanics to a text diagnostic file."""
        path = getattr(self, "_diagnostic_text_path", None)
        if path is None:
            return
        try:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(f"{datetime.now().isoformat()} {message}\n")
                handle.write(f"annotation={json.dumps(annotation, sort_keys=True, default=str)}\n")
        except (OSError, TypeError, ValueError):
            return

    def _append_parser_diagnostic_log(self, body: str) -> None:
        """Best-effort append of unknown parser entries without UI noise."""
        path = getattr(self, "_diagnostic_text_path", None)
        if path is None:
            return
        try:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            first_line = scrub_raw_log(str(body or "")).splitlines()[0] if body else ""
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(f"{datetime.now().isoformat()} Tracker: unknown log entry\n")
                handle.write(f"entry={first_line[:500]}\n")
        except (OSError, TypeError, ValueError):
            return

    @staticmethod
    def _annotation_signature(annotation: Dict[str, Any]) -> tuple:
        """Return stable signature used to dedupe unhandled-annotation diagnostics."""
        ann_type = annotation.get("type", [])
        if not isinstance(ann_type, list):
            ann_type = [ann_type] if ann_type else []
        details = annotation.get("details", [])
        detail_keys = tuple(
            sorted(
                str(detail.get("key"))
                for detail in details
                if isinstance(detail, dict) and detail.get("key")
            )
        )
        category = None
        for detail in details:
            if isinstance(detail, dict) and detail.get("key") == "category":
                values = detail.get("valueString", [])
                if isinstance(values, list) and values:
                    category = values[0]
                break
        return (
            tuple(sorted(str(item) for item in ann_type if item)),
            str(category or ""),
            detail_keys,
        )

    def _log_unhandled_annotation(
        self,
        annotation: Dict[str, Any],
        *,
        game_objects_by_id: Optional[Dict[int, Dict[str, Any]]] = None,
        note: Optional[str] = None,
    ) -> None:
        """Emit one-time diagnostics for annotation patterns the tracker does not yet model."""
        signature = self._annotation_signature(annotation)
        if signature in self.game_state.logged_unhandled_annotations:
            return
        self.game_state.logged_unhandled_annotations.add(signature)

        ann_types, category, detail_keys = signature
        parts = [", ".join(ann_types) if ann_types else "unknown annotation"]
        if category:
            parts.append(f"category={category}")
        if detail_keys:
            parts.append(f"keys={','.join(detail_keys)}")
        if note:
            parts.append(note)

        affected_ids = annotation.get("affectedIds", [])
        if isinstance(affected_ids, list) and affected_ids:
            instance_id = affected_ids[0]
            obj = self._lookup_object(instance_id, game_objects_by_id)
            name = self._object_display_name(obj, instance_id)
            if name and not name.startswith("ID "):
                parts.append(f"affected=[{name}]")

        message = "Tracker: unhandled annotation - " + " | ".join(parts)
        self._append_diagnostic_log(message, annotation)
