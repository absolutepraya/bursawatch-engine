"""Isolated dispatch of independently leased source subscription work."""
from __future__ import annotations

from typing import Any, Callable


class PipelineRuntime:
    def __init__(self, client, handlers: dict[str, Callable[[dict[str, Any]], None]]):
        self.client = client
        self.handlers = dict(handlers)

    def run_once(self, limit: int = 10) -> list[dict[str, str]]:
        outcomes = []
        if not self.handlers:
            return outcomes
        for item in self.client.claim(list(self.handlers), limit):
            wid, token = item["work_key"], item["lease_token"]
            pipeline = item["pipeline_id"]
            handler = self.handlers.get(pipeline)
            if handler is None:
                outcomes.append({"work_key": wid, "status": "unsupported_pipeline"})
                continue
            if not self.client.fence(wid, token):
                outcomes.append({"work_key": wid, "status": "superseded"})
                continue
            try:
                # Domain owner must atomically fence event_key/version with effect_key.
                # The API fence narrows the race but cannot prevent a revision while
                # the handler is already executing.
                handler(item)
            except Exception:
                # Provider errors, source text and credentials never enter routine logs.
                try:
                    settled = self.client.settle(wid, token, False, "handler_failed")
                    outcomes.append({"work_key": wid, "status": "retry" if settled["status"] == "pending" else settled["status"]})
                except Exception:
                    outcomes.append({"work_key": wid, "status": "settlement_unconfirmed"})
            else:
                try:
                    settled = self.client.settle(wid, token, True)
                    outcomes.append({"work_key": wid, "status": settled["status"]})
                except Exception:
                    outcomes.append({"work_key": wid, "status": "settlement_unconfirmed"})
        return outcomes
