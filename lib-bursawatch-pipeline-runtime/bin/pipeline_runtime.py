"""Isolated dispatch of independently leased source subscription work."""
from __future__ import annotations

import re
from typing import Any, Callable


class PipelineRuntime:
    def __init__(self, client, handlers: dict[str, Callable[[dict[str, Any]], None]]):
        self.client = client
        self.handlers = dict(handlers)

    def run_once(self, limit: int = 10) -> list[dict[str, str]]:
        outcomes = []
        for item in self.client.claim(limit):
            wid, token = item["work_key"], item["lease_token"]
            pipeline = item["pipeline_id"]
            handler = self.handlers.get(pipeline)
            if handler is None:
                self.client.settle(wid, token, False, "handler_unavailable")
                outcomes.append({"work_key": wid, "status": "retry"})
                continue
            try:
                # Handler must pass effect_key to its domain owner. It is stable across
                # lease expiry and explicit replay, so owner deduplication is durable.
                handler(item)
            except Exception:
                # Provider errors, source text and credentials never enter routine logs.
                self.client.settle(wid, token, False, "handler_failed")
                outcomes.append({"work_key": wid, "status": "retry"})
            else:
                self.client.settle(wid, token, True)
                outcomes.append({"work_key": wid, "status": "done"})
        return outcomes
