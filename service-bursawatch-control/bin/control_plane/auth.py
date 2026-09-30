from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
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
    """Trusted machine, reconciler, and development-only human credentials."""

    def __init__(
        self,
        machine_token: str | None,
        admin_token: str | None,
        reconciler_token: str | None = None,
        source_endpoint_tokens: dict[str, str] | None = None,
        observer_token: str | None = None,
        publication_owner_tokens: dict[str, str] | None = None,
    ) -> None:
        source_endpoint_tokens = source_endpoint_tokens or {}
        publication_owner_tokens = publication_owner_tokens or {}
        from .publication_model import OWNER_ROUTES
        if set(publication_owner_tokens) - set(OWNER_ROUTES) or any(
            type(token) is not str or len(token) < 32 for token in publication_owner_tokens.values()
        ):
            raise ValueError("publication owner credentials are invalid")
        if len(source_endpoint_tokens) > 500 or any(
            type(endpoint) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._/@-]{0,255}", endpoint)
            or type(token) is not str or len(token) < 32
            for endpoint, token in source_endpoint_tokens.items()
        ):
            raise ValueError("source endpoint credentials are invalid")
        configured_tokens = [
            token
            for token in (machine_token, admin_token, reconciler_token, observer_token)
            if token is not None and token.strip()
        ] + list(source_endpoint_tokens.values()) + list(publication_owner_tokens.values())
        if len(configured_tokens) != len(set(configured_tokens)):
            raise ValueError("control-plane static credentials must use distinct token values")
        self.machine_token = machine_token
        self.admin_token = admin_token
        self.reconciler_token = reconciler_token
        self.observer_token = observer_token
        self.source_endpoint_tokens = dict(source_endpoint_tokens)
        self.publication_owner_tokens = dict(publication_owner_tokens)

    @classmethod
    def from_environment(cls) -> "StaticTokenAuth":
        return cls(
            machine_token=os.environ.get("CONTROL_PLANE_MACHINE_TOKEN"),
            admin_token=os.environ.get("CONTROL_PLANE_ADMIN_TOKEN"),
            reconciler_token=os.environ.get("CONTROL_PLANE_RECONCILER_TOKEN"),
            observer_token=os.environ.get("CONTROL_PLANE_OBSERVER_TOKEN"),
            source_endpoint_tokens=_source_endpoint_tokens_from_environment(),
            publication_owner_tokens=_publication_owner_tokens_from_environment(),
        )

    def authenticate(self, authorization: str | None) -> Principal:
        if type(authorization) is not str or not authorization.startswith("Bearer "):
            raise AuthenticationError("bearer authentication is required")
        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            raise AuthenticationError("bearer authentication is required")
        if self.machine_token and secrets_equal(token, self.machine_token):
            return Principal(subject="machine", kind="machine")
        for endpoint, endpoint_token in self.source_endpoint_tokens.items():
            if secrets_equal(token, endpoint_token):
                return Principal(subject=endpoint, kind="source_machine")
        for owner_id, owner_token in self.publication_owner_tokens.items():
            if secrets_equal(token, owner_token):
                return Principal(subject=owner_id, kind="publication_owner")
        if self.reconciler_token and secrets_equal(token, self.reconciler_token):
            return Principal(subject="schedule-reconciler", kind="reconciler")
        if self.observer_token and secrets_equal(token, self.observer_token):
            return Principal(subject="hermes-observer", kind="observer")
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
    reconciler_token = os.environ.get("CONTROL_PLANE_RECONCILER_TOKEN")
    observer_token = os.environ.get("CONTROL_PLANE_OBSERVER_TOKEN")
    source_endpoint_tokens = _source_endpoint_tokens_from_environment()
    publication_owner_tokens = _publication_owner_tokens_from_environment()
    supabase_url = os.environ.get("CONTROL_PLANE_SUPABASE_URL", "").strip()
    if not supabase_url:
        return StaticTokenAuth(
            machine_token=machine_token,
            admin_token=static_admin_token,
            reconciler_token=reconciler_token,
            observer_token=observer_token,
            source_endpoint_tokens=source_endpoint_tokens,
            publication_owner_tokens=publication_owner_tokens,
        )
    if static_admin_token:
        raise RuntimeError("CONTROL_PLANE_ADMIN_TOKEN must be unset when Supabase Auth is enabled")
    authenticators: list[Authenticator] = [
        SupabaseJwtAuth(supabase_url, parse_admin_user_ids(os.environ.get("CONTROL_PLANE_ADMIN_USER_IDS")))
    ]
    if machine_token or reconciler_token or observer_token or source_endpoint_tokens or publication_owner_tokens:
        authenticators.insert(
            0,
            StaticTokenAuth(
                machine_token=machine_token,
                admin_token=None,
                reconciler_token=reconciler_token,
                observer_token=observer_token,
                source_endpoint_tokens=source_endpoint_tokens,
                publication_owner_tokens=publication_owner_tokens,
            ),
        )
    return CompositeAuth(authenticators)


def _source_endpoint_tokens_from_environment() -> dict[str, str]:
    raw = os.environ.get("CONTROL_PLANE_SOURCE_ENDPOINT_TOKENS", "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("source endpoint credential mapping is invalid") from exc
    if type(value) is not dict:
        raise ValueError("source endpoint credential mapping must be an object")
    return value


def _publication_owner_tokens_from_environment() -> dict[str, str]:
    raw = os.environ.get("CONTROL_PLANE_PUBLICATION_OWNER_TOKENS", "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("publication owner credential mapping is invalid") from exc
    if type(value) is not dict:
        raise ValueError("publication owner credential mapping must be an object")
    return value


def secrets_equal(left: str, right: str) -> bool:
    if len(left) != len(right):
        return False
    result = 0
    for left_char, right_char in zip(left.encode(), right.encode(), strict=True):
        result |= left_char ^ right_char
    return result == 0
