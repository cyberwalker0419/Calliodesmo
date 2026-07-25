from calliodesmo.config import Settings


def test_settings_defaults():
    s = Settings(_env_file=None)
    assert s.jwt_algorithm == "HS256"
    assert s.jwt_expire_minutes == 60
    assert s.embedding_dimension == 1024
    assert s.database_url.startswith("postgresql+asyncpg://")


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("CALLIODESMO_JWT_SECRET_KEY", "test-secret")
    monkeypatch.setenv("CALLIODESMO_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    s = Settings(_env_file=None)
    assert s.jwt_secret_key == "test-secret"
    assert s.database_url == "sqlite+aiosqlite:///:memory:"
