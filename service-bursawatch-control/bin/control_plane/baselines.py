"""Load and seed the reviewed pre-cutover watcher configuration baseline."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable

from .contract import canonical_json_bytes, config_checksum, validate_watcher_id


BASELINE_FILES = {
    "bursawatch-dc-swing-board": "bursawatch-dc-swing-board.json",
    "bursawatch-ig-account-watch": "bursawatch-ig-account-watch.json",
    "bursawatch-stockbit-snips": "bursawatch-stockbit-snips.json",
    "bursawatch-tg-kelas-investasi-gtw": "bursawatch-tg-kelas-investasi-gtw.json",
    "bursawatch-tg-market-news": "bursawatch-tg-market-news.json",
    "bursawatch-tg-phintraco-swing": "bursawatch-tg-phintraco-swing.json",
    "bursawatch-wa-channel-watch": "bursawatch-wa-channel-watch.json",
    "bursawatch-x-account-watch": "bursawatch-x-account-watch.json",
}
LOCK_NAME = "bursawatch-control-plane-baseline-configs-v1"
BASELINE_ACTOR = "source-baseline"


class BaselineSeedError(RuntimeError):
    """The reviewed baseline cannot be selected or seeded safely."""


@dataclass(frozen=True)
class BaselineConfig:
    watcher_id: str
    config_version: int
    config: dict[str, Any]
    config_sha256: str


def load_baselines(directory: Path) -> list[BaselineConfig]:
    expected_names = set(BASELINE_FILES.values())
    try:
        paths = list(directory.iterdir())
    except OSError as exc:
        raise BaselineSeedError("baseline configuration directory could not be read") from exc
    found_names = {path.name for path in paths if path.is_file() and path.suffix == ".json"}
    unexpected_paths = {
        path.name
        for path in paths
        if not path.is_file() or path.suffix != ".json" or path.name not in expected_names
    }
    if found_names != expected_names or unexpected_paths:
        raise BaselineSeedError("baseline configuration files do not match the reviewed watcher set")

    baselines: list[BaselineConfig] = []
    for watcher_id, file_name in sorted(BASELINE_FILES.items()):
        validate_watcher_id(watcher_id)
        try:
            raw = json.loads((directory / file_name).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BaselineSeedError(f"baseline configuration could not be read: {file_name}") from exc
        if type(raw) is not dict:
            raise BaselineSeedError(f"baseline configuration must be an object: {file_name}")
        config_version = raw.get("version")
        if type(config_version) is not int or config_version < 1:
            raise BaselineSeedError(f"baseline configuration has no valid version: {file_name}")
        try:
            canonical_json_bytes(raw)
        except ValueError as exc:
            raise BaselineSeedError(f"baseline configuration is not valid JSON data: {file_name}") from exc
        baselines.append(
            BaselineConfig(
                watcher_id=watcher_id,
                config_version=config_version,
                config=raw,
                config_sha256=config_checksum(raw),
            )
        )
    return baselines


def _connect(dsn: str):
    try:
        import psycopg
    except ImportError as exc:
        raise BaselineSeedError("psycopg is required to seed baseline configurations") from exc
    return psycopg.connect(dsn)


def _json_value(value: dict[str, Any]):
    try:
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise BaselineSeedError("psycopg is required to seed baseline configurations") from exc
    return Jsonb(value)


def seed_baselines(
    dsn: str,
    directory: Path,
    *,
    connect: Callable[[str], Any] = _connect,
    json_value: Callable[[dict[str, Any]], Any] = _json_value,
) -> list[str]:
    if type(dsn) is not str or not dsn.strip():
        raise BaselineSeedError("DATABASE_URL is required")
    baselines = load_baselines(directory)
    connection = connect(dsn)
    outcomes: list[str] = []
    try:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("select pg_advisory_xact_lock(hashtext(%s))", (LOCK_NAME,))
            for baseline in baselines:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        select current_revision
                          from bursawatch_watchers
                         where watcher_id = %s
                         for update
                        """,
                        (baseline.watcher_id,),
                    )
                    watcher = cursor.fetchone()
                    if watcher is None:
                        raise BaselineSeedError(f"baseline watcher is missing: {baseline.watcher_id}")
                    if watcher[0] is not None:
                        outcomes.append(f"already configured: {baseline.watcher_id}")
                        continue
                    cursor.execute(
                        """
                        select count(*)
                          from bursawatch_config_revisions
                         where watcher_id = %s
                        """,
                        (baseline.watcher_id,),
                    )
                    existing_revisions = cursor.fetchone()
                    if existing_revisions is None or existing_revisions[0] != 0:
                        raise BaselineSeedError(
                            f"baseline watcher has configuration history without an active revision: {baseline.watcher_id}"
                        )
                    cursor.execute(
                        """
                        insert into bursawatch_config_revisions
                            (watcher_id, revision, config_version, config, config_sha256, actor_id)
                        values (%s, 1, %s, %s, %s, %s)
                        """,
                        (
                            baseline.watcher_id,
                            baseline.config_version,
                            json_value(baseline.config),
                            baseline.config_sha256,
                            BASELINE_ACTOR,
                        ),
                    )
                    cursor.execute(
                        """
                        update bursawatch_watchers
                           set current_revision = 1,
                               updated_at = now()
                         where watcher_id = %s
                        """,
                        (baseline.watcher_id,),
                    )
                outcomes.append(f"seeded: {baseline.watcher_id}")
    finally:
        connection.close()
    return outcomes
