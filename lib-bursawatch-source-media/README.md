# Bursawatch Source Media client

This standard-library client talks only to the local Source Media Owner at `http://127.0.0.1:9130`. Give upload callers an upload-scoped token file and domain readers a separate read-scoped token file. Tokens must be regular files with mode `0600`.

```python
from pathlib import Path
from bursawatch_source_media import SourceMediaClient

uploader = SourceMediaClient(
    "http://127.0.0.1:9130",
    Path("/home/praya/.hermes/secrets/bursawatch-source-media-upload-token"),
)
media_ref = uploader.upload(
    "telegram:channel:123:message:456:attachment:0",
    image_bytes,
    kind="image",
    content_type="image/jpeg",
    filename="chart.jpg",
)

reader = SourceMediaClient(
    "http://127.0.0.1:9130",
    Path("/home/praya/.hermes/secrets/bursawatch-source-media-read-token"),
)
download = reader.download(media_ref["ref"])
```

`upload` returns the stable source-event media-ref dictionary (`ref`, `sha256`, `kind`, `content_type`, `size_bytes`, `filename`, `durable`). The server derives the ref from the idempotency key, normalizes filenames to the Control Plane's bounded ASCII label format, rejects a changed payload for an existing key, and confirms durability before returning. Keep the same key and exact media metadata when retrying an upload.

`download` returns a `MediaDownload` with `data`, `content_type`, `filename`, `kind`, and `sha256`. The client verifies the downloaded body digest and size against response metadata before returning it. Each call carries one token, so an upload-only token cannot perform reads and a read-only token cannot upload.

The client rejects non-loopback URLs, does not follow redirects, and never constructs Supabase requests. It does not send source media bytes through Control Plane or Discord Delivery APIs by URL; a domain owner passes retrieved bytes to the existing output owner.

`summary_images` prepares optional original-image context only after the domain
owner's text eligibility decision and active-claim check. It reads verified
opaque refs through this client, cross-checks immutable source metadata, and
stages private assets (directories 0700, files 0600). Source association and
order survive. Defaults are four selected images, 8 MiB each, 25 MiB total,
8 seconds per request and 20 seconds aggregate; limits are injectable. Four
process-wide daemon slots prevent unbounded stalled reads. Late reads never
stage assets. Failures return partial/unavailable context for a text fallback,
without model calls, OCR, source discovery or required-media delivery changes.
`download` accepts optional `max_bytes` and `timeout_seconds` bounds; existing
calls retain their behavior. Cleanup removes only the specified private
analysis binding, without touching source media or delivery attachments.
