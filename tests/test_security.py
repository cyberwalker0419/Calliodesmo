import jwt
import pytest

from calliodesmo.auth.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    hashed = hash_password("s3cret")
    assert hashed != "s3cret"
    assert verify_password("s3cret", hashed)
    assert not verify_password("wrong", hashed)


def test_jwt_roundtrip():
    token = create_access_token("user-123", "secret", "HS256", 30)
    payload = decode_access_token(token, "secret", "HS256")
    assert payload["sub"] == "user-123"
    assert payload["exp"] > payload["iat"]


def test_jwt_expired():
    token = create_access_token("u", "secret", "HS256", -1)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token, "secret", "HS256")


def test_jwt_wrong_secret():
    token = create_access_token("u", "secret", "HS256", 30)
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, "other-secret", "HS256")
