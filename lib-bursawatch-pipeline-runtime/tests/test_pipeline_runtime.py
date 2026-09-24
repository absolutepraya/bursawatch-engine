import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from pipeline_runtime import PipelineRuntime


class Client:
    def __init__(self):
        self.settled = []
        self.claimed_pipelines = None
    def claim(self, pipeline_ids, limit):
        self.claimed_pipelines = pipeline_ids
        return [{"work_key": str(i), "lease_token": str(i), "pipeline_id": str(i), "effect_key": str(i)} for i in range(2)]
    def begin(self, wid, token):
        return True
    def settle(self, *args):
        self.settled.append(args)
        return {"status": "pending" if args[2] is False else "done"}


def test_one_handler_failure_does_not_block_another():
    client = Client()
    def fail(item):
        raise RuntimeError("secret provider error")
    seen = []
    runtime = PipelineRuntime(client, {"0": fail, "1": lambda item: seen.append(item["effect_key"])})
    assert [x["status"] for x in runtime.run_once()] == ["retry", "done"]
    assert seen == ["1"]
    assert client.claimed_pipelines == ["0", "1"]
    assert client.settled == [("0", "0", False, "handler_failed"), ("1", "1", True)]


def test_rejected_begin_does_not_dispatch_handler():
    client = Client()
    client.begin = lambda wid, token: wid != "0"
    seen = []
    result = PipelineRuntime(client, {"0": lambda item: seen.append("old"), "1": lambda item: seen.append("new")}).run_once()
    assert [row["status"] for row in result] == ["begin_rejected", "done"]
    assert seen == ["new"]
