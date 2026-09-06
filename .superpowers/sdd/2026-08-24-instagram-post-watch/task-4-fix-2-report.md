# Task 4 Fix 2 Report: Offline Paddle asset boundary

## Commit

- `166beef` Validate offline Paddle OCR assets

## Repairs

- Normalized `paddle` to `paddleocr` before the offline guard, backend construction, and report identity handling. The CLI and programmatic API now apply the same guard to both aliases.
- Replaced directory-exists-only validation with a bounded JSON manifest at `INSTAGRAM_POST_WATCH_PADDLEOCR_MANIFEST`. The manifest must be inside the model root, contain safe relative file names, list regular non-symlink files, and include the exact effective Task 3 selection IDs such as `PP-OCRv5-id` and `PP-OCRv5-en`.
- Rejected symlinked ancestors for model roots, manifests, and listed assets. The complete model tree is snapshotted before execution and any new, removed, or changed file or directory fails closed after execution.
- Expanded note redaction for quoted and space-containing secret values and complete absolute path tokens. Effective runtime languages use the same bounded normalization as CLI languages.
- Preserved all guarded environment values after the benchmark, atomic output behavior, relative-only report paths, and nonzero OCR failure behavior. Fake injected backends remain available for unit tests, while built-in Paddle validation is exercised separately.

## Verification

- Focused benchmark tests: `/Users/absolutepraya/Documents/Projects/Hermes/.venv/bin/python -m pytest -q instagram-post-watch/tests/test_benchmark_ocr.py`
  - Result: `19 passed in 0.08s`
- Full Instagram suite: `/Users/absolutepraya/Documents/Projects/Hermes/.venv/bin/python -m pytest -q instagram-post-watch/tests`
  - Result: `200 passed in 0.28s`
- Bytecode compilation: `/Users/absolutepraya/Documents/Projects/Hermes/.venv/bin/python -m py_compile instagram-post-watch/tools/benchmark_ocr.py`
  - Result: passed
- Diff checks: `git diff --check` and `git diff --cached --check`
  - Result: passed

## Remaining sanitized VPS diff and stop boundary

No VPS preflight, package installation, PaddleOCR environment creation, remote scratch creation, Instagram sample capture, live-account benchmark, network call, `~/rsshub` change, Hermes change, watcher-state change, deployment, or external-system write was performed.

The remaining first-VPS-write diff is unchanged:

```text
+ system packages: tesseract-ocr, tesseract-ocr-eng, tesseract-ocr-ind
+ isolated environment: one watcher-owned PaddleOCR CPU environment under ~/.local/share/ (exact directory name to be confirmed during preflight)
~ shared Yahoo Finance Python environment: unchanged
~ ~/rsshub: unchanged
~ Hermes configuration, cron registry, and gateway: unchanged
~ deployed Instagram watcher files and watcher state: unchanged
```

The package availability, exact isolated environment directory, pre-provisioned model manifest/assets, and runtime resource facts still require the planned VPS preflight. Explicit approval remains required before any VPS dependency write. Work stops here, before Task 4 Step 2, with the original VPS stop boundary unchanged.
