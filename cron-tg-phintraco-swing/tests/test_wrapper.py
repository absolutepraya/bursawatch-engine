from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_wrapper_exports_only_the_shared_polycop_resilience_path() -> None:
    wrapper = (ROOT / "bin/bursawatch-tg-phintraco-swing.sh").read_text()

    assert 'RESILIENCE_BIN="$HOME/.agents/skills/lib-telegram-resilience/bin"' in wrapper
    assert "telegram_resilience.py" in wrapper
    assert "TELEGRAM_SESSION_STRING" not in wrapper
    assert "DISCORD_BOT_TOKEN" not in wrapper
    assert 'DELIVERY_CLIENT_BIN="$HOME/.agents/skills/lib-bursawatch-discord-delivery/bin"' in wrapper
    assert "BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE" in wrapper
    assert "$HOME/.hermes/secrets/bursawatch-discord-delivery-client-token" in wrapper


def test_wrapper_exposes_control_plane_only_when_its_shared_library_is_deployed() -> None:
    wrapper = (ROOT / "bin/bursawatch-tg-phintraco-swing.sh").read_text()

    assert 'CONTROL_PLANE_BIN="$HOME/.agents/skills/lib-bursawatch-control/bin"' in wrapper
    assert 'if [[ -d "$CONTROL_PLANE_BIN" ]]; then' in wrapper
    for variable in (
        "IDX_SWING_WATCH_PHINTRACO_DAILY_CONTROL_PLANE_URL",
        "IDX_SWING_WATCH_PHINTRACO_DAILY_CONTROL_PLANE_WATCHER_ID",
        "IDX_SWING_WATCH_PHINTRACO_DAILY_CONTROL_PLANE_TOKEN",
        "IDX_SWING_WATCH_PHINTRACO_DAILY_CONTROL_PLANE_TIMEOUT_SECONDS",
        "IDX_SWING_WATCH_PHINTRACO_DAILY_CONTROL_PLANE_SPOOL_PATH",
    ):
        assert variable in wrapper


def test_wrapper_exposes_board_owner_command_without_loading_credentials() -> None:
    wrapper = (ROOT / "bin/bursawatch-tg-phintraco-swing.sh").read_text()

    assert (
        'export IDX_SWING_PLAN_BOARD_WRAPPER="${IDX_SWING_PLAN_BOARD_WRAPPER:-'
        '$HOME/.hermes/scripts/bursawatch-dc-swing-board.sh}"'
    ) in wrapper
    assert "IDX_SWING_PLAN_BOARD" not in "\n".join(
        line for line in wrapper.splitlines() if "grep -E" in line
    )


def test_wrapper_exposes_shared_source_media_upload_client_and_scope() -> None:
    wrapper = (ROOT / "bin/bursawatch-tg-phintraco-swing.sh").read_text()

    assert 'SOURCE_MEDIA_BIN="$HOME/.agents/skills/lib-bursawatch-source-media/bin"' in wrapper
    assert "$SOURCE_MEDIA_BIN" in "\n".join(
        line for line in wrapper.splitlines() if "PYTHONPATH=" in line
    )
    assert "BURSAWATCH_SOURCE_MEDIA_URL" in wrapper
    assert "BURSAWATCH_SOURCE_MEDIA_UPLOAD_TOKEN_FILE" in wrapper
    assert "$HOME/.hermes/secrets/bursawatch-source-media-upload-token" in wrapper
    assert "http://127.0.0.1:9130" in wrapper


def test_wrapper_loads_private_phintraco_pythonpath_without_replacing_runtime() -> None:
    wrapper = (ROOT / "bin/bursawatch-tg-phintraco-swing.sh").read_text()

    assert "for k in IDX_SWING_WATCH_PHINTRACO_DAILY_PYTHONPATH; do" in wrapper
    assert '|| ! -d "$pythonpath_entry"' in wrapper
    assert 'export PYTHONPATH="$IDX_SWING_WATCH_PHINTRACO_DAILY_PYTHONPATH:$PYTHONPATH"' in wrapper
    assert 'PYTHON_BIN="${IDX_SWING_WATCH_PHINTRACO_DAILY_PY:-$HOME/.local/share/uv/tools/yahoo-finance-mcp/bin/python}"' in wrapper
