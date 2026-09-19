from __future__ import annotations

import pytest

from control_plane.auth import (
    AuthenticationError,
    CompositeAuth,
    StaticTokenAuth,
    SupabaseJwtAuth,
    auth_from_environment,
    parse_admin_user_ids,
)


class FakeSigningKey:
    key = "public-key"


class FakeJwks:
    def __init__(self) -> None:
        self.tokens: list[str] = []

    def get_signing_key_from_jwt(self, token: str) -> FakeSigningKey:
        self.tokens.append(token)
        return FakeSigningKey()


class FakeJwt:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def decode(self, token: str, key: str, **kwargs: object) -> dict[str, object]:
        self.calls.append({"token": token, "key": key, **kwargs})
        return self.payload


def test_supabase_auth_verifies_the_expected_issuer_audience_and_algorithms():
    jwks = FakeJwks()
    jwt = FakeJwt(
        {
            "sub": "0d14f8cb-5f72-4a79-94a0-0d682179b6ca",
            "role": "authenticated",
            "is_anonymous": False,
        }
    )
    auth = SupabaseJwtAuth(
        "https://project-ref.supabase.co",
        {"0d14f8cb-5f72-4a79-94a0-0d682179b6ca"},
        jwt_module=jwt,
        jwks_client=jwks,
    )

    principal = auth.authenticate("Bearer user-access-token")

    assert principal.kind == "admin"
    assert principal.subject == "0d14f8cb-5f72-4a79-94a0-0d682179b6ca"
    assert jwks.tokens == ["user-access-token"]
    assert jwt.calls == [
        {
            "token": "user-access-token",
            "key": "public-key",
            "algorithms": ["RS256", "ES256"],
            "audience": "authenticated",
            "issuer": "https://project-ref.supabase.co/auth/v1",
            "options": {"require": ["exp", "iat", "sub", "aud", "iss"]},
        }
    ]


def test_supabase_auth_makes_an_authenticated_non_admin_a_viewer():
    auth = SupabaseJwtAuth(
        "https://project-ref.supabase.co",
        set(),
        jwt_module=FakeJwt({"sub": "user-1", "role": "authenticated", "is_anonymous": False}),
        jwks_client=FakeJwks(),
    )

    assert auth.authenticate("Bearer user-access-token").kind == "viewer"


@pytest.mark.parametrize(
    "payload",
    [
        {"sub": "", "role": "authenticated", "is_anonymous": False},
        {"sub": "user-1", "role": "service_role", "is_anonymous": False},
        {"sub": "user-1", "role": "authenticated", "is_anonymous": True},
    ],
)
def test_supabase_auth_rejects_unsafe_claims(payload):
    auth = SupabaseJwtAuth(
        "https://project-ref.supabase.co",
        set(),
        jwt_module=FakeJwt(payload),
        jwks_client=FakeJwks(),
    )

    with pytest.raises(AuthenticationError):
        auth.authenticate("Bearer user-access-token")


def test_composite_auth_keeps_machine_tokens_separate_from_web_users():
    auth = CompositeAuth(
        [
            StaticTokenAuth(machine_token="machine-token", admin_token=None),
            SupabaseJwtAuth(
                "https://project-ref.supabase.co",
                set(),
                jwt_module=FakeJwt({"sub": "user-1", "role": "authenticated", "is_anonymous": False}),
                jwks_client=FakeJwks(),
            ),
        ]
    )

    assert auth.authenticate("Bearer machine-token").kind == "machine"
    assert auth.authenticate("Bearer user-access-token").kind == "viewer"


def test_admin_user_ids_must_be_unique_uuid_values():
    assert parse_admin_user_ids("0d14f8cb-5f72-4a79-94a0-0d682179b6ca") == {
        "0d14f8cb-5f72-4a79-94a0-0d682179b6ca"
    }
    with pytest.raises(ValueError, match="UUID"):
        parse_admin_user_ids("not-a-uuid")
    with pytest.raises(ValueError, match="unique"):
        parse_admin_user_ids(
            "0d14f8cb-5f72-4a79-94a0-0d682179b6ca,0d14f8cb-5f72-4a79-94a0-0d682179b6ca"
        )


def test_supabase_mode_rejects_the_legacy_static_admin_token(monkeypatch):
    monkeypatch.setenv("CONTROL_PLANE_SUPABASE_URL", "https://project-ref.supabase.co")
    monkeypatch.setenv("CONTROL_PLANE_ADMIN_TOKEN", "legacy-admin-token")

    with pytest.raises(RuntimeError, match="must be unset"):
        auth_from_environment()
