#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

_RESILIENCE_BIN = Path(__file__).resolve().parents[2] / "lib-telegram-resilience" / "bin"
if not _RESILIENCE_BIN.exists():
    _RESILIENCE_BIN = Path.home() / ".agents" / "skills" / "lib-telegram-resilience" / "bin"
if str(_RESILIENCE_BIN) not in sys.path:
    sys.path.insert(0, str(_RESILIENCE_BIN))

from telegram_resilience import PolyCopResilience, acquire_probe_after_active_lease, is_transport_error

import config
from agent_protocol import RetryableSubmissionError, agent_item, build_wake_payload, validate_submission
from discord import DISCORD_CHANNEL_ID, DiscordDeliveryError, deliver_oldest_ready_event, nonce, post_text
from parsing import extract_plan
from state import CorruptStateError, RunLockBusyError, claim_oldest_agent, load_state, observe_messages, ready_events, restore_expired_claim, run_lock, save_state
from telegram_source import TelegramMediaError, TelegramSourceError, capture_image, fetch_unseen_messages, make_client, resolve_source

try:
    from control_plane_runtime import ControlPlaneRun
except ModuleNotFoundError:
    class ControlPlaneRun:
        @classmethod
        def begin(cls, *_args, **_kwargs):
            return cls()

        def event(self, *_args, **_kwargs):
            pass

        def finish(self, *_args, **_kwargs):
            pass


WIB = ZoneInfo("Asia/Jakarta")
WATCHER_NAME = "kelas-investasi-gtw"
_DEFAULT_WATCH_CONFIG = config.default_watch_config()
# Compatibility defaults for isolated scanner tests. Runtime resolves each
# source and destination from its frozen configuration snapshot.
HEARTBEAT_CHANNEL_ID = _DEFAULT_WATCH_CONFIG.heartbeat_discord_channel_id


def _require_aware(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return now


def _dry_run(value: bool | None) -> bool:
    return os.environ.get("KELAS_INVESTASI_GTW_NO_POST") == "1" if value is None else value


def _state_path() -> Path:
    return Path(os.environ.get("KELAS_INVESTASI_GTW_STATE_PATH", str(Path.home() / ".hermes" / "state" / "kelas-investasi-gtw-watch.json")))


def resilience() -> PolyCopResilience:
    return PolyCopResilience.from_defaults()


def format_heartbeat(now: datetime, *, scanned: int, pending: int, delivered: int, warning: bool = False) -> str:
    _require_aware(now)
    suffix = " ⚠️" if warning else ""
    return f"🫀 {WATCHER_NAME} · {now.astimezone(WIB):%H:%M} WIB · scanned={scanned} pending={pending} delivered={delivered}{suffix}"


def _fatal_reason(reason: object) -> str:
    if isinstance(reason, RetryableSubmissionError):
        return f"submission rejected: {reason.reason_code}"
    if isinstance(reason, TelegramMediaError):
        return "Telegram source media is unavailable"
    if isinstance(reason, TelegramSourceError):
        return "Telegram source is unavailable"
    if isinstance(reason, CorruptStateError):
        return "watcher state is unavailable"
    if isinstance(reason, DiscordDeliveryError):
        return "Discord delivery is unavailable"
    return "watcher operation failed"


def format_fatal(now: datetime, reason: object) -> str:
    _require_aware(now)
    return f"❌ {WATCHER_NAME} · {now.astimezone(WIB):%H:%M} WIB · failed: {_fatal_reason(reason)}"


def post_heartbeat(
    content: str,
    now: datetime,
    dry_run: bool,
    *,
    channel_id: str = HEARTBEAT_CHANNEL_ID,
    nonce_seed: str | None = None,
) -> None:
    if dry_run:
        print(content)
        return
    hour = now.astimezone(WIB).strftime("%Y%m%d%H")
    seed = nonce_seed or f"heartbeat:{hour}"
    post_text(
        content,
        channel_id,
        False,
        nonce(seed, "status"),
        seed,
        "status",
    )


async def _disconnect(client: object | None) -> None:
    if client is None:
        return
    disconnect = getattr(client, "disconnect", None)
    if disconnect is None:
        return
    try:
        result = disconnect()
        if hasattr(result, "__await__"):
            await result
    except Exception:
        pass


async def _run(
    now: datetime,
    dry_run: bool,
    loaded_config: config.LoadedWatchConfig,
    control_run: ControlPlaneRun,
) -> tuple[dict[str, object], str]:
    path = _state_path()
    try:
        with run_lock(path.with_name(path.name + ".lock")):
            control = resilience()
            decision = await acquire_probe_after_active_lease(control, WATCHER_NAME, now)
            if decision.kind != "probe":
                control_run.event(
                    "resilience-probe-withheld",
                    level="warning",
                    phase="source",
                    event_type="source.probe.withheld",
                    message="Kelas Investasi source probe was withheld by shared Telegram resilience",
                    attributes={"reason": decision.kind},
                )
                return {"wakeAgent": False}, "blocked"

            client: object | None = None
            probe_outcome: str | None = None
            try:
                client = make_client()
                await client.connect()  # type: ignore[union-attr]
                if not await client.is_user_authorized():  # type: ignore[union-attr]
                    control.record_auth_required(decision.lease_id, WATCHER_NAME, now)
                    probe_outcome = "auth"
                    control_run.event(
                        "telegram-auth-required",
                        level="warning",
                        phase="source",
                        event_type="source.auth.required",
                        message="Kelas Investasi Telegram session requires authorization",
                    )
                    return {"wakeAgent": False}, "blocked"
                control.record_authenticated_success(decision.lease_id, WATCHER_NAME, now, None, None)
                probe_outcome = "success"

                state = load_state(path)
                entity = await resolve_source(
                    client,
                    loaded_config.config.telegram_channel_id,
                    loaded_config.config.telegram_username,
                )
                cursor = state["cursor"]
                messages = await fetch_unseen_messages(client, entity, int(cursor or 0))
                observe_messages(state, messages, now)
                events = ready_events(state, now)
                for event in events:
                    await _capture_event_media(client, entity, event, path.parent / "media")
                save_state(path, state)
                control_run.event(
                    "source-poll-completed",
                    level="info",
                    phase="source",
                    event_type="source.poll.completed",
                    message="Kelas Investasi source poll completed",
                    attributes={"messages": len(messages), "ready_bundles": len(events)},
                )

                delivered = _drain_due_delivery(
                    state,
                    path,
                    now,
                    dry_run,
                    channel_id=loaded_config.config.alert_discord_channel_id,
                )
                _drain_publication_projection(state, path, now, dry_run,
                                              channel_id=loaded_config.config.alert_discord_channel_id)
                warning = _has_delivery_warning(state)
                control_run.event(
                    "delivery-drain-completed",
                    level="warning" if warning else "info",
                    phase="delivery",
                    event_type="delivery.drain.completed",
                    message="Kelas Investasi delivery and board drain completed",
                    attributes={
                        "delivered": delivered,
                        "pending": len(state["outbox"]),
                        "warning": warning,
                    },
                )

                claim = claim_oldest_agent(state, now)
                if claim is not None:
                    save_state(path, state)
                    payload = build_wake_payload(
                        agent_item(
                            claim,
                            source_username=loaded_config.config.telegram_username,
                            additional_prompt_instruction=loaded_config.config.additional_prompt_instruction,
                        )
                    )
                    control_run.event(
                        "agent-wake-requested",
                        level="info",
                        phase="agent",
                        event_type="agent.wake.requested",
                        message="Kelas Investasi bundle was claimed for agent analysis",
                        attributes={"event_key": claim["event_key"]},
                    )
                    post_heartbeat(
                        format_heartbeat(now, scanned=len(messages), pending=len(state["outbox"]), delivered=delivered, warning=warning),
                        now,
                        dry_run,
                        channel_id=loaded_config.config.heartbeat_discord_channel_id,
                    )
                    return payload, "degraded" if warning else "ok"
                post_heartbeat(
                    format_heartbeat(now, scanned=len(messages), pending=len(state["outbox"]), delivered=delivered, warning=warning),
                    now,
                    dry_run,
                    channel_id=loaded_config.config.heartbeat_discord_channel_id,
                )
                return {"wakeAgent": False}, "degraded" if warning else "ok"
            except Exception as error:
                if probe_outcome is None and is_transport_error(error):
                    control.record_transport_failure(decision.lease_id, WATCHER_NAME, error, now)
                    probe_outcome = "transport"
                    control_run.event(
                        "telegram-transport-blocked",
                        level="warning",
                        phase="source",
                        event_type="source.transport.blocked",
                        message="Kelas Investasi source poll was blocked by Telegram transport resilience",
                    )
                    return {"wakeAgent": False}, "blocked"
                if probe_outcome is None:
                    # A local pre-auth failure has no Telegram failure category,
                    # but must not strand the shared probe lease until timeout.
                    release = getattr(control, "record_safe_release", None)
                    if callable(release):
                        release(decision.lease_id, WATCHER_NAME, now)
                    probe_outcome = "released"
                try:
                    post_heartbeat(
                        format_fatal(now, error),
                        now,
                        dry_run,
                        channel_id=loaded_config.config.heartbeat_discord_channel_id,
                    )
                except Exception:
                    # A fatal Discord attempt is best effort; the scanner must
                    # still fail so Hermes observes the operational error.
                    pass
                raise
            finally:
                await _disconnect(client)
    except RunLockBusyError:
        control_run.event(
            "run-lock-busy",
            level="warning",
            phase="lifecycle",
            event_type="run.lock.busy",
            message="Kelas Investasi watcher run was skipped because another run holds the lock",
        )
        return {"wakeAgent": False}, "blocked"


async def _capture_event_media(client: object, entity: object, event: dict[str, object], destination: Path) -> None:
    media = event.get("media")
    if not isinstance(media, list):
        return
    header_message_id = event.get("header_message_id")
    header_media = next(
        (
            item
            for item in media
            if isinstance(item, Mapping) and item.get("message_id") == header_message_id
        ),
        None,
    )
    if header_media is None:
        event["media"] = []
        return
    captured: list[dict[str, object]] = []
    message_id, ordinal = header_media.get("message_id"), header_media.get("ordinal")
    if not isinstance(message_id, int) or not isinstance(ordinal, int):
        raise TelegramMediaError("Telegram source media is unavailable")
    existing = header_media.get("path")
    if _verified_captured_path(existing, destination):
        captured.append({"message_id": message_id, "ordinal": ordinal, "path": str(Path(str(existing)).resolve())})
    else:
        captured.append({"message_id": message_id, "ordinal": ordinal, "path": str(await capture_image(client, entity, message_id, ordinal, destination))})
    event["media"] = captured


def _verified_captured_path(value: object, destination: Path) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        path = Path(value).resolve()
        path.relative_to(destination.resolve())
        if not path.is_file() or path.stat().st_size <= 0:
            return False
        with path.open("rb") as source:
            header = source.read(16)
        return (
            header.startswith(b"\x89PNG\r\n\x1a\n")
            or header.startswith(b"\xff\xd8\xff")
            or header.startswith((b"GIF87a", b"GIF89a"))
            or (header.startswith(b"RIFF") and header[8:12] == b"WEBP")
        )
    except (OSError, ValueError):
        return False


def _drain_due_delivery(
    state: dict[str, object],
    path: Path,
    now: datetime,
    dry_run: bool,
    *,
    channel_id: str = DISCORD_CHANNEL_ID,
) -> int:
    """Drain each immediately due text/media leg while the watcher lock is held."""
    delivered = 0
    while deliver_oldest_ready_event(
        state,
        now,
        dry_run,
        state_path=path,
        channel_id=channel_id,
    ):
        delivered += 1
    return delivered


def _drain_publication_projection(
    state: dict[str, object], path: Path, now: datetime, dry_run: bool,
    *, channel_id: str = DISCORD_CHANNEL_ID,
) -> dict[str, int]:
    """Persist confirmed snapshots and retry only the read-model submission."""
    from publication_projection import record_confirmed_outbox, drain

    record_confirmed_outbox(state, path, now, channel_id=channel_id)
    return drain(state, path, now, dry_run=dry_run)


def _has_delivery_warning(state: Mapping[str, object]) -> bool:
    outbox = state.get("outbox")
    if not isinstance(outbox, list):
        return False
    return any(
        isinstance(event, Mapping)
        and event.get("agent_phase") in ("ready", "delivering")
        and (
            event.get("last_error") is not None
            or int(event.get("attempts", 0) or 0) > 0
            or event.get("board_last_error") is not None
            or int(event.get("board_attempts", 0) or 0) > 0
        )
        for event in outbox
    )


def run(now: datetime | None = None, dry_run: bool | None = None) -> dict[str, object]:
    """Run once against one frozen operator configuration snapshot."""
    run_now = _require_aware(now or datetime.now(WIB))
    is_dry_run = _dry_run(dry_run)
    loaded_config = config.load_watch_config_for_run()
    with config.activate_watch_config(loaded_config.config):
        control_run = ControlPlaneRun.begin(
            "KELAS_INVESTASI_GTW",
            loaded_config.revision,
            scheduler_job_id="bursawatch-tg-kelas-investasi-gtw",
        )
        control_run.event(
            "run-started",
            level="info",
            phase="lifecycle",
            event_type="run.started",
            message="Kelas Investasi watcher run started",
            attributes={"config_revision": loaded_config.revision, "no_post": is_dry_run},
        )
        outcome = "failed"
        failure: str | None = None
        try:
            payload, outcome = asyncio.run(_run(run_now, is_dry_run, loaded_config, control_run))
            return payload
        except Exception as error:
            failure = _fatal_reason(error)
            control_run.event(
                "run-failed",
                level="fatal",
                phase="lifecycle",
                event_type="run.failed",
                message="Kelas Investasi watcher run failed",
                attributes={"error": failure},
            )
            raise
        finally:
            control_run.event(
                "run-completed",
                level="warning" if outcome in {"blocked", "degraded"} else "info",
                phase="lifecycle",
                event_type="run.completed",
                message=f"Kelas Investasi watcher run {outcome}",
                attributes={"config_revision": loaded_config.revision},
            )
            control_run.finish(outcome, failure)


def submit_analysis_payload(payload: object, dry_run: bool | None = None, now: datetime | None = None) -> dict[str, object]:
    """Accept one agent result using the current frozen delivery snapshot."""
    submission_now = _require_aware(now or datetime.now(WIB))
    is_dry_run = _dry_run(dry_run)
    loaded_config = config.load_watch_config_for_run()
    with config.activate_watch_config(loaded_config.config):
        control_run = ControlPlaneRun.begin(
            "KELAS_INVESTASI_GTW",
            loaded_config.revision,
            scheduler_job_id="bursawatch-tg-kelas-investasi-gtw",
            trigger="agent_submission",
        )
        control_run.event(
            "agent-submission-started",
            level="info",
            phase="agent",
            event_type="agent.submission.started",
            message="Kelas Investasi agent submission started",
            attributes={"config_revision": loaded_config.revision, "no_post": is_dry_run},
        )
        outcome = "failed"
        failure: str | None = None
        try:
            result, outcome = _submit_analysis_payload_loaded(
                payload,
                is_dry_run,
                submission_now,
                loaded_config,
                control_run,
            )
            return result
        except RetryableSubmissionError as error:
            failure = f"submission rejected: {error.reason_code}"
            outcome = "degraded"
            control_run.event(
                "agent-submission-rejected",
                level="warning",
                phase="agent",
                event_type="agent.submission.rejected",
                message="Kelas Investasi agent submission was rejected",
                attributes={"reason": error.reason_code},
            )
            raise
        except Exception as error:
            failure = _fatal_reason(error)
            control_run.event(
                "agent-submission-failed",
                level="fatal",
                phase="agent",
                event_type="agent.submission.failed",
                message="Kelas Investasi agent submission failed",
                attributes={"error": failure},
            )
            raise
        finally:
            control_run.event(
                "agent-submission-completed",
                level="warning" if outcome in {"degraded", "blocked"} else "info",
                phase="lifecycle",
                event_type="agent.submission.completed",
                message=f"Kelas Investasi agent submission {outcome}",
                attributes={"config_revision": loaded_config.revision},
            )
            control_run.finish(outcome, failure)


def _submit_analysis_payload_loaded(
    payload: object,
    dry_run: bool,
    submission_now: datetime,
    loaded_config: config.LoadedWatchConfig,
    control_run: ControlPlaneRun,
) -> tuple[dict[str, object], str]:
    path = _state_path()
    with run_lock(path.with_name(path.name + ".lock")):
        state = load_state(path)
        if isinstance(payload, str):
            try:
                decoded = json.loads(payload)
            except json.JSONDecodeError as error:
                raise ValueError("submission must be valid JSON") from error
            raw: Mapping[str, object] = decoded if isinstance(decoded, Mapping) else {}
        else:
            raw = payload if isinstance(payload, Mapping) else {}
        key = raw.get("event_key")
        event = next((item for item in state["outbox"] if isinstance(item, dict) and item.get("event_key") == key and item.get("agent_phase") == "claimed"), None)
        if event is None:
            raise ValueError("submission does not match a claimed event")
        if restore_expired_claim(event, submission_now):
            save_state(path, state)
            raise ValueError("submission agent lease has expired")
        plan = extract_plan(str(event["source_text"]))
        event["plan"] = {"buy_area": plan.buy_area, "targets": plan.targets, "stoploss": plan.stoploss}
        try:
            validated = validate_submission(event, payload)
        except RetryableSubmissionError as error:
            _post_submission_warning(
                state,
                event,
                error,
                submission_now,
                dry_run,
                heartbeat_channel_id=loaded_config.config.heartbeat_discord_channel_id,
            )
            raise
        event["title"] = validated["title"]
        event["summary"] = validated["summary"]
        from render import freeze_presentation
        freeze_presentation(event, validated, loaded_config.config.alert_discord_channel_id)
        # Submitted work is delivery-only. It can never re-enter the agent
        # claim queue, even if an immediate Discord retry is pending.
        event["agent_phase"] = "delivering"
        event["agent_lease_until"] = None
        save_state(path, state)
        control_run.event(
            "agent-submission-accepted",
            level="info",
            phase="agent",
            event_type="agent.submission.accepted",
            message="Kelas Investasi agent submission was accepted",
            attributes={"event_key": event["event_key"]},
        )
        delivered = _drain_due_delivery(
            state,
            path,
            submission_now,
            dry_run,
            channel_id=loaded_config.config.alert_discord_channel_id,
        )
        _drain_publication_projection(state, path, submission_now, dry_run,
                                      channel_id=loaded_config.config.alert_discord_channel_id)
        warning = _has_delivery_warning(state)
        control_run.event(
            "agent-delivery-drain-completed",
            level="warning" if warning else "info",
            phase="delivery",
            event_type="delivery.drain.completed",
            message="Kelas Investasi agent delivery and board drain completed",
            attributes={
                "event_key": event["event_key"],
                "delivered": delivered,
                "pending": len(state["outbox"]),
                "warning": warning,
            },
        )
        return {"wakeAgent": False, "delivered": delivered}, "degraded" if warning else "ok"


def _post_submission_warning(
    state: Mapping[str, object],
    event: Mapping[str, object],
    error: RetryableSubmissionError,
    now: datetime,
    dry_run: bool,
    *,
    heartbeat_channel_id: str = HEARTBEAT_CHANNEL_ID,
) -> None:
    event_key = str(event.get("event_key", "unknown"))
    pending = len(state.get("outbox", [])) if isinstance(state.get("outbox"), list) else 0
    content = (
        f"🫀 {WATCHER_NAME} · {now.astimezone(WIB):%H:%M} WIB · "
        f"submission_rejected={error.reason_code} event={event_key} pending={pending} ⚠️"
    )
    hour = now.astimezone(WIB).strftime("%Y%m%d%H")
    try:
        post_heartbeat(
            content,
            now,
            dry_run,
            channel_id=heartbeat_channel_id,
            nonce_seed=f"submission:{hour}:{event_key}:{error.reason_code}",
        )
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submit-analysis")
    arguments = parser.parse_args(argv)
    try:
        if arguments.submit_analysis is not None:
            print(submit_analysis_payload(arguments.submit_analysis))
        else:
            print(run())
    except Exception as error:
        print(f"{type(error).__name__}: {_fatal_reason(error)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
