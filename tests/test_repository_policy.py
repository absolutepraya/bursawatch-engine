from scripts.repository_policy import violations_for


def test_accepts_reviewed_source_and_examples() -> None:
    assert violations_for([
        ".env.example",
        "cron-tg-market-news/bin/scan.py",
        "service-cobalt/compose/docker-compose.yml",
    ]) == []


def test_rejects_runtime_credentials_caches_and_independent_repo() -> None:
    paths = [
        ".env",
        ".worktrees/topic/file.py",
        "service-cobalt/compose/cookies.json",
        "hermes-agent-starter/README.md",
        "cron-tg-market-news/state.json",
        "watcher/__pycache__/scan.pyc",
        "watcher/state/run.lock",
    ]
    assert violations_for(paths) == sorted(paths)
