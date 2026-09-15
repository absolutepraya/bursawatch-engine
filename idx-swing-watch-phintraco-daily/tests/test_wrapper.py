from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_wrapper_exports_only_the_shared_polycop_resilience_path() -> None:
    wrapper = (ROOT / "bin/idx-swing-watch-phintraco-daily.sh").read_text()

    assert 'RESILIENCE_BIN="$HOME/.agents/skills/telegram-resilience/bin"' in wrapper
    assert "telegram_resilience.py" in wrapper
    assert "TELEGRAM_SESSION_STRING" not in wrapper


def test_wrapper_exposes_board_owner_command_without_loading_credentials() -> None:
    wrapper = (ROOT / "bin/idx-swing-watch-phintraco-daily.sh").read_text()

    assert (
        'export IDX_SWING_PLAN_BOARD_WRAPPER="${IDX_SWING_PLAN_BOARD_WRAPPER:-'
        '$HOME/.hermes/scripts/idx-swing-plan-board.sh}"'
    ) in wrapper
    assert "IDX_SWING_PLAN_BOARD" not in "\n".join(
        line for line in wrapper.splitlines() if "grep -E" in line
    )
