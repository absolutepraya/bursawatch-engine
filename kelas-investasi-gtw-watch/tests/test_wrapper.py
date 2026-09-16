from __future__ import annotations

from pathlib import Path


def test_wrapper_uses_restricted_environment_shared_runtime_and_sanitized_log() -> None:
    wrapper = (Path(__file__).resolve().parents[1] / "bin" / "kelas-investasi-gtw-watch.sh").read_text(encoding="utf-8")

    assert 'PYTHONPATH="$SWING_FORMAT_BIN:$HOME/.agents/skills/telegram-resilience/bin"' in wrapper
    assert 'KELAS_INVESTASI_GTW_NO_POST' not in wrapper
    for key in ("DISCORD_BOT_TOKEN", "TELEGRAM_API_ID", "TELEGRAM_API_HASH", "POLYCOP_SESSION_STRING"):
        assert key in wrapper
    assert '"$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python"' in wrapper
    assert '"$HOME/.logs/kelas-investasi-gtw-watch.log"' in wrapper
    assert '| tee -a "$log_file"' in wrapper
    assert 'exit "$status"' in wrapper
    assert 'IDX_SWING_PLAN_BOARD_WRAPPER="${IDX_SWING_PLAN_BOARD_WRAPPER:-$HOME/.hermes/scripts/idx-swing-plan-board.sh}"' in wrapper
