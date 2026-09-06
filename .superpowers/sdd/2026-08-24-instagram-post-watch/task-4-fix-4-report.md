# Task 4 Fix 4 Report: Verified Paddle sandbox contract

## Commit

- `6927b15` Require verified Paddle benchmark sandbox

## Repairs

- Expanded the Task 3 worker's Python offline guard to deny resolver calls (`getaddrinfo`, `gethostbyname`, `gethostbyname_ex`, `gethostbyaddr`, `getfqdn`, `getnameinfo`), connection calls, and socket `send`, `sendall`, `sendfile`, `sendto`, and `sendmsg` before PaddleOCR import or construction.
- Built-in Paddle now refuses to run without `INSTAGRAM_POST_WATCH_PADDLEOCR_SANDBOX=preflight-verified` and a manifest `verified_runtime` record containing the sandbox marker, Paddle version, and constructor API digest. The manifest continues to bind exact effective selections to digest-validated artifacts and constructor model-directory paths.
- Scoped all Paddle/Hugging Face/cache/HOME/XDG paths to the validated model sandbox, while temporary paths use a dedicated output-scratch directory. `tempfile.tempdir` and the working directory are set for the guarded run and restored on success or exception. Stale or persistent temporary contents fail closed.
- Expanded metadata redaction for arbitrary uppercase secret names, `Authorization: Basic` and `Bearer`, quoted and space-containing values, Unix, Windows, UNC, and relative path forms. Preprocessing secret-like values are rejected, and language metadata remains bounded and normalized.

## Confinement limitation

The Python guard is enforced in the multiprocessing worker before Paddle import and covers the Python socket and resolver entry points tested here. Python monkeypatches cannot prove that native libraries loaded by Paddle or its dependencies cannot bypass those patches. The `preflight-verified` marker is therefore an explicit contract for an OS-level network/filesystem sandbox or equivalent reviewed wrapper. The VPS preflight must verify that wrapper provides no network, read-only model/source access, only the dedicated scratch output write area, and the declared Paddle constructor API and version. This local run does not claim native-library confinement or real Paddle model loading.

## Verification

- Focused benchmark tests: `/Users/absolutepraya/Documents/Projects/Hermes/.venv/bin/python -m pytest -q instagram-post-watch/tests/test_benchmark_ocr.py`
  - Result: `35 passed in 0.13s`
- Full Instagram suite: `/Users/absolutepraya/Documents/Projects/Hermes/.venv/bin/python -m pytest -q instagram-post-watch/tests`
  - Result: `216 passed in 0.23s`
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

The package availability, exact isolated environment directory, OS-level sandbox or reviewed wrapper, real model artifacts and digests, installed PaddleOCR constructor API/version, and runtime resource facts still require the planned VPS preflight. Explicit approval remains required before any VPS dependency write. Work stops here, before Task 4 Step 2, with the original VPS stop boundary unchanged.
