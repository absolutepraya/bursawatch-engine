"""Claim cost and API liveness regressions seen on 2026-10-16.

A single ambiguous heartbeat at the head of the shared ``channel:<id>`` chain
left hundreds of later heartbeats pending. The claim query then re-scanned every
delivered row of that chain for each pending candidate (about 70 seconds on the
live ledger), while the worker held the store write lock and the async submit
handler waited for that lock on the event loop.
"""

import asyncio
import json
import random
import threading
import time

import httpx
import pytest

from discord_delivery.api import create_app
from discord_delivery.config import Config
from discord_delivery.store import DeliveryStore

NOW = "2026-10-16T10:15:00.000Z"
CHAIN = "channel:1505162000420835388"

# The pre-fix claim statements, kept verbatim as the behavioural oracle.
ORACLE_CLAIM = """SELECT d.operation_key FROM discord_operations d WHERE d.status IN ('pending','retrying')
    AND (d.next_attempt_at IS NULL OR d.next_attempt_at <= ?)
    AND NOT EXISTS (SELECT 1 FROM discord_operations earlier WHERE earlier.ordering_key=d.ordering_key
        AND (earlier.created_at<d.created_at OR (earlier.created_at=d.created_at AND earlier.rowid<d.rowid))
        AND earlier.status NOT IN ('delivered','rejected'))
    ORDER BY d.created_at,d.rowid LIMIT 1"""
ORACLE_RECONCILE = ORACLE_CLAIM.replace("d.status IN ('pending','retrying')", "d.status='pending_reconciliation'")


def seed(store, rows):
    """Insert ledger rows directly; (key, chain, status, created_ms, next_attempt_at)."""
    with store._transaction():
        store.db.executemany(
            """INSERT INTO discord_operations (id,operation_key,payload_digest,kind,ordering_key,target_json,
               payload_json,attachments_json,status,next_attempt_at,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            [(f"id-{key}", key, "0" * 64, "channel_message_create", chain, "{}", "{}", "[]", status, retry_at,
              f"2026-10-15T{created // 3_600_000:02d}:{created // 60_000 % 60:02d}:{created // 1000 % 60:02d}."
              f"{created % 1000:03d}Z")
             for key, chain, status, created, retry_at in rows])


def stuck_chain_ledger(store, delivered, pending):
    rows = [(f"d{i}", CHAIN, "delivered", i, None) for i in range(delivered)]
    rows.append(("head", CHAIN, "ambiguous", delivered, None))
    rows += [(f"p{i}", CHAIN, "pending", delivered + 1 + i, None) for i in range(pending)]
    rows.append(("other", "bursawatch-dc-morning-brief:heartbeat", "pending", delivered + 5000, None))
    seed(store, rows)


def vm_steps(store, action):
    steps = 0

    def tick():
        nonlocal steps
        steps += 1
        return 0

    store.db.set_progress_handler(tick, 100)
    try:
        result = action()
    finally:
        store.db.set_progress_handler(None, 0)
    return steps, result


def test_claim_cost_is_independent_of_delivered_history(tmp_path):
    costs = []
    for delivered in (300, 6000):
        store = DeliveryStore(tmp_path / f"{delivered}.sqlite3", tmp_path / f"media{delivered}")
        stuck_chain_ledger(store, delivered, pending=60)
        steps, claimed = vm_steps(store, lambda: store.claim_next(NOW))
        # The blocked heartbeat chain must not starve the independent chain.
        assert claimed.key == "other"
        costs.append(steps)
    # Pre-fix: ~20x (cost tracks delivered rows x pending candidates).
    assert costs[1] < costs[0] * 2, costs


@pytest.mark.parametrize("seed_value", range(25))
def test_claim_selection_matches_original_semantics(tmp_path, seed_value):
    rng = random.Random(seed_value)
    store = DeliveryStore(tmp_path / "ledger.sqlite3", tmp_path / "media")
    statuses = ["delivered", "rejected", "pending", "retrying", "pending_reconciliation",
                "ambiguous", "blocked", "delivering"]
    rows = []
    for index in range(rng.randint(5, 60)):
        # Duplicate timestamps exercise the rowid tie-break.
        created = rng.randint(0, 20)
        due = rng.choice([None, "2026-10-16T09:00:00.000Z", "2026-10-16T11:00:00.000Z"])
        rows.append((f"k{index}", f"chain-{rng.randint(0, 4)}", rng.choice(statuses), created, due))
    seed(store, rows)
    for method, oracle in ((store.claim_next, ORACLE_CLAIM), (store.claim_reconciliation, ORACLE_RECONCILE)):
        expected = store.db.execute(oracle, (NOW,)).fetchone()
        claimed = method(NOW)
        assert (claimed.key if claimed else None) == (expected[0] if expected else None)


def test_blocked_head_still_blocks_its_own_chain_only(tmp_path):
    store = DeliveryStore(tmp_path / "ledger.sqlite3", tmp_path / "media")
    seed(store, [("head", CHAIN, "ambiguous", 1, None), ("behind", CHAIN, "pending", 2, None)])
    assert store.claim_next(NOW) is None
    assert store.get_by_key("head").status == "ambiguous"
    assert store.get_by_key("behind").status == "pending"


def test_submit_does_not_freeze_the_event_loop_while_the_write_lock_is_held(tmp_path):
    config = Config("127.0.0.1", 9140, "client-secret", "admin-secret",
                    tmp_path / "bot-token", tmp_path / "delivery.sqlite3", tmp_path / "media")
    store = DeliveryStore(config.state_path, config.media_path)
    app = create_app(config, store)
    held, release = threading.Event(), threading.Event()

    def worker_transaction():
        with store._write_lock:
            held.set()
            release.wait(5)

    holder = threading.Thread(target=worker_transaction)
    holder.start()
    held.wait(5)
    threading.Timer(1.5, release.set).start()
    operation = {"key": "news:1", "kind": "channel_message_create", "ordering_key": "channel:123",
                 "target": {"channel_id": "123"},
                 "payload": {"content": "Example", "allowed_mentions": {"parse": []}}}

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://delivery") as client:
            submitting = asyncio.create_task(client.post(
                "/v1/operations", headers={"Authorization": "Bearer client-secret"},
                files=[("operation", (None, json.dumps(operation), "application/json"))]))
            started = time.perf_counter()
            # Give the submit handler time to reach the held write lock first.
            await asyncio.sleep(0.3)
            health = await client.get("/healthz")
            elapsed = time.perf_counter() - started
            assert (await submitting).status_code == 202
            return health.status_code, elapsed

    status, elapsed = asyncio.run(scenario())
    holder.join()
    assert status == 200
    # Pre-fix the loop thread itself waits for the lock, so health is served only after ~1.5 s.
    assert elapsed < 0.9, elapsed
