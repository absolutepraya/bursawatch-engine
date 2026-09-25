# Bursawatch Source Media client instructions

- Read the repository root `AGENTS.md` and this file before changing this package.
- Keep this client standard-library-only and call only the loopback Source Media Owner.
- Do not add Supabase URLs, Storage credentials, direct provider API calls, or public/signed URL handling.
- Each client instance has one bearer token. The service decides whether that token may upload or read.
- Token files must be regular files with mode `0600`; errors must not include token values, source bytes, or raw provider responses.
- Validate the service response and downloaded SHA-256 before exposing bytes to a caller.
- Tests use loopback fake HTTP only and must never contact Supabase.
