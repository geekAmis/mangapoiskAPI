from __future__ import annotations

import asyncio

import pytest
from manga_common.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from manga_common.cache import MemoryCache, cache_key
from manga_common.config import Settings
from manga_common.errors import UnauthorizedError
from manga_common.security import UserClaims, admin_auth_version, require_admin
from manga_common.text import parse_float, parse_int, parse_year, slugify, strip_html


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong", hashed)


def test_jwt_roundtrip_and_expiry() -> None:
    settings = Settings(jwt_secret="unit-test-secret", access_token_minutes=1)
    token, expires_in = create_access_token(settings, subject="user-1", role="admin")
    assert expires_in == 60
    payload = decode_access_token(settings, token)
    assert payload["sub"] == "user-1"
    assert payload["role"] == "admin"
    with pytest.raises(UnauthorizedError):
        decode_access_token(Settings(jwt_secret="another-secret", access_token_minutes=1), token)


def test_admin_session_is_invalidated_by_password_rotation() -> None:
    settings = Settings(
        jwt_secret="unit-test-secret",
        admin_username="admin",
        admin_password="old-password",
    )
    version = admin_auth_version(settings)

    async def scenario() -> None:
        fresh = UserClaims(id="admin", role="admin", raw={"av": version, "username": "admin"})
        await require_admin(fresh, settings)
        rotated = settings.model_copy(update={"admin_password": "new-password"})
        with pytest.raises(UnauthorizedError):
            await require_admin(fresh, rotated)
        legacy = UserClaims(id="admin", role="admin", raw={"username": "admin"})
        with pytest.raises(UnauthorizedError):
            await require_admin(legacy, settings)

    asyncio.run(scenario())


def test_refresh_hash_is_deterministic() -> None:
    token = "refresh-token"
    assert hash_refresh_token(token) == hash_refresh_token(token)
    assert hash_refresh_token(token) != hash_refresh_token(token + "x")


def test_text_helpers() -> None:
    assert strip_html("<p>Привет <b>мир</b></p>") == "Привет мир"
    assert parse_year("2024 г.") == 2024
    assert parse_float("8,7") == 8.7
    assert parse_int("1 234") == 1234
    assert slugify("Во всеоружии") == "vo-vseoruzhii"


def test_memory_cache_ttl() -> None:
    async def scenario() -> None:
        cache = MemoryCache()
        await cache.set_json("a", {"x": 1}, ttl=1)
        assert await cache.get_json("a") == {"x": 1}
        await asyncio.sleep(1.05)
        assert await cache.get_json("a") is None
        assert cache_key("Manga", " Sample ") == "manga:sample"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("jwt_secret", "change-me-to-a-long-random-string", "JWT_SECRET"),
        ("jwt_secret", "dev-jwt-secret-change-me", "JWT_SECRET"),
        ("internal_token", "change-me-to-another-long-random-string", "INTERNAL_TOKEN"),
        ("internal_token", "dev-internal-token-change-me", "INTERNAL_TOKEN"),
        ("admin_password", "change-me-admin-password", "ADMIN_PASSWORD"),
        ("control_secret_key", "change-me-control-secret", "CONTROL_SECRET_KEY"),
        ("control_secret_key", "dev-control-secret-change-me", "CONTROL_SECRET_KEY"),
    ],
)
def test_production_secrets_reject_placeholders(
    field: str, value: str, expected: str
) -> None:
    values = {
        "jwt_secret": "j" * 64,
        "internal_token": "i" * 64,
        "admin_password": "strong-admin-password",
        "control_secret_key": "c" * 64,
    }
    values[field] = value
    settings = Settings(environment="production", **values)

    with pytest.raises(RuntimeError, match=expected):
        settings.validate_production_secrets()


def test_production_secrets_accept_strong_values() -> None:
    settings = Settings(
        environment="production",
        jwt_secret="j" * 64,
        internal_token="i" * 64,
        admin_password="strong-admin-password",
        control_secret_key="c" * 64,
    )
    settings.validate_production_secrets()


def test_development_secrets_allow_defaults() -> None:
    Settings(environment="development").validate_production_secrets()
