"""Turn and game-state update helpers for tracker events."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set


class TrackerTurnStateMixin:
    """Focused event helpers used by TrackerEventsMixin."""

    def _has_gameplay_annotations(self, data: Dict[str, Any]) -> bool:
        """Return True when annotations indicate gameplay has started (not mulligan setup)."""
        annotations = data.get("annotations", [])
        if not isinstance(annotations, list):
            return False
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            ann_types = annotation.get("type", [])
            if not isinstance(ann_types, list):
                ann_types = [ann_types] if ann_types else []
            if any(
                ann in ann_types
                for ann in (
                    "AnnotationType_AttackerDeclared",
                    "AnnotationType_BlockerDeclared",
                    "AnnotationType_Damage",
                    "AnnotationType_DamageDealt",
                )
            ):
                return True
            if "AnnotationType_ZoneTransfer" in ann_types:
                category = self._annotation_category(annotation)
                if category in {
                    "PlayLand",
                    "CastSpell",
                    "PlaySpell",
                    "Resolve",
                    "Draw",
                    "Destroy",
                    "Exile",
                    "Countered",
                    "Sacrifice",
                    "Discard",
                    "Mill",
                }:
                    return True
        return False

    def _has_mulligan_prompt_in_state(self, data: Dict[str, Any]) -> bool:
        """Best-effort signal for mulligan/keep prompt presence in gameState payload."""
        if self.game_state.opening_mulligan_prompt_seen:
            return True
        players = data.get("players", [])
        if not isinstance(players, list):
            return False
        for player in players:
            if not isinstance(player, dict):
                continue
            pending = (
                player.get("pendingMessageType")
                or player.get("pendingMessage")
                or player.get("pendingDecisionType")
            )
            if pending is None:
                continue
            pending_text = str(pending).lower()
            if "mulligan" in pending_text or "choosestartingplayer" in pending_text:
                return True
        return False

    def _has_new_turn_action_annotations(self, data: Dict[str, Any]) -> bool:
        """Return True when payload likely contains real actions from the newly active turn."""
        annotations = data.get("annotations", [])
        if not isinstance(annotations, list):
            return False
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            ann_types = annotation.get("type", [])
            if not isinstance(ann_types, list):
                ann_types = [ann_types] if ann_types else []
            if "AnnotationType_ZoneTransfer" in ann_types:
                category = self._annotation_category(annotation)
                if category in {"PlayLand", "CastSpell", "PlaySpell", "Resolve", "Draw"}:
                    return True
        return False

    def _has_resolution_annotations(self, data: Dict[str, Any]) -> bool:
        """Return True when a payload includes stack resolution annotations."""
        annotations = data.get("annotations", [])
        if not isinstance(annotations, list):
            return False
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            ann_types = annotation.get("type", [])
            if not isinstance(ann_types, list):
                ann_types = [ann_types] if ann_types else []
            if "AnnotationType_ResolutionStart" in ann_types:
                return True
        return False

    def _refresh_game_state_metadata(self, data: Dict[str, Any]) -> None:
        """Refresh non-turn metadata from a game-state payload."""
        self._remove_deleted_instances(data.get("diffDeletedInstanceIds"))
        self._snapshot_game_objects(data.get("gameObjects", []))
        self._observe_battlefield_creatures(data)
        self._capture_starting_deck_totals(data)
        self._update_format_from_game_state(data)
        self._update_commanders_from_game_state(data)
        self._seed_initial_life_totals(data)
        self._maybe_print_seat_resolution()
        self._maybe_print_pregame_commander_lines()

    def _detect_turn_change(self, turn_num: Optional[int], active_player: Optional[int]) -> bool:
        """Return True when a turn payload should produce a new turn header."""
        if turn_num and turn_num > self.game_state.turn_number:
            if active_player is not None and active_player != self.game_state.active_player:
                return True
            if self.game_state.active_player is None:
                return True
        return bool(
            turn_num == 1 and self.game_state.last_turn_announced < 1 and active_player is not None
        )

    def _warn_on_missing_initial_turns(self, turn_num: Optional[int], seats_known: bool) -> None:
        """Emit a diagnostic when tracking starts after the first turn."""
        if not (
            turn_num is not None
            and turn_num > 2
            and self.game_state.last_turn_announced == 0
            and seats_known
        ):
            return
        missed_turns = list(range(1, turn_num))
        missing_text = ", ".join(str(t) for t in missed_turns[:3])
        if len(missed_turns) > 3:
            missing_text += ", ..."
        self._print_event(
            f"⚠️ First observed turn is {turn_num}; earlier turn(s) ({missing_text}) were not present in the captured log stream.",
            "turn",
        )

    def _queue_turn_header(self, turn_num: int, active_player: Optional[int]) -> None:
        """Queue or flush deferred turn headers for the current turn owner."""
        header = self._turn_header_snapshot(turn_num, active_player)
        if turn_num == 1 and self.game_state.last_turn_announced < 1:
            if active_player == self.game_state.player_seat_id:
                self.game_state.pending_player_turn_header = header
            else:
                self.game_state.pending_opponent_turn_header = header
        elif turn_num > self.game_state.last_turn_announced:
            if active_player == self.game_state.player_seat_id:
                self._flush_pending_opponent_turn_header()
                self.game_state.pending_player_turn_header = header
            else:
                self._flush_pending_player_turn_header()
                self.game_state.pending_opponent_turn_header = header

    def _update_turn_context(self, data: Dict[str, Any]) -> tuple[bool, bool]:
        """Update turn, phase, and deferred-header state."""
        if "turnInfo" not in data:
            return False, False
        turn_info = data["turnInfo"]
        turn_num = turn_info.get("turnNumber")
        active_player = turn_info.get("activePlayer")
        phase = turn_info.get("phase", "")
        step = turn_info.get("step", "")
        seats_known = self.game_state.player_seat_id in (
            1,
            2,
        ) and self.game_state.opponent_seat_id in (1, 2)
        turn_changed = self._detect_turn_change(turn_num, active_player)

        if turn_num is not None:
            self.game_state.turn_number = turn_num
        if active_player is not None:
            self.game_state.active_player = active_player
        if phase:
            self.game_state.phase = phase
        if step:
            self.game_state.step = step

        if (
            turn_num == 1
            and self.game_state.first_player_seat is None
            and active_player is not None
        ):
            self.game_state.first_player_seat = active_player

        self._warn_on_missing_initial_turns(turn_num, seats_known)
        exited_combat_this_update = self._update_combat_phase(phase)

        if turn_changed and turn_num:
            self.game_state.reported_attack_keys = {
                k
                for k in self.game_state.reported_attack_keys
                if isinstance(k, tuple) and k and k[0] >= int(turn_num) - 1
            }

        if turn_changed and seats_known:
            self._queue_turn_header(int(turn_num), active_player)

        return turn_changed, exited_combat_this_update

    def _update_game_state(self, data: Dict[str, Any]):
        """Update the tracked game state from event data."""
        # Process turn info and print turn header FIRST so "Turn N - YOUR TURN" appears
        # before card plays and life changes from this same message.
        self._refresh_game_state_metadata(data)
        previous_attack_target_ids, previous_attack_sources_by_target = (
            self._previous_attack_context()
        )
        turn_changed, exited_combat_this_update = self._update_turn_context(data)
        life_updates = self._collect_life_updates(data)
        late_life_turn_override = self._late_life_turn_override(
            data,
            turn_changed=turn_changed,
            exited_combat_this_update=exited_combat_this_update,
            previous_attack_target_ids=previous_attack_target_ids,
            life_updates=life_updates,
        )
        self.game_state.recent_attack_sources_by_target = previous_attack_sources_by_target
        if (
            life_updates
            and late_life_turn_override is None
            and self._has_resolution_annotations(data)
        ):
            self._deferred_life_updates = (life_updates, late_life_turn_override)
        else:
            self._apply_life_updates(life_updates, late_life_turn_override)

    def _turn_header_snapshot(self, turn_num: int, active_player: Optional[int]) -> tuple:
        """Capture the visible life totals at the moment a turn header is queued."""
        return (
            turn_num,
            active_player,
            self.game_state.player_life,
            self.game_state.opponent_life,
        )

    def _pending_turn_header_parts(self, pending: tuple) -> tuple[int, Optional[int], int, int]:
        """Return pending-header fields, accepting legacy two-field test tuples."""
        turn_num = pending[0]
        active_player = pending[1] if len(pending) > 1 else None
        player_life = pending[2] if len(pending) > 2 else self.game_state.player_life
        opponent_life = pending[3] if len(pending) > 3 else self.game_state.opponent_life
        return turn_num, active_player, player_life, opponent_life

    def _flush_pending_opponent_turn_header(self) -> None:
        """Print and clear deferred 'Turn N - OPPONENT'S TURN' header if set.

        Called at start of _process_annotation (so opponent actions appear under the
        correct header) and before announcing 'Turn N - YOUR TURN' (so we don't
        skip the opponent turn header when opponent passed with no actions).
        """
        pending = self.game_state.pending_opponent_turn_header
        if not pending:
            return
        turn_num, active_player, player_life, opponent_life = self._pending_turn_header_parts(
            pending
        )
        self.game_state.pending_opponent_turn_header = None
        self.game_state.last_turn_announced = turn_num
        if active_player == self.game_state.opponent_seat_id:
            self.game_state.last_opponent_turn_number = turn_num
            self.game_state.turns_taken_by_seat.setdefault(int(active_player), set()).add(
                int(turn_num)
            )
        self._print_line(f"\n{'='*75}")
        self._print_event(f"Turn {turn_num} - OPPONENT'S TURN", "turn")
        self._print_line(f"Life: You {player_life} - {opponent_life} Opponent")
        self._print_line(f"{'='*75}\n")

    def _flush_pending_player_turn_header(self) -> None:
        """Print and clear deferred 'Turn N - YOUR TURN' header if set."""
        pending = self.game_state.pending_player_turn_header
        if not pending:
            return
        turn_num, active_player, player_life, opponent_life = self._pending_turn_header_parts(
            pending
        )
        self.game_state.pending_player_turn_header = None
        self.game_state.last_turn_announced = turn_num
        if active_player == self.game_state.player_seat_id:
            self.game_state.last_player_turn_number = turn_num
            self.game_state.turns_taken_by_seat.setdefault(int(active_player), set()).add(
                int(turn_num)
            )
        self._print_line(f"\n{'='*75}")
        self._print_event(f"Turn {turn_num} - YOUR TURN", "turn")
        self._print_line(f"Life: You {player_life} - {opponent_life} Opponent")
        self._print_line(f"{'='*75}\n")

    def _flush_pending_turn_header_for_seat(self, seat_id: Optional[int]) -> None:
        """Flush deferred turn header for the side that owns the current event."""
        if seat_id == self.game_state.player_seat_id:
            self._flush_pending_player_turn_header()
        elif seat_id == self.game_state.opponent_seat_id:
            self._flush_pending_opponent_turn_header()

    def _flush_pending_active_turn_header(self) -> Optional[int]:
        """Flush the pending header for the active turn and return its turn number."""
        active_player = self.game_state.active_player
        if (
            active_player == self.game_state.player_seat_id
            and self.game_state.pending_player_turn_header
        ):
            turn_num = self._pending_turn_header_parts(self.game_state.pending_player_turn_header)[
                0
            ]
            self._flush_pending_player_turn_header()
            return turn_num
        if (
            active_player == self.game_state.opponent_seat_id
            and self.game_state.pending_opponent_turn_header
        ):
            turn_num = self._pending_turn_header_parts(
                self.game_state.pending_opponent_turn_header
            )[0]
            self._flush_pending_opponent_turn_header()
            return turn_num
        return None
