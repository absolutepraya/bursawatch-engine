from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import UUID


@dataclass(frozen=True)
class Principal:
    subject: str
    kind: str


class AuthenticationError(ValueError):
    """Raised when a request has no valid control-plane credential."""


class Authenticator(Protocol):
    def authenticate(self, authorization: str | None) -> Principal: ...


class StaticTokenAuth:
    """Machine authenticator and development-only human fallback."""

    def __init__(self, machine_token: str | None, admin_token: str | None) -> None:
        self.machine_token = machine_token
        self.admin_token = admin_token

    @classmethod
    def from_environment(cls) -> "StaticTokenAuth":
        return cls(
            machine_token=os.environ.get("CONTROL_PLANE_MACHINE_TOKEN"),
            admin_token=os.environ.get("CONTROL_PLANE_ADMIN_TOKEN"),
        )

    def authenticate(self, authorization: str | None) -> Principal:
        if type(authorization) is not str or not authorization.startswith("Bearer "):
            raise AuthenticationError("bearer authentication is required")
        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            raise AuthenticationError("bearer authentication is required")
        if self.machine_token and secrets_equal(token, self.machine_token):
            return Principal(subject="machine", kind="machine")
        if self.admin_token and secrets_equal(token, self.admin_token):
            return Principal(subject="static-admin", kind="admin")
        raise AuthenticationError("invalid bearer credential")


def parse_admin_user_ids(value: str | None) -> set[str]:
    if value is None or not value.strip():
        return set()
    user_ids = [item.strip() for item in value.split(",")]
    if any(not item for item in user_ids):
        raise ValueError("CONTROL_PLANE_ADMIN_USER_IDS cannot contain empty values")
    normalized: list[str] = []
    for user_id in user_ids:
        try:
            normalized.append(str(UUID(user_id)))
        except ValueError as exc:
            raise ValueError("CONTROL_PLANE_ADMIN_USER_IDS must contain UUID values") from exc
    if len(normalized) != len(set(normalized)):
        raise ValueError("CONTROL_PLANE_ADMIN_USER_IDS must contain unique UUID values")
    return set(normalized)


class SupabaseJwtAuth:
    """Verify asymmetric Supabase Auth access tokens against the project JWKS."""

    def __init__(
        self,
        project_url: str,
        admin_user_ids: set[str],
        *,
        jwt_module: Any | None = None,
        jwks_client: Any | None = None,
    ) -> None:
        parsed = urlparse(project_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.params or parsed.query or parsed.fragment:
            raise ValueError("CONTROL_PLANE_SUPABASE_URL must be an https project URL without query or fragment")
        self.project_url = project_url.rstrip("/")
        self.issuer = f"{self.project_url}/auth/v1"
        self.admin_user_ids = set(admin_user_ids)
        if jwt_module is None:
            try:
                import jwt as imported_jwt
            except ImportError as exc:
                raise RuntimeError("PyJWT[crypto] is required for Supabase Auth") from exc
            jwt_module = imported_jwt
        self._jwt = jwt_module
        if jwks_client is None:
            jwks_client = self._jwt.PyJWKClient(f"{self.issuer}/.well-known/jwks.json")
        self._jwks_client = jwks_client

    def authenticate(self, authorization: str | None) -> Principal:
        if type(authorization) is not str or not authorization.startswith("Bearer "):
            raise AuthenticationError("bearer authentication is required")
        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            raise AuthenticationError("bearer authentication is required")
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            claims = self._jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "ES256"],
                audience="authenticated",
                issuer=self.issuer,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except Exception as exc:
            raise AuthenticationError("invalid Supabase access token") from exc
        subject = claims.get("sub")
        if type(subject) is not str or not subject:
            raise AuthenticationError("Supabase access token has no valid subject")
        if claims.get("role") != "authenticated":
            raise AuthenticationError("Supabase access token has an unsupported role")
        if claims.get("is_anonymous") is True:
            raise AuthenticationError("anonymous Supabase access tokens are not allowed")
        kind = "admin" if subject in self.admin_user_ids else "viewer"
        return Principal(subject=subject, kind=kind)


class CompositeAuth:
    """Try independent trusted credential mechanisms without crossing roles."""

    def __init__(self, authenticators: list[Authenticator]) -> None:
        self.authenticators = authenticators

    def authenticate(self, authorization: str | None) -> Principal:
        for authenticator in self.authenticators:
            try:
                return authenticator.authenticate(authorization)
            except AuthenticationError:
                continue
        raise AuthenticationError("invalid bearer credential")


def auth_from_environment() -> Authenticator:
    machine_token = os.environ.get("CONTROL_PLANE_MACHINE_TOKEN")
    static_admin_token = os.environ.get("CONTROL_PLANE_ADMIN_TOKEN")
    supabase_url = os.environ.get("CONTROL_PLANE_SUPABASE_URL", "").strip()
    if not supabase_url:
        return StaticTokenAuth(machine_token=machine_token, admin_token=static_admin_token)
    if static_admin_token:
        raise RuntimeError("CONTROL_PLANE_ADMIN_TOKEN must be unset when Supabase Auth is enabled")
    authenticators: list[Authenticator] = [
        SupabaseJwtAuth(supabase_url, parse_admin_user_ids(os.environ.get("CONTROL_PLANE_ADMIN_USER_IDS")))
    ]
    if machine_token:
        authenticators.insert(0, StaticTokenAuth(machine_token=machine_token, admin_token=None))
    return CompositeAuth(authenticators)


def secrets_equal(left: str, right: str) -> bool:
    if len(left) != len(right):
        return False
    result = 0
    for left_char, right_char in zip(left.encode(), right.encode(), strict=True):
        result |= left_char ^ right_char
    return result == 0
