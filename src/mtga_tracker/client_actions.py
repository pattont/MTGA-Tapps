"""Normalize client-to-GRE actions from MTGA logs."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .log_json import parse_nested_json_field


def parse_client_action(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return a normalized client action from a parsed log payload."""
    if not isinstance(data, dict):
        return None
    if _is_client_ui_message(data):
        return {"type": "client_ui_message", "raw": data}

    payload = _inner_payload(data)
    if not isinstance(payload, dict):
        return None

    message_type = str(payload.get("type", ""))
    if message_type == "ClientMessageType_MulliganResp":
        decision = str((payload.get("mulliganResp") or {}).get("decision", ""))
        return {
            "type": "mulligan_resp",
            "decision": _normalize_mulligan_decision(decision),
            "raw_decision": decision,
            "game_state_id": payload.get("gameStateId"),
            "resp_id": payload.get("respId"),
            "raw": payload,
        }
    if message_type == "ClientMessageType_SelectNResp":
        select_resp = payload.get("selectNResp") or {}
        selected_object_ids = _int_list(
            select_resp.get("selectedObjectIds")
            or select_resp.get("ids")
            or select_resp.get("objectIds")
        )
        selected_option_ids = _int_list(select_resp.get("selectedOptionIds"))
        return {
            "type": "select_n_resp",
            "selected_object_ids": selected_object_ids,
            "selected_option_ids": selected_option_ids,
            "game_state_id": payload.get("gameStateId"),
            "resp_id": payload.get("respId"),
            "raw": payload,
        }
    if message_type == "ClientMessageType_SubmitDeckResp":
        submit_resp = payload.get("submitDeckResp") or {}
        deck = submit_resp.get("deck") or {}
        return {
            "type": "submit_deck_resp",
            "deck_cards": _int_list(deck.get("deckCards")),
            "sideboard_cards": _int_list(deck.get("sideboardCards")),
            "game_state_id": payload.get("gameStateId"),
            "resp_id": payload.get("respId"),
            "raw": payload,
        }
    return {
        "type": "generic_client_action",
        "message_type": message_type,
        "raw": payload,
    }


def _inner_payload(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    direct = data.get("clientToGreMessage")
    if isinstance(direct, dict):
        payload = direct.get("payload")
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str):
            parsed = parse_nested_json_field(direct, "payload")
            return parsed if isinstance(parsed, dict) else None
        if direct.get("type"):
            return direct

    payload = data.get("payload")
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        parsed = parse_nested_json_field(data, "payload")
        return parsed if isinstance(parsed, dict) else None
    if data.get("type"):
        return data
    return None


def _normalize_mulligan_decision(raw: str) -> str:
    if raw == "MulliganOption_Mulligan":
        return "mulligan"
    if raw == "MulliganOption_AcceptHand":
        return "keep"
    return raw


def _int_list(value: Any) -> list[int]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    parsed = []
    for item in values:
        try:
            parsed.append(int(item))
        except (TypeError, ValueError):
            continue
    return parsed


def _is_client_ui_message(data: Dict[str, Any]) -> bool:
    text = str(data.get("clientToMatchServiceMessageType") or data.get("type") or "")
    return "ClientToGREUIMessage" in text
