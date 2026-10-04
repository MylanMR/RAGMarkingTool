"""Local-account password hashing: PBKDF2-HMAC-SHA256 (FIPS 140 approved
primitive, stdlib only, no native build needed on Windows Server 2019)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

ITERATIONS = 600_000
MIN_LENGTH = 15


class PasswordPolicyError(ValueError):
    pass


def check_policy(password: str, username: str) -> None:
    if not isinstance(password, str) or len(password) < MIN_LENGTH:
        raise PasswordPolicyError("password must be at least {} characters".format(MIN_LENGTH))
    classes = sum([any(c.islower() for c in password), any(c.isupper() for c in password),
                   any(c.isdigit() for c in password), any(not c.isalnum() for c in password)])
    if classes < 3:
        raise PasswordPolicyError(
            "password must use at least 3 of: lowercase, uppercase, digits, symbols")
    if username and username.lower() in password.lower():
        raise PasswordPolicyError("password must not contain the username")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        ITERATIONS, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iters, salt_b64, hash_b64 = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 base64.b64decode(salt_b64), int(iters))
        return hmac.compare_digest(dk, base64.b64decode(hash_b64))
    except (ValueError, AttributeError, TypeError):
        return False


# Equalizes response time for unknown usernames (no account enumeration).
DUMMY_HASH = hash_password("dummy-password-for-timing-Aa1!")
