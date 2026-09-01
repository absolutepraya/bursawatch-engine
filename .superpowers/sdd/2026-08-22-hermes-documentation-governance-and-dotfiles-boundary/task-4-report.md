# Task 4 report: agent-backed cron documentation governance

## Status

Complete. The six agent-backed cron roots now contain only `AGENTS.md` and Hermes-loaded `SKILL.md`. Development, domain, state, safety, deployment, and verification guidance is consolidated into each `AGENTS.md`; `SKILL.md` remains the runtime prompt. No executable code, scheduler record, live state, credential, deployment target, or delivery destination changed.

## Commit

- `1647065141b31dc9365682627b4275ccff85ca28` `docs: consolidate agent-backed cron governance`
- `887fcef a9103f1fd245228b5b9ccbc62d9d9620b` `docs: complete task 4 governance fixes`

## Files changed

- Expanded `AGENTS.md` and retained model-facing `SKILL.md` contracts for `idx-ca-watch`, `idx-market-news-watch`, `kelas-investasi-gtw-watch`, `mm-weekly-log-normalizer`, `scele-digest`, and `x-post-watch`.
- Removed redundant active root documents: `idx-ca-watch/DEPLOY.md`, `idx-market-news-watch/DEPLOY.md`, `kelas-investasi-gtw-watch/{DEPLOY,README,SPEC}.md`, `mm-weekly-log-normalizer/CRON_PROMPT.md`, and `x-post-watch/{PROFILE_CONFIGURATION,README,SPEC}.md`.
- Moved all 14 files from `scele-digest/references/` to `docs/superpowers/references/scele-digest/` as byte-identical renames and linked them from `scele-digest/AGENTS.md`.
- Updated the Market News and shared Telegram-resilience documentation tests to assert transferred `AGENTS.md` guidance instead of removed deploy runbooks.

## Tests

The task brief's `../.venv/bin/python` path resolves to `.worktrees/.venv` from this isolated worktree, where no interpreter exists. I ran the requested targets in fresh processes with the shared repository interpreter at `../../.venv/bin/python`:

```bash
for target in tests/test_documentation_contract.py telegram-resilience/tests/test_documentation.py idx-ca-watch/tests idx-market-news-watch/tests kelas-investasi-gtw-watch/tests mm-weekly-log-normalizer/tests scele-digest/tests x-post-watch/tests; do
  ../../.venv/bin/python -m pytest -q "$target" || exit $?
done
```

Final output:

```text
tests/test_documentation_contract.py: 5 passed in 0.01s
telegram-resilience/tests/test_documentation.py: 4 passed in 0.00s
idx-ca-watch/tests: 43 passed in 0.02s
idx-market-news-watch/tests: 125 passed in 0.87s
kelas-investasi-gtw-watch/tests: 120 passed in 0.12s
mm-weekly-log-normalizer/tests: 89 passed in 0.38s
scele-digest/tests: 18 passed in 0.05s
x-post-watch/tests: 105 passed in 0.12s
```

Total: 509 passed.

## Self-review

- Confirmed all six agent-backed roots list exactly `AGENTS.md` and `SKILL.md`; the repository-wide documentation contract test passed.
- Confirmed all SCELE history moves are `R100` renames and that each moved file has a stable link from `scele-digest/AGENTS.md`.
- Confirmed the documentation diff has no whitespace errors with `git diff --check HEAD`.
- Confirmed no changed path is under a cron `bin/`, `state/`, or `config/` directory and no `.py`, `.sh`, or `.json` executable or runtime file changed.
- Confirmed the commit contains only the reviewed documentation migration, its documentation-test updates, and historical-reference relocations.

## Concerns

None within the approved scope. The task brief supplied the read-only live-registry verification, so no new remote inspection or runtime mutation was performed. No deployment was attempted because this task explicitly excludes deployment targets and scheduler changes.

## Fix round 1

Completed the documentation-only review fixes: restored the required agent-backed domain contracts in `AGENTS.md`, kept `SKILL.md` runtime-only, restored the IDX CA capability and watchdog guidance, completed the X Post profile schema constraints, and extended the documentation-contract policy checks.

Fresh-process verification used the shared repository interpreter because this isolated worktree has no sibling `.venv`:

```bash
for target in tests/test_documentation_contract.py telegram-resilience/tests/test_documentation.py idx-ca-watch/tests idx-market-news-watch/tests kelas-investasi-gtw-watch/tests mm-weekly-log-normalizer/tests scele-digest/tests x-post-watch/tests; do
  ../../.venv/bin/python -m pytest -q "$target" || exit $?
done
```

Exact output:

```text
.......                                                                  [100%]
7 passed in 0.02s
....                                                                     [100%]
4 passed in 0.00s
...........................................                              [100%]
43 passed in 0.03s
........................................................................ [ 57%]
.....................................................                    [100%]
125 passed in 1.12s
........................................................................ [ 60%]
................................................                         [100%]
120 passed in 0.14s
........................................................................ [ 80%]
.................                                                        [100%]
89 passed in 0.47s
..................                                                       [100%]
18 passed in 0.07s
........................................................................ [ 68%]
.................................                                        [100%]
105 passed in 0.14s
```

Total: 511 passed. `git diff --check` passed with no output.

## Fix round 1 finalization

Reviewed the current Task 4 fix diff at `887fcef` against every finding. No additional correction was necessary: the six `AGENTS.md` files contain the transferred current domain and development contracts, the six `SKILL.md` files contain only runtime contracts, the IDX CA capability and watchdog guidance is present, the X Post schema states the five forwarding booleans and actual thread ranges, and the documentation policy test covers governance anchors and deployment-only scheduler instructions.

Fresh-process verification was run from the isolated worktree with the shared repository interpreter because `../.venv/bin/python` is not present from this worktree:

```bash
for target in tests/test_documentation_contract.py telegram-resilience/tests/test_documentation.py idx-ca-watch/tests idx-market-news-watch/tests kelas-investasi-gtw-watch/tests mm-weekly-log-normalizer/tests scele-digest/tests x-post-watch/tests; do
  ../../.venv/bin/python -m pytest -q "$target" || exit $?
done
```

Exact output:

```text
.......                                                                  [100%]
7 passed in 0.02s
....                                                                     [100%]
4 passed in 0.01s
...........................................                              [100%]
43 passed in 0.03s
........................................................................ [ 57%]
.....................................................                    [100%]
125 passed in 0.89s
........................................................................ [ 60%]
................................................                         [100%]
120 passed in 0.13s
........................................................................ [ 80%]
.................                                                        [100%]
89 passed in 0.50s
..................                                                       [100%]
18 passed in 0.06s
........................................................................ [ 68%]
.................................                                        [100%]
105 passed in 0.13s
```

Total: 511 passed.

The final `git diff --check` command completed with no output.

## Fix round 2

Clarified that deployed X Post Watch profile IDs are stable cursor-state namespaces and must not be renamed. Documented that `enabled: false` stops new polling, cursor updates, and queueing, but does not suppress delivery or agent processing of already queued events.

```bash
../../.venv/bin/python -m pytest -q tests/test_documentation_contract.py && ../../.venv/bin/python -m pytest -q x-post-watch/tests
```

Exact output:

```text
.......                                                                  [100%]
7 passed in 0.02s
........................................................................ [ 68%]
.................................                                        [100%]
105 passed in 0.16s
```
