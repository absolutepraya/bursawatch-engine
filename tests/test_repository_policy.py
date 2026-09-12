from scripts.repository_policy import violations_for


def test_accepts_reviewed_source_and_examples() -> None:
    assert violations_for([
        ".env.example",
        "idx-market-news-watch/bin/scan.py",
        "mm-weekly-log-normalizer/assets/MM-Log-Kerja-Magang-Daffa-base.docx",
    ]) == []


def test_rejects_runtime_credentials_caches_and_independent_repo() -> None:
    paths = [
        ".env",
        ".worktrees/topic/file.py",
        "cobalt/compose/cookies.json",
        "hermes-agent-starter/README.md",
        "idx-market-news-watch/state.json",
        "mm-weekly-log-normalizer/local-backfill/Pekan-02/draft.docx",
        "watcher/__pycache__/scan.pyc",
        "watcher/state/run.lock",
    ]
    assert violations_for(paths) == sorted(paths)
