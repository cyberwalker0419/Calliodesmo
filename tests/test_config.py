"""Settings 配置测试：默认值 / 前缀加载 / P6 分析配置项 / .env.example 全量对账。"""

import re
from pathlib import Path

from calliodesmo.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_settings_defaults():
    s = Settings(_env_file=None)
    assert s.jwt_algorithm == "HS256"
    assert s.jwt_expire_minutes == 60
    assert s.embedding_dimension == 1024
    assert s.database_url.startswith("postgresql+asyncpg://")


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("CALLIODESMO_JWT_SECRET_KEY", "test-secret")
    monkeypatch.setenv("CALLIODESMO_DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5433/other")
    s = Settings(_env_file=None)
    assert s.jwt_secret_key == "test-secret"
    assert s.database_url == "postgresql+asyncpg://u:p@localhost:5433/other"


def test_analysis_settings_defaults():
    """P6 分析配置 7 项默认值（计划「配置项清单」表锁定）。"""
    s = Settings(_env_file=None)
    assert s.analysis_model == ""  # 空 = 回退 llm_model
    assert s.analysis_max_chunks == 40
    assert s.analysis_max_input_chars == 24000
    assert s.analysis_parse_retries == 2
    assert s.analysis_custom_schema_max_bytes == 4096
    assert s.analysis_temperature == 0.2
    assert s.eval_analysis_golden_file == "config/golden_analysis.yaml"


def test_analysis_settings_env_override(monkeypatch):
    """CALLIODESMO_ 前缀可加载 7 项分析配置。"""
    monkeypatch.setenv("CALLIODESMO_ANALYSIS_MODEL", "openai/gpt-4o")
    monkeypatch.setenv("CALLIODESMO_ANALYSIS_MAX_CHUNKS", "10")
    monkeypatch.setenv("CALLIODESMO_ANALYSIS_MAX_INPUT_CHARS", "6000")
    monkeypatch.setenv("CALLIODESMO_ANALYSIS_PARSE_RETRIES", "0")
    monkeypatch.setenv("CALLIODESMO_ANALYSIS_CUSTOM_SCHEMA_MAX_BYTES", "1024")
    monkeypatch.setenv("CALLIODESMO_ANALYSIS_TEMPERATURE", "0.7")
    monkeypatch.setenv("CALLIODESMO_EVAL_ANALYSIS_GOLDEN_FILE", "config/other.yaml")
    s = Settings(_env_file=None)
    assert s.analysis_model == "openai/gpt-4o"
    assert s.analysis_max_chunks == 10
    assert s.analysis_max_input_chars == 6000
    assert s.analysis_parse_retries == 0  # 可降 0 退化单次解析
    assert s.analysis_custom_schema_max_bytes == 1024
    assert s.analysis_temperature == 0.7
    assert s.eval_analysis_golden_file == "config/other.yaml"


def _env_example_keys() -> set[str]:
    """解析 .env.example 的 Settings 键集合。

    生效行与注释示例行（如 ``# CALLIODESMO_OCR_SERVER_URL=...``）均计入——
    注释示例行已履行「文档化」义务，与计划「12 项欠账」口径一致。
    """
    keys: set[str] = set()
    pattern = re.compile(r"^\s*(?:#\s*)?CALLIODESMO_([A-Z0-9_]+)\s*=")
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    for line in text.splitlines():
        m = pattern.match(line)
        if m:
            keys.add(m.group(1).lower())
    return keys


def test_env_example_covers_all_settings_fields():
    """对账纪律：Settings.model_fields 与 .env.example 键集合双向 diff 为空。"""
    settings_keys = set(Settings.model_fields)
    env_keys = _env_example_keys()
    assert settings_keys - env_keys == set()  # 每个字段都有样例
    assert env_keys - settings_keys == set()  # 无孤儿键（样例领先于字段）
