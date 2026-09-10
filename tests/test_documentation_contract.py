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
    "idx-market-news-watch", "kelas-investasi-gtw-watch",
    "instagram-post-watch", "mm-weekly-log-normalizer", "scele-digest",
    "whatsapp-channel-watch", "x-post-watch",
}
ALL_CRONS = NO_AGENT_CRONS | AGENT_BACKED_CRONS
REDUNDANT_ROOT_DOCS = {
    "README.md", "SPEC.md", "DEPLOY.md", "DESIGN.md", "PLAN.md",
    "PROFILE_CONFIGURATION.md", "CRON_PROMPT.md",
}
GENERATED_CACHE_DIRECTORIES = {".pytest_cache", ".superpowers", "local-backfill"}
AGENT_GOVERNANCE_ANCHORS = {
    "idx-market-news-watch": (
        "issuer-specific ticker-led standalone news",
        "Anak Usaha <TICKER>",
        "individual company entries in Corporate posts",
        "issuer-specific Special Topics",
    ),
    "kelas-investasi-gtw-watch": (
        "DISCORD_BOT_TOKEN",
        "POLYCOP_SESSION_STRING",
        "matching 15-minute agent lease",
    ),
    "mm-weekly-log-normalizer": (
        "registers the recurring `every 14d` interval",
        "actual successful trigger time",
    ),
    "scele-digest": (
        "todos_added",
        "Include every new deadline key",
        "records candidate keys as consumed",
    ),
    "x-post-watch": (
        "unknown root, profile, channel, or thread fields are rejected",
        "17 to 20 digit ID",
        "age is one to 1,440 minutes",
        "settling is one to 240 minutes",
        "The five forwarding booleans",
        "Surveys, greetings, personal updates",
        "relevance_guard_required",
        "outside the Indonesia or US-listed universe",
        "When the user says `watch this X account <url>`",
        "Propose a complete JSON profile",
        "Do not ask the user to supply facts that the account or source inspection can establish",
    ),
    "instagram-post-watch": (
        "public posts and reels",
        "IG_COOKIE",
        "IG_USERNAME",
        "IG_PASSWORD",
        "127.0.0.1:1201/instagram/2/user/<handle>?format=json",
        "config/watches.json` is the exact JSON configuration boundary",
        "strict validator rejects unknown fields at every object boundary",
        "Credentials, cookies, signed CDN URLs, raw provider response bodies, and local secret paths",
        "vision_partial",
        "vision_full",
        "15-minute agent leases",
        "INSTAGRAM_POST_WATCH_NO_POST=1` suppresses Discord heartbeat delivery and agent claiming",
        "isolated `INSTAGRAM_POST_WATCH_STATE_PATH` and `INSTAGRAM_POST_WATCH_MEDIA_ROOT` paths",
        "must not mutate live state",
        "must not create external messages",
        "deploy.sh instagram-post-watch` copies `bin/` only",
        "exact file comparison",
        "first VPS write",
        "vps:~/.agents/skills/instagram-post-watch/config/watches.json",
        "vps:~/.agents/skills/instagram-post-watch/SKILL.md",
        "SHA-256 checksums",
        "dedicated `rsshub-instagram` dispatcher",
        "first successful observation records the newest source publication",
    ),
    "whatsapp-channel-watch": (
        "existing single Baileys bridge",
        "@newsletter",
        "future-only",
        "Channel sink",
        "no second Baileys session",
    ),
}
DEPLOYMENT_ONLY_SCHEDULER_PATTERNS = (
    re.compile(r"\bregister\b[^.\n]{0,120}\b(?:cron|schedule|interval)\b", re.I),
    re.compile(r"\b(?:create|add|enable|reschedule|retarget)\s+(?:an?\s+)?(?:Hermes\s+)?(?:cron|schedule)\b", re.I),
    re.compile(r"\bHermes starts an interval\b", re.I),
)
README_CRON_TABLE_HEADER = "| Cron | What it is | Mac-runnable? |"


def root_markdown_names(cron: str) -> set[str]:
    return {
        path.name
        for path in (ROOT / cron).iterdir()
        if path.is_file()
        and path.suffix == ".md"
        and path.name != "CONTEXT.md"
    }


def nested_markdown_names(cron_root: Path) -> set[Path]:
    return {
        path.relative_to(cron_root)
        for path in cron_root.rglob("*.md")
        if path.parent != cron_root
        and not (set(path.relative_to(cron_root).parts) & GENERATED_CACHE_DIRECTORIES)
    }


def readme_cron_inventory() -> set[str]:
    lines = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    header_index = lines.index(README_CRON_TABLE_HEADER)
    inventory: set[str] = set()

    for line in lines[header_index + 2:]:
        if not line.startswith("|"):
            break
        match = re.match(r"^\|\s*`([^`]+)`\s*\|", line)
        assert match, f"README.md: malformed cron inventory row {line!r}"
        inventory.add(match.group(1))

    return inventory


def test_cron_classification_is_complete_and_disjoint() -> None:
    assert NO_AGENT_CRONS.isdisjoint(AGENT_BACKED_CRONS), "cron classes overlap"
    assert len(ALL_CRONS) == 17, "update the reviewed cron classification"
    assert all((ROOT / cron).is_dir() for cron in ALL_CRONS), "missing cron source directory"
    assert readme_cron_inventory() == ALL_CRONS, (
        "README.md cron inventory must match the reviewed cron classification"
    )


def test_cron_root_document_shape() -> None:
    for cron in sorted(ALL_CRONS):
        markdown_names = root_markdown_names(cron)
        assert "AGENTS.md" in markdown_names, f"{cron}: missing AGENTS.md"

        if cron in NO_AGENT_CRONS:
            assert "CRON.md" in markdown_names, f"{cron}: missing no-agent CRON.md"
            assert "SKILL.md" not in markdown_names, f"{cron}: no-agent cron has SKILL.md"
        else:
            assert "SKILL.md" in markdown_names, f"{cron}: missing agent-backed SKILL.md"
            assert "CRON.md" not in markdown_names, f"{cron}: agent-backed cron has CRON.md"


def test_cron_directories_have_no_redundant_or_nested_markdown() -> None:
    for cron in sorted(ALL_CRONS):
        redundant_docs = root_markdown_names(cron) & REDUNDANT_ROOT_DOCS
        assert not redundant_docs, f"{cron}: redundant root documents {sorted(redundant_docs)}"
        nested_markdown = nested_markdown_names(ROOT / cron)
        assert not nested_markdown, f"{cron}: nested Markdown {sorted(nested_markdown)}"


def test_nested_markdown_ignores_generated_cache_but_not_source_docs(tmp_path: Path) -> None:
    cache_readme = tmp_path / ".pytest_cache" / "README.md"
    cache_readme.parent.mkdir()
    cache_readme.write_text("generated cache")
    source_doc = tmp_path / "references" / "guide.md"
    source_doc.parent.mkdir()
    source_doc.write_text("source documentation")

    assert nested_markdown_names(tmp_path) == {Path("references/guide.md")}


def test_context_map_is_not_active() -> None:
    assert not (ROOT / "CONTEXT-MAP.md").exists(), "remove root CONTEXT-MAP.md after transfer"


def test_context_files_are_ignored_scratch() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "**/CONTEXT.md" in gitignore


def test_active_instructions_do_not_link_to_removed_context_files() -> None:
    instruction_paths = [ROOT / "AGENTS.md", ROOT / "README.md"]
    for cron in sorted(ALL_CRONS):
        instruction_paths.extend(
            ROOT / cron / name for name in ("AGENTS.md", "CRON.md", "SKILL.md")
        )

    markdown_link_to_context = re.compile(r"\]\([^)]*CONTEXT\.md(?:[)#?]|$)", re.I)
    for path in instruction_paths:
        if path.is_file():
            assert not markdown_link_to_context.search(path.read_text()), (
                f"{path.relative_to(ROOT)}: link to removed CONTEXT.md"
            )


def test_agent_backed_agents_documents_keep_reviewed_governance_anchors() -> None:
    for cron, anchors in AGENT_GOVERNANCE_ANCHORS.items():
        text = (ROOT / cron / "AGENTS.md").read_text(encoding="utf-8")
        for anchor in anchors:
            assert anchor in text, f"{cron}: AGENTS.md missing governance anchor {anchor!r}"


def test_agent_backed_skills_exclude_deployment_only_scheduler_instructions() -> None:
    for cron in AGENT_BACKED_CRONS:
        text = (ROOT / cron / "SKILL.md").read_text(encoding="utf-8")
        for pattern in DEPLOYMENT_ONLY_SCHEDULER_PATTERNS:
            assert not pattern.search(text), (
                f"{cron}: SKILL.md contains deployment-only scheduler instruction {pattern.pattern!r}"
            )
