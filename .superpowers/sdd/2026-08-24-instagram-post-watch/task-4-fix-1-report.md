# Task 4 Fix 1 Report: Local OCR benchmark review repairs

## Commit

- `5ffb6b4` Harden Instagram OCR benchmark

## Repairs

- OCR `error`, `timeout`, `unavailable`, uncertain, malformed, and invalid result surfaces now preserve per-image report entries and return nonzero after the sanitized report is written.
- JSON reports use a temporary file in the validated destination directory, flush and `fsync`, `os.replace`, parent-directory `fsync`, and failure cleanup.
- Backend runtime configuration is consulted for effective model version and language set, including Paddle language-specific model selections.
- Built-in Paddle runs fail closed unless `INSTAGRAM_POST_WATCH_PADDLEOCR_OFFLINE=1` and an existing absolute `INSTAGRAM_POST_WATCH_PADDLEOCR_MODEL_DIR` are supplied. Offline/model-source environment variables are scoped before backend construction and execution, and cache locations are directed only to that pre-provisioned directory. Injected fake backends remain usable without these settings.
- Output paths reject symlinked destinations and parents before writing. Input traversal excludes symlink files, reports only POSIX relative paths, and preprocessing versions and notes are bounded and sanitized.
- Backend injection uses `backend is not None`, preserving falsey injected backends.

## Verification

- Focused benchmark tests: `/Users/absolutepraya/Documents/Projects/Hermes/.venv/bin/python -m pytest -q instagram-post-watch/tests/test_benchmark_ocr.py`
  - Result: `14 passed in 0.04s`
- Full Instagram suite: `/Users/absolutepraya/Documents/Projects/Hermes/.venv/bin/python -m pytest -q instagram-post-watch/tests`
  - Result: `195 passed in 0.26s`
- Bytecode compilation: `/Users/absolutepraya/Documents/Projects/Hermes/.venv/bin/python -m py_compile instagram-post-watch/tools/benchmark_ocr.py`
  - Result: passed
- Diff checks: `git diff --check` and `git diff --cached --check`
  - Result: passed

## Remaining sanitized VPS diff and stop boundary

No VPS preflight, package installation, PaddleOCR environment creation, remote scratch creation, Instagram sample capture, live-account benchmark, `~/rsshub` change, Hermes change, watcher-state change, deployment, or external-system write was performed.

The remaining first-VPS-write diff is unchanged:

```text
+ system packages: tesseract-ocr, tesseract-ocr-eng, tesseract-ocr-ind
+ isolated environment: one watcher-owned PaddleOCR CPU environment under ~/.local/share/ (exact directory name to be confirmed during preflight)
~ shared Yahoo Finance Python environment: unchanged
~ ~/rsshub: unchanged
~ Hermes configuration, cron registry, and gateway: unchanged
~ deployed Instagram watcher files and watcher state: unchanged
```

The package availability, exact isolated environment directory, pre-provisioned local model contents, and runtime resource facts still require the planned VPS preflight. Explicit approval remains required before any VPS dependency write. Work stops here, before Task 4 Step 2, with the original VPS stop boundary unchanged.
