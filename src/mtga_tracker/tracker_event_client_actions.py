"""Client-to-GRE action and payload extraction helpers."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


class TrackerClientActionsMixin:
    """Focused event helpers used by TrackerEventsMixin."""

    def _extract_game_state_events(self, line: str) -> List[Dict[str, Any]]:
        """Return ordered game-state events from one raw log line."""
        extract_many = getattr(self.parser, "extract_game_state_events", None)
        if callable(extract_many):
            events = extract_many(line)
            if isinstance(events, list):
                return [event for event in events if isinstance(event, dict)]
        single = self.parser.extract_card_events(line)
        if isinstance(single, dict):
            return [single]
        return []

    def _extract_client_gre_payloads(self, line: str) -> List[Dict[str, Any]]:
        """Return ordered client-to-GRE payloads from one raw log line."""
        extract_many = getattr(self.parser, "extract_client_gre_payloads", None)
        if callable(extract_many):
            payloads = extract_many(line)
            if isinstance(payloads, list):
                return [payload for payload in payloads if isinstance(payload, dict)]
        data = self.parser.parse_json_from_line(line)
        if not isinstance(data, dict):
            return []
        direct = data.get("clientToGreMessage")
        if isinstance(direct, dict):
            payload = direct.get("payload")
            if isinstance(payload, dict):
                return [{"type": "client_gre_message", "data": payload}]
            if direct.get("type"):
                return [{"type": "client_gre_message", "data": direct}]
        if data.get(
            "clientToMatchServiceMessageType"
        ) == "ClientToMatchServiceMessageType_ClientToGREMessage" and isinstance(
            data.get("payload"), dict
        ):
            return [{"type": "client_gre_message", "data": data["payload"]}]
        return []

    def _extract_gre_messages(self, line: str) -> List[Dict[str, Any]]:
        """Return ordered GRE-to-client messages from one raw log line."""
        data = self.parser.parse_json_from_line(line)
        if not isinstance(data, dict):
            return []
        gre_event = data.get("greToClientEvent")
        if not isinstance(gre_event, dict):
            return []
        messages = gre_event.get("greToClientMessages")
        if not isinstance(messages, list):
            return []
        return [message for message in messages if isinstance(message, dict)]

    @staticmethod
    def _as_list(value: Any) -> List[Any]:
        """Return value as a list, accepting Arena's singular-or-list response shapes."""
        if isinstance(value, list):
            return value
        if value is None:
            return []
        return [value]

    def _capture_casting_time_options_requests(self, message: Dict[str, Any]) -> None:
        """Remember modal-option prompts so client responses can be logged with card names."""
        if message.get("type") != "GREMessageType_CastingTimeOptionsReq":
            return
        game_state_id = message.get("gameStateId")
        options_req = message.get("castingTimeOptionsReq") or {}
        for option in self._as_list(options_req.get("castingTimeOptionReq")):
            if not isinstance(option, dict):
                continue
            if option.get("castingTimeOptionType") != "CastingTimeOptionType_Modal":
                continue
            cto_id = option.get("ctoId")
            modal_req = option.get("modalReq") or {}
            selected_options = [
                modal_option.get("grpId")
                for modal_option in self._as_list(modal_req.get("modalOptions"))
                if isinstance(modal_option, dict) and modal_option.get("grpId") is not None
            ]
            if game_state_id is None or cto_id is None:
                continue
            self.game_state.pending_modal_requests[(int(game_state_id), int(cto_id))] = {
                "source_grp_id": option.get("grpId"),
                "affected_id": option.get("affectedId"),
                "player_id": option.get("playerIdToPrompt"),
                "ability_grp_id": modal_req.get("abilityGrpId"),
                "modal_options": selected_options,
            }

    def _store_submitted_deck(
        self,
        deck_cards: List[Any],
        sideboard_cards: List[Any],
    ) -> None:
        """Keep the latest authoritative deck submission for the next game."""
        parsed_deck = [int(card) for card in deck_cards]
        parsed_sideboard = [int(card) for card in sideboard_cards]
        self._pending_submitted_deck_cards = parsed_deck
        self._pending_submitted_sideboard_cards = parsed_sideboard
        if not self.game_state.in_match or (
            not self.game_state.match_complete
            and self.game_state.last_turn_announced <= 0
        ):
            self.game_state.submitted_deck_cards = parsed_deck.copy()
            self.game_state.submitted_sideboard_cards = parsed_sideboard.copy()

    def _capture_submitted_deck_message(self, message: Dict[str, Any]) -> None:
        """Capture the deck bundled with Arena's game connection response.

        Also reads the Bo3 intermission SubmitDeckReq: it carries the deck as
        sideboarded for the NEXT game (validated against real logs), which is
        the only single-line source for post-board decklists — without it,
        games 2+ would persist the match's original 60.
        """
        message_type = message.get("type")
        if message_type == "GREMessageType_SubmitDeckReq":
            deck = (message.get("submitDeckReq") or {}).get("deck") or {}
            deck_cards = deck.get("deckCards")
            sideboard_cards = deck.get("sideboardCards")
            if isinstance(deck_cards, list) and deck_cards:
                self._store_submitted_deck(
                    deck_cards,
                    sideboard_cards if isinstance(sideboard_cards, list) else [],
                )
            return
        if message_type != "GREMessageType_ConnectResp":
            return
        connect_response = message.get("connectResp") or {}
        deck_message = connect_response.get("deckMessage") or {}
        deck_cards = deck_message.get("deckCards")
        sideboard_cards = deck_message.get("sideboardCards")
        if isinstance(deck_cards, list):
            self._store_submitted_deck(
                deck_cards,
                sideboard_cards if isinstance(sideboard_cards, list) else [],
            )

    def _mode_text(self, ability_grp_id: int) -> Optional[str]:
        """Return concise display text for one selected modal ability."""
        get_text = getattr(self.card_db, "get_ability_text", None)
        raw_text = get_text(int(ability_grp_id)) if callable(get_text) else None
        text = self._normalize_ability_text(raw_text)
        if not text:
            return None
        text = re.sub(r"\s+", " ", text.replace("•", " ")).strip()
        return text

    def _handle_casting_time_options_response(self, payload: Dict[str, Any]) -> None:
        """Log selected modal choices from local client responses."""
        game_state_id = payload.get("gameStateId")
        options_resp = payload.get("castingTimeOptionsResp") or {}
        for option in self._as_list(options_resp.get("castingTimeOptionResp")):
            if not isinstance(option, dict):
                continue
            if option.get("castingTimeOptionType") != "CastingTimeOptionType_Modal":
                continue
            cto_id = option.get("ctoId")
            if game_state_id is None or cto_id is None:
                continue
            key = (int(game_state_id), int(cto_id))
            if key in self.game_state.logged_modal_choices:
                continue
            request = self.game_state.pending_modal_requests.get(key) or {}
            selected_grp_ids = [
                int(grp_id)
                for grp_id in self._as_list((option.get("chooseModalResp") or {}).get("grpIds"))
                if grp_id is not None
            ]
            mode_texts = [text for grp_id in selected_grp_ids if (text := self._mode_text(grp_id))]
            if not mode_texts:
                continue
            source_grp_id = request.get("source_grp_id")
            card_name = (
                self.card_db.get_card_name(int(source_grp_id))
                if source_grp_id is not None
                else "modal spell"
            )
            seat_id = self.game_state.player_seat_id or request.get("player_id")
            self.game_state.logged_modal_choices.add(key)
            self._print_event(
                self._format_actor_event(
                    "",
                    seat_id,
                    f"chose modes for [{card_name}]: {'; '.join(mode_texts)}",
                    turn_override=self._event_turn_number(seat_id),
                ),
                "ability",
            )

    def _handle_client_gre_payload(self, payload_event: Dict[str, Any]) -> None:
        """Handle client-to-GRE responses that improve mulligan/opening-hand tracking."""
        payload = payload_event.get("data", {})
        if not isinstance(payload, dict):
            return
        normalized = payload_event.get("normalized")
        normalized = normalized if isinstance(normalized, dict) else {}
        payload_type = str(payload.get("type", ""))

        if payload_type == "ClientMessageType_CastingTimeOptionsResp":
            self._handle_casting_time_options_response(payload)
            return

        if payload_type == "ClientMessageType_MulliganResp":
            decision = str(
                normalized.get("decision")
                or (payload.get("mulliganResp") or {}).get("decision", "")
            )
            self.game_state.opening_mulligan_prompt_seen = True
            if decision in {"mulligan", "MulliganOption_Mulligan"}:
                self.game_state.explicit_mulligan_count += 1
                self.game_state.opening_keep_confirmed = False
                self.game_state.opening_select_n_ids = []
            elif decision in {"keep", "MulliganOption_AcceptHand"}:
                self.game_state.opening_keep_confirmed = True
                self._finalize_confirmed_opening_hand_candidate()
            return

        if (
            payload_type == "ClientMessageType_SubmitDeckResp"
            or normalized.get("type") == "submit_deck_resp"
        ):
            deck_cards = normalized.get("deck_cards")
            sideboard_cards = normalized.get("sideboard_cards")
            if isinstance(deck_cards, list):
                self._store_submitted_deck(
                    deck_cards,
                    sideboard_cards if isinstance(sideboard_cards, list) else [],
                )
            return

        if payload_type != "ClientMessageType_SelectNResp":
            return
        if self.game_state.opening_hand_capture_closed:
            return
        if self.game_state.last_turn_announced > 0:
            return
        if not (
            self.game_state.opening_keep_confirmed or self.game_state.explicit_mulligan_count > 0
        ):
            return
        select_resp = payload.get("selectNResp") or {}
        ids = (
            normalized.get("selected_object_ids")
            or select_resp.get("selectedObjectIds")
            or select_resp.get("ids")
        )
        if not isinstance(ids, list):
            return
        parsed_ids: List[int] = []
        for value in ids:
            try:
                parsed_ids.append(int(value))
            except (TypeError, ValueError):
                continue
        if parsed_ids:
            self.game_state.opening_select_n_ids = parsed_ids
            self._finalize_opening_hand_after_bottom_selection()
