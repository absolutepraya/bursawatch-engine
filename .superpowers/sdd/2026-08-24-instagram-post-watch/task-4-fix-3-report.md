# Task 4 Fix 3 Report: Hard offline Paddle boundary

## Commit

- `74782e1` Enforce offline Paddle OCR benchmark boundary

## Repairs

- Built-in `paddle` and `paddleocr` runs now set a scoped hard-offline flag. Task 3's multiprocessing worker installs a process-local guard before importing or constructing PaddleOCR, denying DNS resolution, socket connect, connect-ex, sendto, and sendmsg attempts. A simulated worker network attempt is covered by a regression.
- Paddle, Hugging Face, cache, HOME, XDG, and temporary-directory locations are directed to the validated model sandbox. All changed environment variables, including the hard-offline and binding variables, are restored on success and exception.
- The manifest now maps each effective selection to a model directory, explicit artifact paths, SHA-256 digests, and constructor path bindings. Artifacts must be regular non-symlink, non-hardlink files, at least 1 KiB, and digest-valid. Missing, mismatched, one-byte, or unexpected files fail closed. The worker revalidates the same bindings and digests immediately before Paddle import/construction, then merges the validated absolute model-directory kwargs into the Paddle constructor.
- Notes now redact common `ACCESS_TOKEN`, `CLIENT_SECRET`, `SECRET_KEY`, and `Authorization: Bearer` forms, including quoted and space-containing values. Alias handling, symlink ancestor checks, atomic output, metadata sanitization, and nonzero OCR failure behavior remain intact.

## Local API limitation and exact VPS preflight requirement

PaddleOCR is not installed locally, so its installed constructor keyword names and model-directory semantics were not guessed. The benchmark therefore requires a manifest `constructor_kwargs` mapping whose values resolve to the validated selection model directory, and Task 3 passes those exact absolute paths to `PaddleOCR`. The local tests use a fake backend and a synthetic digest-backed fixture only to test enforcement mechanics. Before any VPS benchmark, the preflight must verify the installed PaddleOCR API accepts the selected constructor keys and that the real PP-OCRv5 Indonesian and English artifacts load from those paths without downloading or writing outside the sandbox. A preflight failure must stop the benchmark.

## Verification

- Focused benchmark tests: `/Users/absolutepraya/Documents/Projects/Hermes/.venv/bin/python -m pytest -q instagram-post-watch/tests/test_benchmark_ocr.py`
  - Result: `24 passed in 0.09s`
- Full Instagram suite: `/Users/absolutepraya/Documents/Projects/Hermes/.venv/bin/python -m pytest -q instagram-post-watch/tests`
  - Result: `205 passed in 0.21s`
- Bytecode compilation: `/Users/absolutepraya/Documents/Projects/Hermes/.venv/bin/python -m py_compile instagram-post-watch/tools/benchmark_ocr.py instagram-post-watch/bin/ocr.py`
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

The package availability, exact isolated environment directory, real model artifacts and digests, installed PaddleOCR constructor path keys, and runtime resource facts still require the planned VPS preflight. Explicit approval remains required before any VPS dependency write. Work stops here, before Task 4 Step 2, with the original VPS stop boundary unchanged.
