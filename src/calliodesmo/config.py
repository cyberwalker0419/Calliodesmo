"""应用配置：环境变量 / .env 加载（前缀 CALLIODESMO_）。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CALLIODESMO_", env_file=".env", extra="ignore")

    environment: str = "development"
    debug: bool = True

    database_url: str = "postgresql+asyncpg://calliodesmo:calliodesmo@localhost:5432/calliodesmo"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "calliodesmo"

    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    llm_model: str = "openai/gpt-4o-mini"
    llm_api_key: str | None = None
    llm_api_base: str | None = None
    llm_disable_thinking: bool = (
        True  # 对 reasoning 模型禁用思考链（chat_template_kwargs.enable_thinking=False）
    )

    embedding_provider: str = "bge-m3"  # hash | bge-m3 | remote
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimension: int = 1024
    embedding_api_base: str | None = None  # remote 时指向嵌入服务（如 http://host:8082/v1）

    admin_username: str = "admin"
    admin_password: str | None = None

    # P3 Web UI
    allow_self_register: bool = False  # 自注册默认关；开启时 clearance 上限 INTERNAL
    cors_origins: list[str] = []  # 兜底（默认空 = 关）；dev 走 Vite proxy 同源
    demo_dir: str = "data/demo"  # serve --seed-demo 演示文档目录
    demo_cache_file: str = "data/demo/seed-cache.json"  # seed 产物落盘缓存

    # P1 ECL 管线
    extraction_template_file: str = "config/extraction_templates.yaml"
    chunk_size: int = 1200
    chunk_overlap: int = 100
    # 社区检测算法：connected_components（默认零依赖）| networkx_louvain（需 extra graph-analytics）
    # | leiden（v2，需 extra graph-leiden，暂未实现）
    community_detector: str = "connected_components"
    community_resolution: float = 1.0  # louvain/leiden 模块度分辨率（越大社区越细）
    community_seed: int = 42  # louvain/leiden 随机种子（保确定性）
    # 文档社区选项 B（独立嵌入聚类，不依赖实体图）
    doc_community_clustering: bool = True  # ingest 后派生文档聚类社区
    doc_cluster_threshold: float = 0.7  # 文档嵌入相似度阈值（>= 阈值连边 -> 连通分量）

    # P2 检索与 RAG
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_provider: str = "none"  # none | local | remote（remote 走 HTTP rerank 服务）
    reranker_api_base: str | None = None  # remote 时指向 rerank 服务（如 http://rerank-host:8083）
    reranker_api_key: str | None = None
    rerank_top_n: int = 20
    hybrid_enabled: bool = True
    sparse_enabled: bool = True
    local_search_hops: int = 1
    global_top_communities: int = 10
    default_search_mode: str = "native_rag"
    chunk_summary_enabled: bool = False
    eval_golden_file: str = "config/golden_qa.yaml"


@lru_cache
def get_settings() -> Settings:
    return Settings()
