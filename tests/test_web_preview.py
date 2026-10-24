import copy
import importlib.util
import io
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("web_preview", ROOT / "scripts/web_preview.py")
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)
EMAIL = "reviewer@example.test"


class FakeAPI:
    def __init__(self):
        self.items = []
        self.calls = []
        self.fail_delete = False

    def apps(self):
        return iter(copy.deepcopy(self.items))

    def request(self, method, path, body=None, **kwargs):
        self.calls.append((method, path, body))
        if method == "POST":
            app = copy.deepcopy(body)
            app["id"] = str(len(self.items) + 1)
            self.items.append(app)
            return {"result": app}
        if method == "GET":
            return {"result": copy.deepcopy(next(x for x in self.items if path.endswith('/' + x['id'])))}
        if method == "DELETE" and path.startswith("workers/") and self.fail_delete:
            raise RuntimeError("Deletion failed")
        return None  # Includes already absent resources.


@pytest.mark.parametrize("value", ["0", "-1", "../95", "95/production", "1?force=true", "", "1.0", "01", "9999999999"])
def test_invalid_pr_cannot_reach_cloudflare(value):
    api = FakeAPI()
    with pytest.raises(ValueError):
        preview.cleanup(value, api)
    assert not api.calls


def test_preview_config_never_inherits_production_bindings(tmp_path):
    for package in preview.PACKAGES:
        directory = tmp_path / package
        directory.mkdir()
        source = json.loads((ROOT / package / "wrangler.jsonc").read_text())
        source.update(vars={"SECRET": "production"}, services=[{"binding": "BACKEND"}],
                      env={"production": {}}, workers_dev=False, preview_urls=True)
        (directory / "wrangler.jsonc").write_text(json.dumps(source))
    preview.prepare("95", tmp_path)
    for package, target in preview.targets("95").items():
        config = json.loads((tmp_path / package / ".wrangler-preview.json").read_text())
        assert config["name"] == target["name"]
        assert config["account_id"] == preview.ACCOUNT
        assert config["routes"] == []
        assert config["workers_dev"] is True
        assert config["preview_urls"] is False
        assert config["vars"]["BURSAWATCH_PREVIEW_MODE"] == "1"
        assert not {"services", "env", "secrets", "placement"} & config.keys()
        assert "production" not in json.dumps(config)
    landing = json.loads((tmp_path / "web-landing/.wrangler-preview.json").read_text())
    assert landing["vars"]["BURSAWATCH_CONFIG_URL"] == "https://bursawatch-dash-pr-95.absolutepraya.workers.dev"


def test_protect_is_idempotent_and_reads_back_exact_allowlist():
    api = FakeAPI()
    preview.protect("95", api, EMAIL)
    preview.protect("95", api, EMAIL)
    assert len(api.items) == 2
    assert len([x for x in api.calls if x[0] == "POST"]) == 2
    assert len([x for x in api.calls if x[0] == "GET"]) == 4
    for app in api.items:
        assert app["policies"][0]["include"] == [{"email": {"email": EMAIL}}]


def test_protect_rejects_widened_or_foreign_policy():
    api = FakeAPI()
    preview.protect("95", api, EMAIL)
    api.items[0]["policies"][0]["include"] = [{"everyone": {}}]
    with pytest.raises(RuntimeError, match="allowlist"):
        preview.protect("95", api, EMAIL)
    api.items[0]["name"] = "Someone else's app"
    with pytest.raises(RuntimeError, match="owner"):
        preview.cleanup("95", api)


def test_cleanup_deletes_only_fixed_pr_names_before_gates():
    api = FakeAPI()
    preview.protect("95", api, EMAIL)
    api.calls.clear()
    preview.cleanup("95", api)
    assert [(method, path) for method, path, _ in api.calls] == [
        ("DELETE", "workers/services/bursawatch-dash-pr-95"),
        ("DELETE", "workers/services/bursawatch-landing-pr-95"),
        ("DELETE", "access/apps/1"), ("DELETE", "access/apps/2"),
    ]


def test_cleanup_worker_failure_keeps_all_access_gates():
    api = FakeAPI()
    preview.protect("95", api, EMAIL)
    api.calls.clear()
    api.fail_delete = True
    with pytest.raises(RuntimeError):
        preview.cleanup("95", api)
    assert not any(path.startswith("access/") for _, path, _ in api.calls)


def test_failed_deploy_cleanup_retains_gates():
    api = FakeAPI()
    preview.protect("95", api, EMAIL)
    api.calls.clear()
    preview.cleanup("95", api, keep_access=True)
    assert len(api.calls) == 2
    assert all(path.startswith("workers/services/bursawatch-") for _, path, _ in api.calls)


class AnonymousOpener:
    def __init__(self, code=302, location="https://team.cloudflareaccess.com/cdn-cgi/access/login/example"):
        self.code, self.location = code, location
        self.urls = []

    def open(self, url, timeout):
        assert url.get_header("User-agent") == "Bursawatch-Preview-CI/1.0"
        url = url.full_url
        self.urls.append(url)
        raise HTTPError(url, self.code, "test", {"Location": self.location}, io.BytesIO())


def test_verify_checks_pages_assets_and_api_without_following_login():
    opener = AnonymousOpener()
    preview.verify("95", opener)
    assert len(opener.urls) == 7
    assert any(url.endswith("/api/control/watchers") for url in opener.urls)
    assert sum(url.endswith("/favicon.ico") for url in opener.urls) == 2


def test_verify_retries_only_unavailable_routes_during_propagation():
    class PropagatingOpener(AnonymousOpener):
        def open(self, url, timeout):
            if not self.urls:
                self.urls.append(url.full_url)
                raise HTTPError(url.full_url, 404, "not propagated", {}, io.BytesIO())
            return super().open(url, timeout)

    opener = PropagatingOpener()
    preview.verify("95", opener, attempts=2, retry_delay=0)
    assert len(opener.urls) == 8


def test_verify_does_not_retry_a_public_app_response():
    opener = AnonymousOpener(200, "")
    with pytest.raises(RuntimeError, match="HTTP 200"):
        preview.verify("95", opener, attempts=2, retry_delay=0)
    assert len(opener.urls) == 1


@pytest.mark.parametrize("code,location", [
    (200, ""), (403, ""), (302, "https://evil.test/cdn-cgi/access/login/a"),
    (302, "https://team.cloudflareaccess.com.evil.test/cdn-cgi/access/login/a"),
    (302, "https://team.cloudflareaccess.com/other"),
])
def test_verify_rejects_app_content_and_unrelated_redirects(code, location):
    with pytest.raises(RuntimeError, match="not gated"):
        preview.verify("95", AnonymousOpener(code, location))
