# Task 4 Report: Local OCR benchmark implementation

## Commit

- `96a2efb` Add local Instagram OCR benchmark

## Local files

- `instagram-post-watch/tools/benchmark_ocr.py`
- `instagram-post-watch/tests/test_benchmark_ocr.py`

The CLI supports the required `--input-dir`, `--output`, and `--engine` options, plus `--languages`, `--preprocessing-version`, and `--accuracy-notes`. It processes supported image files recursively in lexical relative-path order, invokes an injected backend or the Task 3 `build_backend`, and writes only the requested JSON output. The report contains engine ID, model version, languages, preprocessing version, per-image relative path and latency, status, character count, confidence, total latency, peak RSS, and sanitized manual accuracy notes.

The benchmark does not call `extract_cached`, create OCR cache files, use watcher state, post to Discord, access the network, or include absolute paths, backend errors, OCR command output, or OCR secrets in the report. Malformed input and an unavailable requested backend return nonzero. Tests inject fake backends, so OCR binaries and packages are not required locally.

## Verification

- Focused benchmark tests: `/Users/absolutepraya/Documents/Projects/Hermes/.venv/bin/python -m pytest -q instagram-post-watch/tests/test_benchmark_ocr.py`
  - Result: `3 passed in 0.04s`
- Instagram test suite: `/Users/absolutepraya/Documents/Projects/Hermes/.venv/bin/python -m pytest -q instagram-post-watch/tests`
  - Result: `184 passed in 0.19s`
- Bytecode compilation: `/Users/absolutepraya/Documents/Projects/Hermes/.venv/bin/python -m py_compile instagram-post-watch/tools/benchmark_ocr.py`
  - Result: passed
- Diff checks: `git diff --check` and `git diff --cached --check`
  - Result: passed

## VPS work intentionally not performed

No VPS connection, VPS preflight, package installation, PaddleOCR environment creation, sample capture, live-account benchmark, `~/rsshub` change, Hermes change, watcher-state change, remote scratch creation, or external-system write was performed.

The exact sanitized VPS package/environment delta still awaiting approval is:

```text
+ system packages: `tesseract-ocr`, `tesseract-ocr-eng`, `tesseract-ocr-ind`
+ isolated environment: one watcher-owned PaddleOCR CPU environment under `~/.local/share/` (exact directory name to be confirmed during preflight)
~ shared Yahoo Finance Python environment: unchanged
~ ~/rsshub: unchanged
~ Hermes configuration, cron registry, and gateway: unchanged
~ deployed Instagram watcher files and watcher state: unchanged
```

The package names and the final isolated environment directory must be confirmed by the VPS preflight before any write. No live package or environment diff was collected because the requested stop boundary is before Task 4 Step 2. Approval is still required before the first VPS dependency write, as specified by the plan.

## Stop point

Work stops after the local implementation, tests, compilation, diff checks, commit, and this report. Task 4 VPS preflight and all subsequent benchmark/deployment actions remain pending explicit approval and were not attempted.
