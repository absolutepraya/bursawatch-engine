from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "bin" / "idx-ssf-watch-phintraco-weekly.sh"


def test_wrapper_has_weekly_ssf_identity_and_dry_run_support() -> None:
    script = WRAPPER.read_text()

    assert "IDX_SSF_WATCH_PHINTRACO_WEEKLY_NO_POST" in script
    assert "idx-ssf-watch-phintraco-weekly" in script
    assert "IDX_SWING_WATCH" not in script


def test_wrapper_pins_one_canonical_production_state_path() -> None:
    script = WRAPPER.read_text()

    assert "export IDX_SSF_WATCH_PHINTRACO_WEEKLY_STATE_PATH=" in script
    assert "$HOME/.hermes/state/idx-ssf-watch-phintraco-weekly.json" in script


def test_wrapper_exports_only_the_shared_polycop_resilience_path() -> None:
    script = WRAPPER.read_text()

    assert 'RESILIENCE_BIN="$HOME/.agents/skills/telegram-resilience/bin"' in script
    assert "telegram_resilience.py" in script
    assert "TELEGRAM_SESSION_STRING" not in script
