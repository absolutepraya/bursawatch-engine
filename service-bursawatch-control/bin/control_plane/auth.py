from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Principal:
    subject: str
    kind: str


class AuthenticationError(ValueError):
    """Raised when a request has no valid control-plane credential."""


class StaticTokenAuth:
    """Development authenticator pending the Supabase JWT verifier."""

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


def secrets_equal(left: str, right: str) -> bool:
    if len(left) != len(right):
        return False
    result = 0
    for left_char, right_char in zip(left.encode(), right.encode(), strict=True):
        result |= left_char ^ right_char
    return result == 0
