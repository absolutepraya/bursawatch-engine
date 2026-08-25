from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMMON_STATE_PATH = "~/.hermes/state/telegram-resilience-polyclop.json"


def test_each_polycop_watcher_documents_the_shared_resilience_contract() -> None:
    documents = (
        ROOT / "idx-market-news-watch" / "SKILL.md",
        ROOT / "idx-swing-watch-phintraco-daily" / "SKILL.md",
        ROOT / "idx-ssf-watch-phintraco-weekly" / "SKILL.md",
        ROOT / "polymarket-signal-watch" / "SKILL.md",
    )

    for document in documents:
        text = document.read_text(encoding="utf-8")
        assert "telegram-resilience" in text
        assert "POLYCOP_SESSION_STRING" in text
        assert COMMON_STATE_PATH in text
        assert "no-agent" in text
        assert "cursor" in text
        assert "TELEGRAM_SESSION_STRING" not in text


def test_resilience_readme_requires_safe_probe_and_no_manual_cron_trigger() -> None:
    text = (ROOT / "telegram-resilience" / "README.md").read_text(encoding="utf-8")

    for required in (
        "telegram-resilience-probe.py",
        "--no-notify",
        "/tmp/telegram-resilience-probe-state.json",
        "Do not manually trigger",
        "Do not edit live watcher",
    ):
        assert required in text
