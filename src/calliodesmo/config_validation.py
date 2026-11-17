"""配置校验：把「跑起来才炸」的问题提前到启动前（P9 Task 5，`calliodesmo doctor` 内核）。

设计约束：

- **纯函数**：``validate_settings(settings) -> list[Issue]`` 不连库、不联网、不抛异常，
  因此离线可测、CI 可跑；连通性检查在 ``api/observability`` 侧另做。
- **分级**：``error`` 阻断生产启动（``serve`` 在 ``ENVIRONMENT=production`` 时拒启，
  开发环境只提示）；``warn`` 为便利默认的提醒；``info`` 说明当前取舍（如重排关闭）。
- **本地豁免规则与 ``retrieval/factory`` 同源**：``LOCAL_HOSTS`` / ``is_local_endpoint``
  由本模块定义并被工厂复用，避免「工厂放行、体检报错」两套口径打架。
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from calliodesmo.config import Settings

ERROR = "error"
WARN = "warn"
INFO = "info"

#: 视为「本地服务」的 host 片段（LLM / 识图 key 豁免判定用，与工厂同口径）
LOCAL_HOSTS: tuple[str, ...] = ("localhost", "127.0.0.1", "0.0.0.0", "::1")
#: 免 key 的本地模型前缀
LOCAL_MODEL_PREFIXES = ("ollama/", "lm-studio/")
#: 生产环境必须替换的默认密钥
DEFAULT_JWT_SECRET = "change-me-in-production"
#: JWT 密钥最小长度（HS256 推荐 ≥32 字节，RFC 7518 3.2）
MIN_JWT_SECRET_BYTES = 32

_DATABASE_SCHEMES = ("postgresql+asyncpg", "postgresql")
_VECTOR_BACKENDS = ("memory", "postgres")
_GRAPH_BACKENDS = ("memory", "neo4j")
_COMMUNITY_BACKENDS = ("memory", "postgres")
_EMBEDDING_PROVIDERS = ("hash", "bge-m3", "remote")
_RERANKER_PROVIDERS = ("none", "local", "remote")
_OCR_PROVIDERS = ("none", "stub", "paddleocr")
#: 可用的社区检测器（leiden 尚未实现，networkx_louvain 需 graph-analytics extra）
_COMMUNITY_DETECTORS = ("connected_components", "networkx_louvain")


@dataclass(frozen=True)
class Issue:
    """一条配置体检结论：级别 + 稳定 code（测试与文档引用）+ 可读说明与修复提示。"""

    level: str
    code: str
    message: str
    hint: str = ""


def is_local_endpoint(api_base: str | None, model: str = "") -> bool:
    """本地豁免判定：API base 指向本机，或模型带 ``ollama/`` / ``lm-studio/`` 前缀。"""
    if api_base and any(host in api_base for host in LOCAL_HOSTS):
        return True
    return bool(model) and model.startswith(LOCAL_MODEL_PREFIXES)


def validate_settings(settings: Settings) -> list[Issue]:
    """校验配置，返回问题列表（按检查面分组，顺序稳定，便于逐条断言）。"""
    production = settings.environment.lower() == "production"
    return [
        *_check_database(settings),
        *_check_stores(settings),
        *_check_auth(settings, production=production),
        *_check_models(settings),
        *_check_ecl(settings),
        *_check_agent(settings),
        *_check_ops(settings, production=production),
    ]


def summarize(issues: list[Issue]) -> dict:
    """按级别汇总：``{ok, errors, warnings, infos}``（``ok`` = 无 error 级问题）。"""
    return {
        "ok": not [i for i in issues if i.level == ERROR],
        "errors": len([i for i in issues if i.level == ERROR]),
        "warnings": len([i for i in issues if i.level == WARN]),
        "infos": len([i for i in issues if i.level == INFO]),
    }


# ---------------------------------------------------------------------------
# 构造 helper（统一 code / 提示写法，避免每处手拼长行）
# ---------------------------------------------------------------------------


def _bad_enum(code: str, field: str, value: object, allowed: tuple[str, ...]) -> Issue:
    return Issue(
        ERROR,
        code,
        f"{field}={value!r} 非法（可选 {allowed}）",
        f"改 CALLIODESMO_{field.upper()}",
    )


def _missing(code: str, field: str, message: str, hint: str) -> Issue:
    return Issue(ERROR, code, message, hint)


# ---------------------------------------------------------------------------


def _check_database(settings: Settings) -> list[Issue]:
    url = settings.database_url or ""
    scheme = url.split("://", 1)[0] if "://" in url else ""
    if scheme not in _DATABASE_SCHEMES:
        return [
            Issue(
                ERROR,
                "database_url_scheme",
                f"DATABASE_URL 协议不受支持：{scheme or '(空)'}",
                "P4.5 起仅支持 PostgreSQL + asyncpg（SQLite 模式已移除）："
                "postgresql+asyncpg://user:pass@host:5432/db",
            )
        ]
    issues: list[Issue] = []
    if not urlparse(url).hostname:
        issues.append(Issue(ERROR, "database_url_host", "DATABASE_URL 缺主机名", "检查连接串拼写"))
    if "@" not in url:
        issues.append(
            Issue(
                WARN,
                "database_url_no_credentials",
                "DATABASE_URL 未含凭据",
                "确认经 .pgpass / 环境变量等方式提供",
            )
        )
    return issues


def _check_stores(settings: Settings) -> list[Issue]:
    issues: list[Issue] = []
    for field, value, allowed in (
        ("vector_store_backend", settings.vector_store_backend, _VECTOR_BACKENDS),
        ("graph_store_backend", settings.graph_store_backend, _GRAPH_BACKENDS),
        ("community_store_backend", settings.community_store_backend, _COMMUNITY_BACKENDS),
    ):
        if value not in allowed:
            issues.append(_bad_enum(field, field, value, allowed))
    if settings.graph_store_backend == "neo4j" and not settings.neo4j_uri:
        issues.append(
            _missing(
                "neo4j_uri",
                "neo4j_uri",
                "graph_store_backend=neo4j 但 NEO4J_URI 为空",
                "设置 CALLIODESMO_NEO4J_URI",
            )
        )
    if "memory" in (settings.vector_store_backend, settings.community_store_backend):
        issues.append(
            Issue(
                WARN,
                "store_backend_memory",
                "存在 memory 后端：重启丢数据、多进程不共享",
                "生产全部设 postgres / neo4j",
            )
        )
    if settings.community_detector not in _COMMUNITY_DETECTORS:
        issues.append(
            Issue(
                ERROR,
                "community_detector",
                f"community_detector={settings.community_detector!r} 非法或需 extra",
                "可选 "
                + str(tuple(_COMMUNITY_DETECTORS))
                + "；networkx_louvain 需 `uv sync --extra graph-analytics`",
            )
        )
    return issues


def _check_auth(settings: Settings, *, production: bool) -> list[Issue]:
    issues: list[Issue] = []
    secret = settings.jwt_secret_key or ""
    if secret == DEFAULT_JWT_SECRET:
        issues.append(
            Issue(
                ERROR if production else WARN,
                "jwt_default_secret",
                "JWT_SECRET_KEY 仍是默认值" + ("（生产必须更换）" if production else ""),
                '生成随机串：python -c "import secrets;print(secrets.token_urlsafe(48))"',
            )
        )
    elif len(secret.encode()) < MIN_JWT_SECRET_BYTES:
        issues.append(
            Issue(
                ERROR if production else WARN,
                "jwt_secret_too_short",
                f"JWT_SECRET_KEY 短于 {MIN_JWT_SECRET_BYTES} 字节",
                "HS256 建议 ≥32 字节随机串",
            )
        )
    if settings.allow_self_register and production:
        issues.append(
            Issue(
                WARN,
                "self_register_production",
                "生产开启自注册（clearance 已封顶 INTERNAL）",
                "确认确有需要",
            )
        )
    if production and "*" in (settings.cors_origins or []):
        issues.append(Issue(WARN, "cors_wildcard", "生产环境 CORS 为 *", "收紧为实际域名"))
    return issues


def _check_models(settings: Settings) -> list[Issue]:
    issues: list[Issue] = []
    model = settings.llm_model
    if not model:
        issues.append(
            _missing("llm_model", "llm_model", "LLM_MODEL 为空", "设置 CALLIODESMO_LLM_MODEL")
        )
    elif (
        not model.startswith("test/")
        and not settings.llm_api_key
        and not is_local_endpoint(settings.llm_api_base, model)
    ):
        issues.append(
            Issue(
                ERROR,
                "llm_api_key",
                "远端 LLM 未配置 API key",
                "设置 CALLIODESMO_LLM_API_KEY，或把 API_BASE 指向本地服务自动豁免",
            )
        )
    if settings.embedding_provider not in _EMBEDDING_PROVIDERS:
        issues.append(
            _bad_enum(
                "embedding_provider",
                "embedding_provider",
                settings.embedding_provider,
                _EMBEDDING_PROVIDERS,
            )
        )
    elif settings.embedding_provider == "remote" and not settings.embedding_api_base:
        issues.append(
            _missing(
                "embedding_api_base",
                "embedding_api_base",
                "embedding_provider=remote 但 EMBEDDING_API_BASE 为空",
                "指向 OpenAI 兼容嵌入服务",
            )
        )
    elif settings.embedding_provider == "bge-m3":
        issues.append(
            Issue(
                INFO,
                "embedding_local_extra",
                "bge-m3 本地嵌入需可选 extra",
                "安装：`uv sync --extra embedding-local`",
            )
        )
    if settings.reranker_provider not in _RERANKER_PROVIDERS:
        issues.append(
            _bad_enum(
                "reranker_provider",
                "reranker_provider",
                settings.reranker_provider,
                _RERANKER_PROVIDERS,
            )
        )
    elif settings.reranker_provider == "remote" and not settings.reranker_api_base:
        issues.append(
            _missing(
                "reranker_api_base",
                "reranker_api_base",
                "reranker_provider=remote 但 RERANKER_API_BASE 为空",
                "指向 rerank 服务",
            )
        )
    elif settings.reranker_provider == "none":
        issues.append(
            Issue(INFO, "reranker_disabled", "重排关闭（保序降级）", "要精度可设 local / remote")
        )
    if settings.ocr_provider not in _OCR_PROVIDERS:
        issues.append(
            _bad_enum("ocr_provider", "ocr_provider", settings.ocr_provider, _OCR_PROVIDERS)
        )
    elif (
        settings.ocr_provider == "paddleocr" and settings.ocr_remote and not settings.ocr_server_url
    ):
        issues.append(
            _missing(
                "ocr_server_url",
                "ocr_server_url",
                "OCR_REMOTE=true 但 OCR_SERVER_URL 为空",
                "指向 PaddleOCR 编排服务",
            )
        )
    if not settings.vision_api_key and not is_local_endpoint(
        settings.vision_api_base, settings.vision_model
    ):
        issues.append(
            Issue(
                WARN,
                "vision_api_key",
                "识图模型为远端且未配 key（提问侧附图不可用）",
                "设置 CALLIODESMO_VISION_API_KEY 或改本地端点",
            )
        )
    return issues


def _check_ecl(settings: Settings) -> list[Issue]:
    issues: list[Issue] = []
    if settings.chunk_size <= 0:
        issues.append(
            _missing(
                "chunk_size",
                "chunk_size",
                f"chunk_size={settings.chunk_size} 须 > 0",
                "调 CALLIODESMO_CHUNK_SIZE",
            )
        )
    if settings.chunk_overlap < 0 or settings.chunk_overlap >= settings.chunk_size:
        issues.append(
            _missing(
                "chunk_overlap",
                "chunk_overlap",
                f"chunk_overlap={settings.chunk_overlap} 须落在 [0, chunk_size)",
                "调 CALLIODESMO_CHUNK_OVERLAP",
            )
        )
    auto, review = (
        settings.alignment_auto_merge_threshold,
        settings.alignment_review_threshold,
    )
    if not 0 < auto <= 1 or not 0 < review <= 1:
        issues.append(
            _missing(
                "alignment_thresholds",
                "alignment_*_threshold",
                "实体对齐阈值须落在 (0, 1]",
                "检查 ALIGNMENT_*_THRESHOLD",
            )
        )
    elif review > auto:
        issues.append(
            _missing(
                "alignment_thresholds",
                "alignment_*_threshold",
                "复核阈值高于自动合并阈值（复核带为空）",
                "使 review <= auto_merge",
            )
        )
    if settings.analysis_max_chunks < 1 or settings.analysis_max_input_chars < 1000:
        issues.append(
            _missing(
                "analysis_budget",
                "analysis_max_*",
                "分析预算参数过小",
                "检查 ANALYSIS_MAX_CHUNKS / ANALYSIS_MAX_INPUT_CHARS",
            )
        )
    return issues


def _check_agent(settings: Settings) -> list[Issue]:
    if (
        settings.agent_max_steps < 1
        or settings.agent_token_budget < 1
        or settings.agent_wall_clock_seconds < 1
        or settings.agent_history_window < 1
    ):
        return [
            _missing(
                "agent_budget",
                "agent_*",
                "Agent 预算帽与历史窗口参数须全部为正",
                "检查 AGENT_MAX_STEPS / AGENT_TOKEN_BUDGET / "
                "AGENT_WALL_CLOCK_SECONDS / AGENT_HISTORY_WINDOW",
            )
        ]
    return []


def _check_ops(settings: Settings, *, production: bool) -> list[Issue]:
    issues: list[Issue] = []
    if settings.db_pool_size < 1 or settings.db_max_overflow < 0:
        issues.append(
            _missing(
                "db_pool",
                "db_pool_size / db_max_overflow",
                "连接池参数非法"
                f"（pool_size={settings.db_pool_size}, max_overflow={settings.db_max_overflow}）",
                "pool_size ≥ 1；max_overflow ≥ 0（常驻 + 突发 = 可并发请求数）",
            )
        )
    if settings.audit_retention_days < 0:
        issues.append(
            _missing(
                "audit_retention_days",
                "audit_retention_days",
                f"audit_retention_days={settings.audit_retention_days} 非法（0 = 永久保留）",
                "设为 0 或正整数",
            )
        )
    if production and settings.debug:
        issues.append(
            Issue(WARN, "debug_in_production", "生产开启 debug", "设 CALLIODESMO_DEBUG=false")
        )
    return issues


__all__ = ["ERROR", "INFO", "WARN", "Issue", "is_local_endpoint", "summarize", "validate_settings"]
