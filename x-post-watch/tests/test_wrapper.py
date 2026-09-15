from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_wrapper_exposes_board_owner_command_without_loading_board_credentials() -> None:
    wrapper = (ROOT / "bin/x-post-watch.sh").read_text()

    assert (
        'export IDX_SWING_PLAN_BOARD_WRAPPER="${IDX_SWING_PLAN_BOARD_WRAPPER:-'
        '$HOME/.hermes/scripts/idx-swing-plan-board.sh}"'
    ) in wrapper
    assert "IDX_SWING_PLAN_BOARD" not in "\n".join(
        line for line in wrapper.splitlines() if "grep -E" in line
    )
