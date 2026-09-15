"""Sole episode coordinator and durable Discord intent drainer.

Source intake never fetches prices or calls back into an All Swing watcher.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import re

from calendar import sessions_ago
from discord_forum import DiscordForumClient, DiscordForumError
from models import Episode, MarketState, SourceEvent
from render import WIB, escape, format_wib, render_history, render_primary_card, render_source_only_card, render_source_reply
from store import BoardStore, BoardStoreTransaction, StoreBlockedError


_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
             "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5}
_TARGET = re.compile(
    r"(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th) target"
    r"(?: [0-9][0-9.,]*)? (?:achieved|hit|reached)", re.IGNORECASE
)


def source_outcome_state(event: SourceEvent, active_plan: SourceEvent) -> MarketState | None:
    """Map explicit source confirmations, never suggestions or inferred prices."""
    if event.kind not in {"status", "reminder"} or active_plan.plan is None:
        return None
    status = (event.source_status or "").strip()
    if status.casefold() == "stop-loss hit":
        return MarketState.STOP_LOSS_BREACHED
    if status.casefold() == "all targets achieved":
        count = len(active_plan.plan.targets)
        return MarketState.from_target_number(min(count, 5))
    match = _TARGET.fullmatch(status)
    if match:
        number = _ORDINALS[match.group(1).casefold()]
        if number <= len(active_plan.plan.targets):
            return MarketState.from_target_number(number)
    return None


class BoardEngine:
    def __init__(self, store: BoardStore, client: DiscordForumClient) -> None:
        self.store = store
        self.client = client

    def submit(self, event: SourceEvent, now: datetime) -> str:
        """Persist source identity, then atomically decide and enqueue its effects.

        A replay resumes an intake interrupted before its decision committed.
        Completed identities return board_duplicate, including ignored events.
        """
        submitted = self.store.submit_event(event, now)
        with self.store.transaction() as tx:
            if tx.event_processed(submitted.id):
                return "board_duplicate"
            # An identity replay always uses the first immutable intake payload.
            event = tx.source_event(submitted.id)
            active = tx.active_episode(event.ticker)
            if event.kind == "social":
                self._social(tx, event, submitted.id, active, now)
                result = "board_submitted"
            elif event.kind == "buy":
                self._buy(tx, event, submitted.id, active, now)
                result = "board_submitted"
            elif active is not None and active.lifecycle == "primary":
                self._status(tx, event, submitted.id, active, now)
                result = "board_submitted"
            else:
                result = "board_ignored"
            tx.mark_event_processed(submitted.id, now)
            return result

    def _social(self, tx, event, event_id, active, now):
        if active is None:
            active = tx.create_episode(event.ticker, "source", event.source_title, event.published_at)
            active = replace(active, lifecycle_tag="Source plan")
            tx.update_episode(active)
            self._enqueue(tx, event, active, "create_thread", {
                "name": active.title, "content": render_source_only_card(active.title),
                "tag_names": ["Source plan"], "chart": None,
            }, now)
        else:
            tx.update_episode(replace(active, latest_material_at=max(active.latest_material_at, event.published_at)))
        self._source_reply(tx, event, active, now)

    def _buy(self, tx, event, event_id, active, now):
        event_date = event.published_at.astimezone(WIB).date()
        if active is not None and active.latest_material_at.astimezone(WIB).date() < sessions_ago(event_date, 20):
            # Close only the board's selection window. No synthetic resolution,
            # market fact, archive request, or retention message is produced.
            tx.finish_plan(active.id, now)
            tx.update_episode(replace(active, closed_at=now))
            active = None
        title = f"{event.ticker}: Buy"
        if active is None:
            active = tx.create_episode(event.ticker, "primary", title, event.published_at)
            active = replace(active, lifecycle_tag="Primary plan")
            tx.update_episode(active)
            tx.replace_plan(active.id, event_id, event, now)
            self._enqueue(tx, event, active, "create_thread", {
                "name": title, "content": render_primary_card(event),
                "tag_names": ["Primary plan"], "chart": event.media_path,
            }, now)
            return
        prior = tx.active_plan(active.id)
        promoted = active.lifecycle == "source"
        active = replace(active, lifecycle="primary", title=title, lifecycle_tag="Primary plan",
                         market_tag=None, latest_material_at=max(active.latest_material_at, event.published_at))
        tx.update_episode(active)
        tx.replace_plan(active.id, event_id, event, now)
        self._enqueue(tx, event, active, "edit_starter", {
            "content": render_primary_card(event), "chart": event.media_path,
            "clear_attachments": event.media_path is None,
        }, now)
        self._patch(tx, event, active, now)
        detail = ("Promoted to Primary plan" if promoted else
                  f"Replacement: prior source {prior.source_url}" if prior else "Replacement: Primary plan")
        self._history(tx, event, event_id, active, f"{detail}; new source {event.source_url}", now)

    def _status(self, tx, event, event_id, active, now):
        plan = tx.active_plan(active.id)
        if plan is None:
            raise StoreBlockedError("active primary episode is missing its plan")
        previous = plan.source_status or "New setup"
        current = event.source_status or previous
        state = source_outcome_state(event, plan)
        terminal = (current.strip().casefold() == "all targets achieved") or state == MarketState.STOP_LOSS_BREACHED or (
            state is not None and plan.plan is not None and
            state.value == f"TP{len(plan.plan.targets)} reached"
        )
        # Source confirmations may set the factual tag; generic status leaves it.
        active = replace(active, market_tag=state.value if state else active.market_tag,
                         latest_material_at=max(active.latest_material_at, event.published_at),
                         lifecycle="resolved" if terminal else "primary",
                         lifecycle_tag="Resolved" if terminal else "Primary plan",
                         closed_at=now if terminal else None)
        tx.set_source_status(active.id, current)
        tx.update_episode(active)
        self._source_reply(tx, event, active, now)
        checkpoint, last_valid = tx.latest_checkpoints(active.id)
        self._enqueue(tx, event, active, "edit_starter", {
            "content": render_primary_card(replace(plan, source_status=current), checkpoint, last_valid),
            "chart": None,
        }, now)
        self._patch(tx, event, active, now)
        detail = f"Source Status: {escape(previous)} to {escape(current)}; {event.source_url}"
        if terminal:
            tx.finish_plan(active.id, now)
            detail += f"; Resolved: {state.value}"
        if current != previous or terminal:
            self._history(tx, event, event_id, active, detail, now)

    def _source_reply(self, tx, event, active, now):
        self._enqueue(tx, event, active, "post_source_reply", {
            "content": render_source_reply(event), "media": event.media_path,
        }, now)

    def _patch(self, tx, event, active, now):
        tags = [active.lifecycle_tag]
        if active.market_tag:
            tags.append(active.market_tag)
        self._enqueue(tx, event, active, "patch_thread", {
            "name": active.title, "tag_names": tags, "archived": False,
        }, now)

    def _history(self, tx, event, event_id, active, detail, now):
        content = render_history(format_wib(event.published_at), detail)
        history_id = tx.add_history(active.id, event_id, content, now)
        self._enqueue(tx, event, active, "post_history_reply", {
            "content": content, "media": None, "history_id": history_id,
        }, now)

    @staticmethod
    def _enqueue(tx: BoardStoreTransaction, event: SourceEvent, active: Episode,
                 operation: str, payload: dict, now: datetime) -> None:
        dedupe_key = f"event:{event.event_key}:{operation}"
        tx.enqueue_outbox(operation, active.id, {**payload, "nonce_value": dedupe_key}, dedupe_key, now)

    def drain(self, now: datetime | None = None, *, limit: int = 100) -> int:
        """Execute due intents in episode order, retaining failures for retry."""
        if limit < 1:
            raise ValueError("drain limit must be positive")
        completed = 0
        for _ in range(limit):
            instant = now or datetime.now(timezone.utc)
            operation = self.store.claim_due_outbox(instant)
            if operation is None:
                break
            try:
                payload = dict(operation.payload)
                if operation.operation != "create_thread":
                    episode = self.store.episode(operation.episode_id)
                    if not episode.thread_id or not episode.starter_message_id:
                        raise StoreBlockedError("Discord thread identity is unavailable")
                    payload.update(thread_id=episode.thread_id, message_id=episode.starter_message_id)
                completion = self.client.execute(operation.operation, payload)
                if operation.operation == "create_thread" and not all(
                    completion.get(key) for key in ("thread_id", "starter_message_id")
                ):
                    raise DiscordForumError("Discord thread identity is unavailable")
                self.store.complete_outbox(operation.id, operation.claim_token, completion, instant)
                completed += 1
            except Exception as exc:
                # Store only a safe category, never provider bodies or credentials.
                self.store.fail_outbox(operation.id, operation.claim_token, type(exc).__name__, instant)
        return completed
