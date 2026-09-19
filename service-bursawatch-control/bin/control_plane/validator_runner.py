from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: validator_runner.py <config-directory> <loader-name>", file=sys.stderr)
        return 64
    directory = Path(argv[1]).resolve()
    loader_name = argv[2]
    if not (directory / "config.py").is_file():
        print("configured watcher config module is unavailable", file=sys.stderr)
        return 65
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("configuration payload is invalid JSON", file=sys.stderr)
        return 65
    sys.path.insert(0, str(directory))
    try:
        module = importlib.import_module("config")
        loader = getattr(module, loader_name)
        loader(payload)
    except (ValueError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 65
    except Exception:
        print("configured watcher config module is unavailable", file=sys.stderr)
        return 65
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
