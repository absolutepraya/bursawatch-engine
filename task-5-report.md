# Task 5 documentation-governance report

## Round 1 correction

The `a37381f` baseline accepted the documentation shape but had not yet reconciled the `idx-market-news-watch` portion of the context audit. This round adds the source-backed candidate identity, cross-provider duplicate, Yahoo quote limitation and degradation, exact text rendering, standalone delivery, and per-item retry contract to its canonical `AGENTS.md`.

The audit's intended regular-session versus official-close rule and quote-degraded heartbeat are not asserted as implemented because the current executable has no session clock or stale-quote validation and does not emit a separate quote-degraded heartbeat. The accepted ADR now makes clear that document-shape acceptance is not a claim that every ignored-context finding had already been reconciled.

## Fix commands and output

The nested worktree does not have `../.venv/bin/python`; the shared repository
environment was used explicitly for each check.

```text
$ /Users/absolutepraya/Documents/Projects/Hermes/.venv/bin/python -m pytest -q idx-market-news-watch/tests/test_packaging.py idx-market-news-watch/tests/test_agent_protocol.py idx-market-news-watch/tests/test_delivery.py idx-market-news-watch/tests/test_selection.py
......................................................                   [100%]
54 passed in 0.12s

$ /Users/absolutepraya/Documents/Projects/Hermes/.venv/bin/python -m pytest -q tests/test_documentation_contract.py
.......                                                                  [100%]
7 passed in 0.01s

$ /Users/absolutepraya/Documents/Projects/Hermes/.venv/bin/python -c 'from pathlib import Path; import re, sys; root=Path.cwd(); missing=[]; pattern=re.compile(r"(?<!!)(?<!<)\\]\\(([^)#?]+)(?:#[^)]+)?\\)"); [missing.append((path, target)) for path in root.rglob("*.md") if ".git" not in path.parts and ".worktrees" not in path.parts for target in pattern.findall(path.read_text(encoding="utf-8")) if not target.startswith(("http://", "https://", "mailto:", "#")) and not (path.parent / target).resolve().exists()]; [print(f"{path.relative_to(root)}: {target}") for path, target in missing]; sys.exit(bool(missing))'
(no output, exit 0)

$ git diff --check
(no output, exit 0)
```

## Fix round 2 checks

The canonical `idx-market-news-watch/AGENTS.md` now documents the implementation's exact quote and replay boundaries: 1D uses Yahoo `fast_info.previous_close` when valid and otherwise `closes[-2]`; same-provider replays must be within seven days and have either two shared normalized facts or strong overlap of at least five tokens and 40% of the smaller source.

```text
$ /Users/absolutepraya/Documents/Projects/Hermes/.venv/bin/python -m pytest -q tests/test_documentation_contract.py
.......                                                                  [100%]
7 passed in 0.02s

$ /Users/absolutepraya/Documents/Projects/Hermes/.venv/bin/python -m pytest -q idx-market-news-watch/tests
........................................................................ [ 57%]
.....................................................                    [100%]
125 passed in 0.90s

$ git diff --check
(no output, exit 0)
```
