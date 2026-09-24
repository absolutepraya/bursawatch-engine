from __future__ import annotations

from pathlib import Path


def test_wrapper_uses_restricted_environment_shared_runtime_and_sanitized_log() -> None:
    wrapper = (Path(__file__).resolve().parents[1] / "bin" / "bursawatch-tg-kelas-investasi-gtw.sh").read_text(encoding="utf-8")

    assert 'CONTROL_PLANE_BIN="$HOME/.agents/skills/lib-bursawatch-control/bin"' in wrapper
    assert 'if [[ -d "$CONTROL_PLANE_BIN" ]]; then' in wrapper
    assert 'DELIVERY_CLIENT_BIN="$HOME/.agents/skills/lib-bursawatch-discord-delivery/bin"' in wrapper
    assert 'PYTHONPATH="$DELIVERY_CLIENT_BIN:$CONTROL_PLANE_BIN:$SWING_FORMAT_BIN:$HOME/.agents/skills/lib-telegram-resilience/bin:${PYTHONPATH-}"' in wrapper
    assert 'KELAS_INVESTASI_GTW_NO_POST' not in wrapper
    assert "DISCORD_BOT_TOKEN" not in wrapper
    for key in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "POLYCOP_SESSION_STRING"):
        assert key in wrapper
    assert "BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE" in wrapper
    assert "$HOME/.hermes/secrets/bursawatch-discord-delivery-client-token" in wrapper
    assert '"$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python"' in wrapper
    assert '"$HOME/.logs/bursawatch-tg-kelas-investasi-gtw.log"' in wrapper
    assert '| tee -a "$log_file"' in wrapper
    assert 'exit "$status"' in wrapper
    assert 'IDX_SWING_PLAN_BOARD_WRAPPER="${IDX_SWING_PLAN_BOARD_WRAPPER:-$HOME/.hermes/scripts/bursawatch-dc-swing-board.sh}"' in wrapper
    for key in (
        "KELAS_INVESTASI_GTW_CONTROL_PLANE_URL",
        "KELAS_INVESTASI_GTW_CONTROL_PLANE_WATCHER_ID",
        "KELAS_INVESTASI_GTW_CONTROL_PLANE_TOKEN",
        "KELAS_INVESTASI_GTW_CONTROL_PLANE_TIMEOUT_SECONDS",
        "KELAS_INVESTASI_GTW_CONTROL_PLANE_SPOOL_PATH",
    ):
        assert key in wrapper
