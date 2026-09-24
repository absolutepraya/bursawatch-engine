import pytest

import manage


def sample(status="blocked"):
    return {"key": "news:1", "target": {"channel_id": "123"}, "digest": "a" * 64,
            "status": status, "created_at": "2026-09-24T00:00:00Z", "error_category": "missing_access"}


def test_status_prints_only_sanitized_fields(monkeypatch, capsys):
    monkeypatch.setattr(manage, "_request", lambda *_: {"operations": [sample()]})
    assert manage.main(["status"]) == 0
    text = capsys.readouterr().out
    assert "news:1" in text and "channel_id=123" in text and "missing_access" in text
    assert "content" not in text and "media" not in text


def test_retry_previews_before_apply_and_requires_matching_digest(monkeypatch, capsys):
    calls = []
    def fake_request(method, path, data=None):
        calls.append((method, path, data))
        if method == "GET":
            return {"operations": [sample()]}
        return sample("retrying")
    monkeypatch.setattr(manage, "_request", fake_request)
    assert manage.main(["retry", "news:1", "--expected-digest", "a" * 64]) == 0
    assert all(call[0] == "GET" for call in calls)
    with pytest.raises(RuntimeError):
        manage.main(["retry", "news:1", "--expected-digest", "b" * 64, "--apply"])
    assert all(call[0] == "GET" for call in calls)
    assert manage.main(["retry", "news:1", "--expected-digest", "a" * 64, "--apply"]) == 0
    assert calls[-1][0] == "POST"
    assert calls[-1][2] == {"expected_digest": "a" * 64}
