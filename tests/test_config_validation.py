"""P9 Task 5：配置校验（`calliodesmo doctor` 的判定内核，纯函数）。"""

from __future__ import annotations

from calliodesmo.config import Settings, get_settings
from calliodesmo.config_validation import (
    ERROR,
    INFO,
    is_local_endpoint,
    summarize,
    validate_settings,
)


def _settings(**overrides) -> Settings:
    """构造与 .env 隔离的 Settings（_env_file=None，避免宿主环境干扰断言）。"""
    base = {
        "environment": "development",
        "database_url": "postgresql+asyncpg://u:p@localhost:5432/db",
        "llm_model": "ollama/qwen2.5",
        "llm_api_key": None,
        "llm_api_base": "http://localhost:11434",
        "jwt_secret_key": "x" * 40,
        "vector_store_backend": "postgres",
        "graph_store_backend": "neo4j",
        "community_store_backend": "postgres",
        "embedding_provider": "hash",
        "reranker_provider": "none",
        "_env_file": None,
    }
    base.update(overrides)
    return Settings(**base)


def _codes(issues) -> set[str]:
    return {issue.code for issue in issues}


def _issue(issues, code):
    return next((issue for issue in issues if issue.code == code), None)


class TestHealthyBaseline:
    def test_minimal_local_config_has_no_errors(self):
        issues = validate_settings(_settings())
        assert [i.level for i in issues if i.level == ERROR] == []

    def test_summarize_counts(self):
        summary = summarize(validate_settings(_settings()))
        assert summary["errors"] == 0
        assert summary["ok"] is True


class TestSecrets:
    def test_default_secret_in_production_is_error(self):
        issues = validate_settings(
            _settings(environment="production", jwt_secret_key="change-me-in-production")
        )
        assert _issue(issues, "jwt_default_secret").level == ERROR

    def test_default_secret_in_development_is_warning(self):
        issues = validate_settings(_settings(jwt_secret_key="change-me-in-production"))
        assert _issue(issues, "jwt_default_secret").level != ERROR

    def test_short_secret_in_production_is_error(self):
        issues = validate_settings(_settings(environment="production", jwt_secret_key="abc"))
        assert _issue(issues, "jwt_secret_too_short").level == ERROR

    def test_wildcard_cors_in_production_warns(self):
        issues = validate_settings(_settings(environment="production", cors_origins=["*"]))
        assert _issue(issues, "cors_wildcard").level != ERROR


class TestBackends:
    def test_sqlite_url_rejected(self):
        issues = validate_settings(_settings(database_url="sqlite+aiosqlite:///./x.db"))
        assert _issue(issues, "database_url_scheme").level == ERROR

    def test_unknown_store_backend_rejected(self):
        issues = validate_settings(_settings(vector_store_backend="mongo"))
        assert _issue(issues, "vector_store_backend").level == ERROR

    def test_neo4j_backend_without_uri(self):
        issues = validate_settings(_settings(graph_store_backend="neo4j", neo4j_uri=""))
        assert _issue(issues, "neo4j_uri").level == ERROR

    def test_community_detector_unknown(self):
        issues = validate_settings(_settings(community_detector="leiden"))
        assert _issue(issues, "community_detector").level == ERROR


class TestModelStack:
    def test_llm_missing_key_remote(self):
        issues = validate_settings(
            _settings(llm_model="openai/gpt-4o-mini", llm_api_key=None, llm_api_base=None)
        )
        assert _issue(issues, "llm_api_key").level == ERROR

    def test_llm_local_exempt(self):
        issues = validate_settings(
            _settings(
                llm_model="openai/local", llm_api_key=None, llm_api_base="http://127.0.0.1:8080/v1"
            )
        )
        assert _issue(issues, "llm_api_key") is None

    def test_llm_ollama_prefix_exempt(self):
        issues = validate_settings(_settings(llm_model="ollama/qwen2.5", llm_api_base=None))
        assert _issue(issues, "llm_api_key") is None

    def test_llm_empty_model(self):
        issues = validate_settings(_settings(llm_model=""))
        assert _issue(issues, "llm_model").level == ERROR

    def test_embedding_remote_without_base(self):
        issues = validate_settings(_settings(embedding_provider="remote", embedding_api_base=None))
        assert _issue(issues, "embedding_api_base").level == ERROR

    def test_reranker_remote_without_base(self):
        issues = validate_settings(_settings(reranker_provider="remote", reranker_api_base=None))
        assert _issue(issues, "reranker_api_base").level == ERROR


class TestNumericBounds:
    def test_chunk_overlap_too_large(self):
        issues = validate_settings(_settings(chunk_size=100, chunk_overlap=100))
        assert _issue(issues, "chunk_overlap").level == ERROR

    def test_alignment_thresholds_inverted(self):
        issues = validate_settings(
            _settings(alignment_auto_merge_threshold=0.8, alignment_review_threshold=0.9)
        )
        assert _issue(issues, "alignment_thresholds").level == ERROR

    def test_threshold_out_of_range(self):
        issues = validate_settings(_settings(alignment_auto_merge_threshold=1.5))
        assert _issue(issues, "alignment_thresholds").level == ERROR

    def test_agent_budget_non_positive(self):
        issues = validate_settings(_settings(agent_max_steps=0))
        assert _issue(issues, "agent_budget").level == ERROR

    def test_negative_retention_is_info(self):
        issues = validate_settings(_settings(audit_retention_days=-1))
        assert _issue(issues, "audit_retention_days").level in (INFO, ERROR)


class TestLocalEndpointHelper:
    def test_matches_factory_rule(self):
        assert is_local_endpoint("http://localhost:11434", "openai/x")
        assert is_local_endpoint("http://127.0.0.1:8080/v1", "openai/x")
        assert is_local_endpoint(None, "ollama/qwen2.5")
        assert is_local_endpoint("", "lm-studio/local")
        assert not is_local_endpoint("http://192.168.1.5:8888/v1", "openai/x")


class TestDoctorCli:
    """`calliodesmo doctor`：纯配置面（--no-check-db）离线可判，error 非零退出。"""

    def test_clean_config_exits_zero(self, monkeypatch):
        from typer.testing import CliRunner

        from calliodesmo.cli import app

        monkeypatch.setenv("CALLIODESMO_ENVIRONMENT", "development")
        monkeypatch.setenv("CALLIODESMO_DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
        monkeypatch.setenv("CALLIODESMO_LLM_MODEL", "ollama/qwen2.5")
        monkeypatch.setenv("CALLIODESMO_JWT_SECRET_KEY", "x" * 40)
        monkeypatch.setenv("CALLIODESMO_VECTOR_STORE_BACKEND", "postgres")
        monkeypatch.setenv("CALLIODESMO_GRAPH_STORE_BACKEND", "neo4j")
        monkeypatch.setenv("CALLIODESMO_COMMUNITY_STORE_BACKEND", "postgres")
        monkeypatch.setenv("CALLIODESMO_COMMUNITY_DETECTOR", "connected_components")
        monkeypatch.delenv("CALLIODESMO_CORS_ORIGINS", raising=False)
        get_settings.cache_clear()
        try:
            result = CliRunner().invoke(app, ["doctor", "--no-check-db"])
        finally:
            get_settings.cache_clear()
        assert result.exit_code == 0, result.output
        assert "配置校验" in result.output
        assert "可以启动" in result.output

    def test_sqlite_url_exits_one(self, monkeypatch):
        from typer.testing import CliRunner

        from calliodesmo.cli import app

        monkeypatch.setenv("CALLIODESMO_DATABASE_URL", "sqlite+aiosqlite:///./dev.db")
        get_settings.cache_clear()
        try:
            result = CliRunner().invoke(app, ["doctor", "--no-check-db"])
        finally:
            get_settings.cache_clear()
        assert result.exit_code == 1
        assert "database_url_scheme" in result.output


class TestDatabasePoolSettings:
    def test_pool_params_valid_by_default(self):
        assert _issue(validate_settings(_settings()), "db_pool") is None

    def test_zero_pool_size_is_error(self):
        issues = validate_settings(_settings(db_pool_size=0))
        assert _issue(issues, "db_pool").level == ERROR

    def test_negative_overflow_is_error(self):
        issues = validate_settings(_settings(db_max_overflow=-1))
        assert _issue(issues, "db_pool").level == ERROR

    def test_sql_echo_decoupled_from_debug(self):
        """echo 不再跟随 debug：DEBUG=true 也不默认回显 SQL。"""
        from calliodesmo.config import Settings

        assert Settings(debug=True, _env_file=None).db_echo is False
