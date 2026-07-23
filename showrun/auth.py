"""Showrun account, password, and API-token primitives."""

from __future__ import annotations

import hashlib
import secrets
from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from time import monotonic

from chirp.security.passwords import hash_password, verify_login

from showrun.store import ShowrunStore, UserRecord

API_TOKEN_PREFIX = "sr_live_"


def normalize_email(value: str) -> str:
    """Return a stable account identifier without pretending to validate delivery."""

    email = value.strip().lower()
    if (
        len(email) > 254
        or "@" not in email
        or email.startswith("@")
        or email.endswith("@")
        or " " in email
    ):
        raise ValueError("Enter a valid email address.")
    return email


def validate_password(value: str) -> str:
    """Apply a small, legible minimum suitable for the hosted alpha."""

    if len(value) < 12:
        raise ValueError("Use at least 12 characters for your password.")
    if len(value) > 256:
        raise ValueError("Password is too long.")
    return value


def validate_name(value: str) -> str:
    name = " ".join(value.split())
    if not name:
        raise ValueError("Enter your name.")
    if len(name) > 80:
        raise ValueError("Name must be 80 characters or fewer.")
    return name


def password_hash(value: str) -> str:
    return hash_password(validate_password(value))


def verify_password(value: str, stored_hash: str | None) -> bool:
    return verify_login(value, stored_hash)


def issue_token() -> tuple[str, str, str]:
    """Return plaintext, display prefix, and one-way digest for an API token."""

    plaintext = f"{API_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
    return plaintext, plaintext[:16], token_digest(plaintext)


def token_digest(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


async def verify_api_token(store: ShowrunStore, plaintext: str) -> UserRecord | None:
    """Resolve a non-revoked token and attach its restricted scopes."""

    resolved = await store.get_user_by_token_hash(token_digest(plaintext))
    if resolved is None:
        return None
    user, scopes = resolved
    await store.touch_api_token(token_digest(plaintext))
    return replace(user, scopes=frozenset(scopes.split()))


@dataclass(slots=True)
class LoginThrottle:
    """Bound login attempts per client in the single-process deployment."""

    attempts: int = 8
    window_seconds: float = 300
    _buckets: dict[str, deque[float]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = monotonic()
        bucket = self._buckets[key]
        cutoff = now - self.window_seconds
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self.attempts:
            return False
        bucket.append(now)
        if len(self._buckets) > 10_000:
            self._buckets = defaultdict(deque, {key: bucket})
        return True
