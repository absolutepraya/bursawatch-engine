from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def test_wrapper_loads_reviewed_source_root_without_loading_unrelated_secrets(tmp_path):
    home = tmp_path / "home"
    env_file = home / ".hermes" / ".env"
    env_file.parent.mkdir(parents=True)
    fresh_root = home / ".hermes" / "state" / "wa-fresh"
    env_file.write_text(
        f"BURSAWATCH_WA_SOURCE_STATE_ROOT={fresh_root}\n"
        "UNRELATED_TEST_SECRET=must-not-load\n"
    )
    interpreter = home / ".local/share/uv/tools/yahoo-finance-mcp/bin/python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        f"sys.path.insert(0, {str(ROOT / 'lib-bursawatch-source-ingest/bin')!r})\n"
        f"sys.path.insert(0, {str(ROOT / 'lib-bursawatch-control/bin')!r})\n"
        "from source_runner import state_root\n"
        "print(json.dumps({'root': str(state_root('BURSAWATCH_WA_SOURCE', "
        "'bursawatch-wa-source-ingest')), 'unrelated': os.environ.get('UNRELATED_TEST_SECRET')}))\n"
    )
    interpreter.chmod(0o755)
    result = subprocess.run(
        ["bash", str(ROOT / "cron-wa-source-ingest/bin/bursawatch-wa-source-ingest.sh")],
        env={"HOME": str(home), "PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(result.stdout) == {"root": str(fresh_root), "unrelated": None}
