import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_watchdog_wrapper_copied_to_scripts_executes_skill_watchdog_target(tmp_path):
    scripts = tmp_path / "home" / ".hermes" / "scripts"
    scripts.mkdir(parents=True)
    copied_wrapper = scripts / "bursawatch-tg-market-news-watchdog.sh"
    shutil.copy2(ROOT / "bin" / "watchdog-wrapper.sh", copied_wrapper)
    copied_wrapper.chmod(0o755)
    client_token = tmp_path / "delivery-client-token"
    client_token.write_text("test-token\n", encoding="utf-8")
    client_token.chmod(0o600)
    captured_target = tmp_path / "target.txt"
    fake_python = tmp_path / "python"
    fake_python.write_text(f'#!/bin/sh\nprintf "%s" "$1" > "{captured_target}"\n', encoding="utf-8")
    fake_python.chmod(0o755)
    home = tmp_path / "home"
    resilience_module = (
        home / ".agents" / "skills" / "lib-telegram-resilience" / "bin" / "telegram_resilience.py"
    )
    resilience_module.parent.mkdir(parents=True)
    resilience_module.write_text("# test module\n", encoding="utf-8")

    subprocess.run(
        [str(copied_wrapper)],
        check=True,
        env={
            **os.environ,
            "HOME": str(home),
            "IDX_MARKET_NEWS_PYTHON": str(fake_python),
            "BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE": str(client_token),
        },
    )

    assert captured_target.read_text(encoding="utf-8") == str(
        home / ".agents" / "skills" / "bursawatch-tg-market-news" / "bin" / "watchdog.py"
    )
    wrapper = copied_wrapper.read_text(encoding="utf-8")
    assert "BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE" in wrapper
    assert "DISCORD_BOT_TOKEN" not in wrapper
    assert "TELEGRAM_API_ID" not in wrapper
    assert "TELEGRAM_API_HASH" not in wrapper
    assert "POLYCOP_SESSION_STRING" not in wrapper
    assert 'RESILIENCE_BIN="$HOME/.agents/skills/lib-telegram-resilience/bin"' in wrapper
    assert "PYTHONPATH" in wrapper


def test_scanner_and_watchdog_wrappers_share_the_durable_default_state_path():
    scanner = (ROOT / "bin" / "bursawatch-tg-market-news.sh").read_text(encoding="utf-8")
    watchdog = (ROOT / "bin" / "watchdog-wrapper.sh").read_text(encoding="utf-8")
    default = "$HOME/.hermes/state/idx-market-news.json"

    assert default in scanner
    assert default in watchdog
    assert 'export IDX_MARKET_NEWS_STATE_PATH="$STATE_PATH"' in scanner
    assert 'export IDX_MARKET_NEWS_STATE_PATH="${IDX_MARKET_NEWS_STATE_PATH:-$HOME/.hermes/state/idx-market-news.json}"' in watchdog
    assert 'install -d -m 700 "$(dirname "$STATE_PATH")"' in scanner


def test_agents_includes_independent_minutely_watchdog_schedule():
    guide = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "## Independent watchdog schedule" in guide
    assert "watchdog-wrapper.sh" in guide
    assert "* * * * *" in guide
    assert "BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE" in guide
    assert "shared Delivery Owner" in guide
    assert "IDX_MARKET_NEWS_NO_POST=1" in guide
    assert "$HOME/.agents/skills/bursawatch-tg-market-news/bin/watchdog.py" in guide
