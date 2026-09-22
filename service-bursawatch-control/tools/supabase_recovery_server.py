#!/usr/bin/env python3
"""Complete a Supabase password recovery redirect on localhost.

The access token stays in the browser URL fragment and is never sent to this
Python server. The page uses it directly with Supabase's authenticated user
endpoint to set a new password.
"""

from __future__ import annotations

import argparse
import getpass
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip("\"'")
    return values


def page(supabase_url: str, publishable_key: str) -> bytes:
    config = json.dumps(
        {"supabaseUrl": supabase_url, "publishableKey": publishable_key},
        separators=(",", ":"),
    )
    document = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Supabase password recovery</title>
<style>
  body {{ font: 16px system-ui, sans-serif; max-width: 36rem; margin: 3rem auto; padding: 0 1rem; }}
  label {{ display: block; margin: 1rem 0 .35rem; }}
  input, button {{ box-sizing: border-box; font: inherit; padding: .65rem; width: 100%; }}
  button {{ margin-top: 1rem; cursor: pointer; }}
  #status {{ white-space: pre-wrap; margin-top: 1rem; }}
</style>
<h1>Set a new password</h1>
<p>This local page uses the recovery session in the URL fragment. The token is not sent to this local server.</p>
<form id="form" hidden>
  <label for="password">New password</label>
  <input id="password" type="password" minlength="8" autocomplete="new-password" required>
  <label for="confirm">Confirm new password</label>
  <input id="confirm" type="password" minlength="8" autocomplete="new-password" required>
  <button type="submit">Set password</button>
</form>
<p id="status">Checking the recovery link...</p>
<script>
const config = {config};
const status = document.getElementById('status');
const form = document.getElementById('form');
const params = new URLSearchParams(window.location.hash.slice(1));
const accessToken = params.get('access_token');
const recoveryType = params.get('type');

if (!accessToken || recoveryType !== 'recovery') {{
  status.textContent = 'No recovery session was found. Open a fresh reset link in this browser.';
}} else {{
  form.hidden = false;
  status.textContent = 'Choose a new password.';
}}

form.addEventListener('submit', async (event) => {{
  event.preventDefault();
  const password = document.getElementById('password').value;
  const confirm = document.getElementById('confirm').value;
  if (password !== confirm) {{
    status.textContent = 'The passwords do not match.';
    return;
  }}
  status.textContent = 'Updating password...';
  try {{
    const response = await fetch(config.supabaseUrl + '/auth/v1/user', {{
      method: 'PUT',
      headers: {{
        'apikey': config.publishableKey,
        'Authorization': 'Bearer ' + accessToken,
        'Content-Type': 'application/json'
      }},
      body: JSON.stringify({{ password }})
    }});
    if (!response.ok) {{
      const body = await response.text();
      throw new Error('Supabase rejected the password update (HTTP ' + response.status + '). ' + body.slice(0, 200));
    }}
    history.replaceState(null, '', window.location.pathname);
    form.hidden = true;
    status.textContent = 'Password updated. You can close this tab and stop the local server.';
  }} catch (error) {{
    status.textContent = error instanceof Error ? error.message : String(error);
  }}
}});
</script>
"""
    return document.encode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--env",
        type=Path,
        default=Path.cwd() / "service-bursawatch-control" / ".env",
        help="ignored control-plane env file",
    )
    parser.add_argument("--port", type=int, default=3000)
    args = parser.parse_args()
    env_path = args.env.expanduser().resolve()
    if not env_path.is_file():
        parser.error(f"env file not found: {env_path}")
    values = load_env(env_path)
    supabase_url = values.get("CONTROL_PLANE_SUPABASE_URL", "").rstrip("/")
    if not supabase_url:
        parser.error("CONTROL_PLANE_SUPABASE_URL is missing from the env file")
    publishable_key = getpass.getpass("Supabase publishable/anon key: ").strip()
    if not publishable_key:
        parser.error("publishable/anon key is required")

    content = page(supabase_url, publishable_key)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            request_path = urlsplit(self.path).path
            if request_path not in {"/", ""}:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, format: str, *args: object) -> None:
            print(f"localhost:3000 {format % args}")

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Recovery page ready at http://127.0.0.1:{args.port}")
    print("Open a fresh Supabase reset link in this browser, then press Ctrl-C here after success.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nRecovery server stopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
