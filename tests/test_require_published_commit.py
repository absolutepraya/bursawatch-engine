from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess


SCRIPT = Path(__file__).parents[1] / "scripts" / "require-published-commit"


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ | {
        "GIT_AUTHOR_NAME": "Hermes Test",
        "GIT_AUTHOR_EMAIL": "hermes@example.invalid",
        "GIT_COMMITTER_NAME": "Hermes Test",
        "GIT_COMMITTER_EMAIL": "hermes@example.invalid",
    }
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )


def repository(tmp_path: Path) -> tuple[Path, Path, Path]:
    origin = tmp_path / "origin.git"
    worktree = tmp_path / "worktree"
    git("init", "--bare", str(origin), cwd=tmp_path)
    git("clone", str(origin), str(worktree), cwd=tmp_path)
    git("switch", "-c", "main", cwd=worktree)
    (worktree / "README.md").write_text("Hermes\n")
    guard = install_guard(worktree)
    git("add", "README.md", "scripts/require-published-commit", cwd=worktree)
    git("commit", "-m", "initial", cwd=worktree)
    git("push", "-u", "origin", "main", cwd=worktree)
    return origin, worktree, guard


def install_guard(worktree: Path) -> Path:
    target = worktree / "scripts" / "require-published-commit"
    target.parent.mkdir()
    shutil.copy2(SCRIPT, target)
    return target


def test_accepts_clean_published_commit(tmp_path: Path) -> None:
    _, worktree, guard = repository(tmp_path)
    result = subprocess.run([str(guard)], cwd=worktree, text=True, capture_output=True)
    assert result.returncode == 0
    assert "published commit:" in result.stdout


def test_rejects_dirty_worktree(tmp_path: Path) -> None:
    _, worktree, guard = repository(tmp_path)
    (worktree / "README.md").write_text("dirty\n")
    result = subprocess.run([str(guard)], cwd=worktree, text=True, capture_output=True)
    assert result.returncode == 1
    assert "not clean" in result.stderr


def test_rejects_local_only_commit(tmp_path: Path) -> None:
    _, worktree, guard = repository(tmp_path)
    (worktree / "README.md").write_text("local only\n")
    git("add", "README.md", cwd=worktree)
    git("commit", "-m", "local only", cwd=worktree)
    result = subprocess.run([str(guard)], cwd=worktree, text=True, capture_output=True)
    assert result.returncode == 1
    assert "not published" in result.stderr
