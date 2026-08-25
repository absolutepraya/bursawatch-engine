from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_wrapper_exports_only_the_shared_polycop_resilience_path() -> None:
    wrapper = (ROOT / "bin/idx-swing-watch-phintraco-daily.sh").read_text()

    assert 'RESILIENCE_BIN="$HOME/.agents/skills/telegram-resilience/bin"' in wrapper
    assert "telegram_resilience.py" in wrapper
    assert "TELEGRAM_SESSION_STRING" not in wrapper
