import importlib
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / name / 'bin') for name in (
    'cron-dc-morning-brief', 'lib-news-format', 'lib-sectors', 'lib-chart-img', 'lib-yahoo-market-data',
    'lib-bursawatch-control', 'lib-bursawatch-discord-delivery')]

@pytest.fixture
def core():
    def load(name):
        try:
            return importlib.import_module('morning_brief.' + name)
        except ModuleNotFoundError as exc:
            pytest.fail('missing morning core interface: ' + str(exc))
    return load
