"""密码哈希（pwdlib/Argon2）与 JWT 编解码（PyJWT）。"""

from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

_password_hash = PasswordHash.recommended()


def hash_password(plain: str) -> str:
    return _password_hash.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _password_hash.verify(plain, hashed)


def create_access_token(subject: str, secret_key: str, algorithm: str, expires_minutes: int) -> str:
    now = datetime.now(UTC)
    payload = {"sub": subject, "iat": now, "exp": now + timedelta(minutes=expires_minutes)}
    return jwt.encode(payload, secret_key, algorithm=algorithm)


def decode_access_token(token: str, secret_key: str, algorithm: str) -> dict:
    """解码并校验 JWT；失败抛 jwt.PyJWTError 子类。"""
    return jwt.decode(token, secret_key, algorithms=[algorithm])
