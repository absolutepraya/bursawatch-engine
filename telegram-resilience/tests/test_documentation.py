from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMMON_STATE_PATH = "~/.hermes/state/telegram-resilience-polyclop.json"


def test_each_polycop_watcher_documents_the_shared_resilience_contract() -> None:
    documents = (
        ROOT / "idx-market-news-watch" / "SKILL.md",
        ROOT / "idx-swing-watch-phintraco-daily" / "CRON.md",
        ROOT / "idx-ssf-watch-phintraco-weekly" / "CRON.md",
        ROOT / "kelas-investasi-gtw-watch" / "SKILL.md",
        ROOT / "polymarket-signal-watch" / "CRON.md",
    )

    for document in documents:
        text = document.read_text(encoding="utf-8")
        assert "telegram-resilience" in text
        assert "POLYCOP_SESSION_STRING" in text
        assert COMMON_STATE_PATH in text
        assert "no-agent" in text
        assert "cursor" in text
        assert "TELEGRAM_SESSION_STRING" not in text


def test_kelas_investasi_gtw_documents_shared_session() -> None:
    text = (ROOT / "kelas-investasi-gtw-watch" / "SKILL.md").read_text(encoding="utf-8")

    for required in (
        "POLYCOP_SESSION_STRING",
        "acquire_probe_after_active_lease",
        "KELAS_INVESTASI_GTW_NO_POST=1",
    ):
        assert required in text


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


def test_resilience_readme_and_kelas_deploy_inventory_and_no_post_boundary() -> None:
    resilience_readme = (ROOT / "telegram-resilience" / "README.md").read_text(encoding="utf-8")
    deploy = (ROOT / "kelas-investasi-gtw-watch" / "DEPLOY.md").read_text(encoding="utf-8")

    assert "five" in resilience_readme
    assert "kelas-investasi-gtw-watch" in resilience_readme
    assert "all five `scan.py` files" in resilience_readme
    assert "KELAS_INVESTASI_GTW_FORCE_HEARTBEAT" not in deploy
    assert "shared Telegram resilience state" in deploy
    assert "KELAS_INVESTASI_GTW_STATE_MEDIA_ROOT=/tmp/kelas-investasi-gtw-media" in deploy
    assert "production-state-free smoke test" in deploy
