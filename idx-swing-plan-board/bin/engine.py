"""Sole episode coordinator and durable Discord intent drainer.

Source intake never fetches prices or calls back into an All Swing watcher.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import re

from calendar import is_idx_trading_day, sessions_ago
from discord_forum import DiscordForumClient, DiscordForumError, DiscordRateLimitError, DiscordRejectedError
from models import Checkpoint, Episode, MarketState, SourceEvent
from media_store import acquire_media
from prices import classify_close, fetch_session_close, parse_plan_levels
from render import WIB, render_primary_card, render_source_only_card, render_source_replies, primary_card_requires_source_reply
from store import BoardStore, BoardStoreTransaction, StoreBlockedError


_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
             "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "6th": 6}
_TARGET = re.compile(
    r"(first|second|third|fourth|fifth|sixth|[0-9]+(?:st|nd|rd|th)) target"
    r"(?: [0-9][0-9.,]*)? (?:achieved|hit|reached)", re.IGNORECASE
)


def _source_confirmations(event: SourceEvent, active_plan: SourceEvent) -> tuple[bool, set[int]]:
    if event.kind not in {"status", "reminder"} or active_plan.plan is None:
        return False, set()
    reached: set[int] = set()
    stopped = False
    for fragment in re.split(r"[;\n]+", event.source_status or ""):
        status = " ".join(fragment.strip().rstrip(".").split()).casefold()
        if re.fullmatch(r"stop[- ]?loss(?: [0-9][0-9.,]*)? (?:hit|breached)", status):
            stopped = True
        elif re.fullmatch(r"all targets (?:achieved|hit|reached)", status):
            reached.add(len(active_plan.plan.targets))
        elif match := _TARGET.fullmatch(status):
            ordinal = match.group(1).casefold()
            reached.add(_ORDINALS[ordinal] if ordinal in _ORDINALS else int(ordinal[:-2]))
        elif match := re.fullmatch(r"(?:target|tp) ([0-9][0-9.,]*) (?:achieved|hit|reached)", status):
            token = match.group(1).replace(".", "").replace(",", "")
            # An unnumbered source target confirms its exact written level.
            exact = {index for index, target in enumerate(active_plan.plan.targets, 1)
                     if target.strip().replace(".", "").replace(",", "") == token}
            reached.update(exact or {int(token)})
    return stopped, {number for number in reached if 1 <= number <= len(active_plan.plan.targets)}


def source_outcome_state(event: SourceEvent, active_plan: SourceEvent) -> MarketState | None:
    """Map explicit source confirmations, never suggestions or inferred prices."""
    stopped, reached = _source_confirmations(event, active_plan)
    if stopped:
        return MarketState.STOP_LOSS_BREACHED
    return MarketState.from_target_number(min(max(reached), 6)) if reached else None


class BoardEngine:
    def __init__(self, store: BoardStore, client: DiscordForumClient) -> None:
        self.store = store
        self.client = client

    def submit(self, event: SourceEvent, now: datetime) -> str:
        """Persist source identity, then atomically decide and enqueue its effects.

        A replay resumes an intake interrupted before its decision committed.
        Completed identities return board_duplicate, including ignored events.
        """
        with self.store.transaction() as tx:
            submitted = tx.submit_event(event, now)
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

    def after_close(self, phase: str, now: datetime) -> dict[str, int]:
        """Reconcile active primary plans at the one reviewed close-phase instant.

        Yahoo is read before the short owner transaction.  The attempt marker,
        factual checkpoint, card intent, and tag intent then commit together, so
        a restart cannot repeat a phase or split its facts.
        """
        if phase not in {"initial", "retry"}:
            raise ValueError("close phase must be initial or retry")
        instant = _wib(now)
        expected_hour, expected_minute = (16, 30) if phase == "initial" else (17, 0)
        if (instant.hour, instant.minute) != (expected_hour, expected_minute):
            return _close_result()
        if not is_idx_trading_day(instant.date()):
            return _close_result()

        candidates = self.store.active_primary_plans()
        result = _close_result(active=len(candidates))
        session_date = instant.date().isoformat()
        for candidate in candidates:
            # Retried phases are eligible only after this exact plan's initial
            # source failed. A plan replacement receives a fresh plan identity.
            with self.store.transaction() as tx:
                current = next(
                    (item for item in tx.active_primary_plans() if item.plan_id == candidate.plan_id),
                    None,
                )
                if current is None or tx.close_attempted(current.plan_id, session_date, phase):
                    continue
                if phase == "retry" and not tx.initial_close_unavailable(current.plan_id, session_date):
                    continue
            close = fetch_session_close(candidate.event.ticker, instant.date())
            try:
                levels = parse_plan_levels(
                    candidate.event.plan.entry, candidate.event.plan.stop_loss, candidate.event.plan.targets
                )
                state = classify_close(close, levels) if close is not None else None
            except ValueError:
                # Unsupported source notation is not a failed market fetch.
                # Leave this plan's prior facts and attempts intact, and keep
                # reconciling the other tickers.
                result["invalid"] += 1
                continue
            with self.store.transaction() as tx:
                current = next(
                    (item for item in tx.active_primary_plans() if item.plan_id == candidate.plan_id),
                    None,
                )
                if current is None or tx.close_attempted(current.plan_id, session_date, phase):
                    continue
                if phase == "retry" and not tx.initial_close_unavailable(current.plan_id, session_date):
                    continue
                tx.record_close_attempt(current.plan_id, session_date, phase, instant, close is not None)
                if close is None:
                    result["unavailable"] += 1
                    if phase == "retry":
                        checkpoint, last_valid = tx.latest_checkpoints(current.episode.id)
                        unavailable = Checkpoint.unavailable_at(
                            session_date=session_date, checked_at=instant.isoformat()
                        )
                        tx.record_checkpoint(current.episode.id, unavailable)
                        self._enqueue_close_edit(
                            tx, current, unavailable, last_valid, instant, "retry-unavailable"
                        )
                    continue

                checkpoint = Checkpoint.market(
                    session_date=session_date,
                    checked_at=instant.isoformat(),
                    close_price=_price_text(close),
                    state=state,
                )
                _, last_valid = tx.latest_checkpoints(current.episode.id)
                tx.record_checkpoint(current.episode.id, checkpoint)
                terminal = (state == MarketState.STOP_LOSS_BREACHED
                            or levels.targets[-1].is_reached_by(close))
                updated = replace(current.episode, market_tag=state.value,
                                  lifecycle="resolved" if terminal else "primary",
                                  lifecycle_tag="Resolved" if terminal else "Primary plan",
                                  closed_at=instant if terminal else None)
                tx.update_episode(updated)
                self._enqueue_close_edit(tx, current, checkpoint, checkpoint, instant, f"{phase}-close")
                if updated.market_tag != current.episode.market_tag or terminal:
                    self._enqueue_close_patch(tx, current.plan_id, updated, instant, f"{phase}-tag")
                if terminal:
                    tx.finish_plan(updated.id, instant)
                result["checked"] += 1
        result["pending"] = self.store.pending_outbox_count()
        return result

    def _social(self, tx, event, event_id, active, now):
        if active is None:
            active = tx.create_episode(event.ticker, "source", event.source_title, event.published_at)
            active = replace(active, lifecycle_tag="Source plan")
            tx.update_episode(active)
            self._enqueue(tx, event, active, "create_thread", {
                "name": active.title, "content": render_source_only_card(active.title, event.source_url),
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
            if primary_card_requires_source_reply(event):
                self._source_reply(tx, event, active, now)
            return
        active = replace(active, lifecycle="primary", title=title, lifecycle_tag="Primary plan",
                         market_tag=None, latest_material_at=max(active.latest_material_at, event.published_at))
        tx.update_episode(active)
        tx.replace_plan(active.id, event_id, event, now)
        self._enqueue(tx, event, active, "edit_starter", {
            "content": render_primary_card(event), "chart": event.media_path,
            "clear_attachments": event.media_path is None,
        }, now)
        self._patch(tx, event, active, now)
        if primary_card_requires_source_reply(event):
            self._source_reply(tx, event, active, now)

    def _status(self, tx, event, event_id, active, now):
        plan = tx.active_plan(active.id)
        if plan is None:
            raise StoreBlockedError("active primary episode is missing its plan")
        current = event.source_status or plan.source_status or "New setup"
        state = source_outcome_state(event, plan)
        stopped, reached = _source_confirmations(event, plan)
        terminal = stopped or len(plan.plan.targets) in reached
        # Source confirmations may set the factual tag; generic status leaves it.
        active = replace(active, market_tag=state.value if state else active.market_tag,
                         latest_material_at=max(active.latest_material_at, event.published_at),
                         lifecycle="resolved" if terminal else "primary",
                         lifecycle_tag="Resolved" if terminal else "Primary plan",
                         closed_at=now if terminal else None)
        tx.set_source_status(active.id, current, event.published_at)
        tx.update_episode(active)
        self._source_reply(tx, event, active, now)
        checkpoint, last_valid = tx.latest_checkpoints(active.id)
        self._enqueue(tx, event, active, "edit_starter", {
            "content": render_primary_card(
                replace(plan, source_status=current), checkpoint, last_valid, event.published_at
            ),
            "chart": None,
        }, now)
        self._patch(tx, event, active, now)
        if terminal:
            tx.finish_plan(active.id, now)

    def _source_reply(self, tx, event, active, now):
        contents = render_source_replies(event)
        for index, content in enumerate(contents):
            self._enqueue(tx, event, active, "post_source_reply", {
                "content": content, "media": event.media_path if index == 0 else None,
            }, now, suffix=f":{index}" if len(contents) > 1 else "")
        for index, url in enumerate(event.media_urls):
            self._enqueue(tx, event, active, "post_source_reply", {
                "content": f"[Source media {index + 1}](<{event.source_url}>)",
                "media": None, "media_url": url,
            }, now, suffix=f":media:{index}")

    def _patch(self, tx, event, active, now):
        tags = [active.lifecycle_tag]
        if active.market_tag:
            tags.append(active.market_tag)
        self._enqueue(tx, event, active, "patch_thread", {
            "name": active.title, "tag_names": tags, "archived": False,
        }, now)

    def _enqueue_close_edit(self, tx, current, checkpoint, last_valid, now, suffix):
        payload = {
            "content": render_primary_card(
                current.event, checkpoint, last_valid, current.source_updated_at
            ),
            "chart": None,
            "nonce_value": f"close:{current.plan_id}:{checkpoint.session_date}:{suffix}:edit",
        }
        tx.enqueue_outbox(
            "edit_starter", current.episode.id, payload,
            payload["nonce_value"], now,
        )

    def _enqueue_close_patch(self, tx, plan_id, active, now, suffix):
        tags = [active.lifecycle_tag]
        if active.market_tag:
            tags.append(active.market_tag)
        nonce_value = f"close:{plan_id}:{_wib(now).date().isoformat()}:{suffix}:patch"
        tx.enqueue_outbox(
            "patch_thread", active.id,
            {"name": active.title, "tag_names": tags, "archived": False, "nonce_value": nonce_value},
            nonce_value, now,
        )

    def schedule_history_cleanup(self, now: datetime) -> int:
        """Durably queue deletion of the legacy quoted history replies."""
        with self.store.transaction() as tx:
            return tx.schedule_history_deletes(now)

    def schedule_format_migration(self, now: datetime) -> int:
        """Queue one canonical card rewrite for every existing plan episode."""
        count = 0
        for card in self.store.latest_plan_cards():
            if not card.episode.thread_id or not card.episode.starter_message_id:
                continue
            checkpoint, last_valid = self._latest_checkpoints(card.episode.id)
            with self.store.transaction() as tx:
                tx.enqueue_outbox(
                    "edit_starter",
                    card.episode.id,
                    {
                        "content": render_primary_card(
                            card.event, checkpoint, last_valid, card.source_updated_at
                        ),
                        "chart": None,
                        "nonce_value": f"format-migration:v3:{card.episode.id}:{card.plan_id}",
                    },
                    f"format-migration:v3:{card.episode.id}:{card.plan_id}",
                    now,
                )
            count += 1
        return count

    def _latest_checkpoints(self, episode_id: int):
        with self.store.transaction() as tx:
            return tx.latest_checkpoints(episode_id)

    @staticmethod
    def _enqueue(tx: BoardStoreTransaction, event: SourceEvent, active: Episode,
                 operation: str, payload: dict, now: datetime, suffix: str = "") -> None:
        dedupe_key = f"event:{event.event_key}:{operation}{suffix}"
        tx.enqueue_outbox(operation, active.id, {**payload, "nonce_value": dedupe_key}, dedupe_key, now)

    def drain(self, now: datetime | None = None, *, limit: int = 100) -> int:
        """Execute due intents in episode order, retaining failures for retry."""
        if limit < 1:
            raise ValueError("drain limit must be positive")
        with self.store.delivery_lock() as acquired:
            return self._drain_owned(now, limit) if acquired else 0

    def _drain_owned(self, now: datetime | None, limit: int) -> int:
        completed = 0
        for _ in range(limit):
            instant = now or datetime.now(timezone.utc)
            operation = self.store.claim_due_outbox(instant)
            if operation is None:
                break
            try:
                payload = dict(operation.payload)
                if payload.get("media_url") and not getattr(self.client, "no_post", False):
                    payload["media"] = str(acquire_media(payload["media_url"], operation.dedupe_key))
                if operation.operation != "create_thread":
                    episode = self.store.episode(operation.episode_id)
                    if not episode.thread_id or not episode.starter_message_id:
                        raise StoreBlockedError("Discord thread identity is unavailable")
                    if operation.operation == "delete_message":
                        payload.setdefault("thread_id", episode.thread_id)
                    else:
                        payload.update(thread_id=episode.thread_id, message_id=episode.starter_message_id)
                creating = operation.operation in {"create_thread", "post_source_reply", "post_history_reply"}
                if creating and payload.get("create_snapshot"):
                    completion = self.client.recover_create(operation.operation, payload)
                else:
                    def before_create():
                        snapshot = self.client.create_snapshot(operation.operation, payload)
                        self.store.set_create_snapshot(operation.id, operation.claim_token, snapshot)
                    self.client.before_create = before_create if creating else None
                    completion = self.client.execute(operation.operation, payload)
                if operation.operation == "create_thread" and not all(
                    completion.get(key) for key in ("thread_id", "starter_message_id")
                ):
                    raise DiscordForumError("Discord thread identity is unavailable")
                self.store.complete_outbox(operation.id, operation.claim_token, completion, instant)
                completed += 1
            except Exception as exc:
                if isinstance(exc, (DiscordRateLimitError, DiscordRejectedError)) and getattr(exc, "create_rejected", False):
                    self.store.set_create_snapshot(operation.id, operation.claim_token, None)
                # Store only a safe category, never provider bodies or credentials.
                self.store.fail_outbox(
                    operation.id, operation.claim_token, type(exc).__name__, instant,
                    minimum_delay_seconds=exc.retry_after if isinstance(exc, DiscordRateLimitError) else 0,
                )
            finally:
                self.client.before_create = None
        return completed


def _wib(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must include a timezone")
    return value.astimezone(WIB)


def _price_text(value) -> str:
    return format(value, "f").rstrip("0").rstrip(".") if "." in format(value, "f") else format(value, "f")


def _close_result(*, active: int = 0) -> dict[str, int]:
    return {"active": active, "checked": 0, "unavailable": 0, "pending": 0, "invalid": 0}
