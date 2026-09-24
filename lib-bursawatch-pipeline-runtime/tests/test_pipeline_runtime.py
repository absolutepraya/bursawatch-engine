import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from pipeline_runtime import PipelineRuntime


class Client:
    def __init__(self):
        self.settled = []
    def claim(self, limit):
        return [{"work_key": str(i), "lease_token": str(i), "pipeline_id": str(i), "effect_key": str(i)} for i in range(2)]
    def settle(self, *args):
        self.settled.append(args)


def test_one_handler_failure_does_not_block_another():
    client = Client()
    def fail(item):
        raise RuntimeError("secret provider error")
    seen = []
    runtime = PipelineRuntime(client, {"0": fail, "1": lambda item: seen.append(item["effect_key"])})
    assert [x["status"] for x in runtime.run_once()] == ["retry", "done"]
    assert seen == ["1"]
    assert client.settled == [("0", "0", False, "handler_failed"), ("1", "1", True)]
