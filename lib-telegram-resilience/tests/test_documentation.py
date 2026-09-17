from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMMON_STATE_PATH = "~/.hermes/state/telegram-resilience-polyclop.json"


def test_each_polycop_watcher_documents_the_shared_resilience_contract() -> None:
    documents = (
        ROOT / "cron-tg-market-news" / "SKILL.md",
        ROOT / "cron-tg-phintraco-swing" / "CRON.md",
        ROOT / "cron-tg-kelas-investasi-gtw" / "SKILL.md",
    )

    for document in documents:
        text = document.read_text(encoding="utf-8")
        assert "lib-telegram-resilience" in text
        assert "POLYCOP_SESSION_STRING" in text
        assert COMMON_STATE_PATH in text
        assert "no-agent" in text
        assert "cursor" in text
        assert "TELEGRAM_SESSION_STRING" not in text


def test_kelas_investasi_gtw_documents_shared_session() -> None:
    text = (ROOT / "cron-tg-kelas-investasi-gtw" / "SKILL.md").read_text(encoding="utf-8")

    for required in (
        "POLYCOP_SESSION_STRING",
        "acquire_probe_after_active_lease",
        "KELAS_INVESTASI_GTW_NO_POST=1",
    ):
        assert required in text


def test_resilience_readme_requires_safe_probe_and_no_manual_cron_trigger() -> None:
    text = (ROOT / "lib-telegram-resilience" / "README.md").read_text(encoding="utf-8")

    for required in (
        "telegram-resilience-probe.py",
        "--no-notify",
        "/tmp/telegram-resilience-probe-state.json",
        "Do not manually trigger",
        "Do not edit live watcher",
    ):
        assert required in text


def test_resilience_readme_and_kelas_agents_inventory_and_no_post_boundary() -> None:
    resilience_readme = (ROOT / "lib-telegram-resilience" / "README.md").read_text(encoding="utf-8")
    agents = (ROOT / "cron-tg-kelas-investasi-gtw" / "AGENTS.md").read_text(encoding="utf-8")

    assert "four" in resilience_readme
    assert "bursawatch-tg-kelas-investasi-gtw" in resilience_readme
    assert "all remaining scanner files" in resilience_readme
    assert "KELAS_INVESTASI_GTW_FORCE_HEARTBEAT" not in agents
    assert "lib-telegram-resilience" in agents
    assert "KELAS_INVESTASI_GTW_STATE_MEDIA_ROOT=/tmp/kelas-investasi-gtw-media" in agents
    assert "production-state-free smoke test" in agents
