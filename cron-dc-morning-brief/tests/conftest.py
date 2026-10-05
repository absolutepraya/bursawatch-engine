import importlib
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'cron-dc-morning-brief/bin'), str(ROOT / 'lib-sectors/bin')]

@pytest.fixture
def core():
    def load(name):
        try:
            return importlib.import_module('morning_brief.' + name)
        except ModuleNotFoundError as exc:
            pytest.fail('missing morning core interface: ' + str(exc))
    return load
