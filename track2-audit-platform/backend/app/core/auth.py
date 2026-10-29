"""Password verification and expiring server-side sessions."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock

from .rbac import Role


class AuthenticationError(PermissionError):
    pass


def hash_password(password: str, salt: bytes | None = None) -> str:
    if len(password) < 8:
        raise ValueError("password must contain at least 8 characters")
    used_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), used_salt, 210_000)
    return f"pbkdf2_sha256$210000${used_salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt_hex, expected_hex = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
        )
        return hmac.compare_digest(actual.hex(), expected_hex)
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True, slots=True)
class UserIdentity:
    user_id: str
    username: str
    password_hash: str
    roles: frozenset[Role]
    active: bool = True


@dataclass(frozen=True, slots=True)
class Session:
    token: str
    user_id: str
    roles: frozenset[Role]
    expires_at: datetime


class AuthService:
    def __init__(
        self,
        users: tuple[UserIdentity, ...],
        *,
        clock: Callable[[], datetime] | None = None,
        session_ttl: timedelta = timedelta(hours=8),
    ) -> None:
        self._users = {user.username.casefold(): user for user in users}
        self._sessions: dict[str, Session] = {}
        self._lock = Lock()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.session_ttl = session_ttl

    def login(self, username: str, password: str) -> Session:
        user = self._users.get(username.strip().casefold())
        if user is None or not user.active or not verify_password(password, user.password_hash):
            raise AuthenticationError("invalid credentials")
        session = Session(
            secrets.token_urlsafe(32), user.user_id, user.roles, self.clock() + self.session_ttl
        )
        with self._lock:
            self._sessions[session.token] = session
        return session

    def authenticate(self, token: str) -> Session:
        with self._lock:
            session = self._sessions.get(token)
            if session is None or session.expires_at <= self.clock():
                if session is not None:
                    del self._sessions[token]
                raise AuthenticationError("session is missing or expired")
            return session

    def logout(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)
