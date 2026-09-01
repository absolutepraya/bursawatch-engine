from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
NO_AGENT_CRONS = {
    "dotfiles-sync", "idx-ssf-watch-phintraco-weekly",
    "idx-swing-watch-phintraco-daily", "job-watcher", "marka-backup",
    "polymarket-signal-watch", "security-audit", "sharing-cleanup",
    "skills-update", "us-etf-dca-watch",
}
AGENT_BACKED_CRONS = {
    "idx-ca-watch", "idx-market-news-watch", "kelas-investasi-gtw-watch",
    "mm-weekly-log-normalizer", "scele-digest", "x-post-watch",
}
ALL_CRONS = NO_AGENT_CRONS | AGENT_BACKED_CRONS
REDUNDANT_ROOT_DOCS = {
    "README.md", "SPEC.md", "DEPLOY.md", "DESIGN.md", "PLAN.md",
    "PROFILE_CONFIGURATION.md", "CRON_PROMPT.md", "CONTEXT.md",
}


def root_markdown_names(cron: str) -> set[str]:
    return {
        path.name
        for path in (ROOT / cron).iterdir()
        if path.is_file() and path.suffix == ".md"
    }


def test_cron_classification_is_complete_and_disjoint() -> None:
    assert NO_AGENT_CRONS.isdisjoint(AGENT_BACKED_CRONS)
    assert len(ALL_CRONS) == 16
    assert all((ROOT / cron).is_dir() for cron in ALL_CRONS)


def test_cron_root_document_shape() -> None:
    for cron in sorted(ALL_CRONS):
        markdown_names = root_markdown_names(cron)
        assert "AGENTS.md" in markdown_names

        if cron in NO_AGENT_CRONS:
            assert "CRON.md" in markdown_names
            assert "SKILL.md" not in markdown_names
        else:
            assert "SKILL.md" in markdown_names
            assert "CRON.md" not in markdown_names


def test_cron_directories_have_no_redundant_or_nested_markdown() -> None:
    for cron in sorted(ALL_CRONS):
        assert not root_markdown_names(cron) & REDUNDANT_ROOT_DOCS
        nested_markdown = {
            path.relative_to(ROOT / cron)
            for path in (ROOT / cron).rglob("*.md")
            if path.parent != ROOT / cron
        }
        assert not nested_markdown


def test_context_map_is_not_active() -> None:
    assert not (ROOT / "CONTEXT-MAP.md").exists()


def test_active_instructions_do_not_link_to_removed_context_files() -> None:
    instruction_paths = [ROOT / "AGENTS.md", ROOT / "README.md"]
    for cron in sorted(ALL_CRONS):
        instruction_paths.extend(
            ROOT / cron / name for name in ("AGENTS.md", "CRON.md", "SKILL.md")
        )

    markdown_link_to_context = re.compile(r"\]\([^)]*CONTEXT\.md(?:[)#?]|$)", re.I)
    for path in instruction_paths:
        if path.is_file():
            assert not markdown_link_to_context.search(path.read_text())
