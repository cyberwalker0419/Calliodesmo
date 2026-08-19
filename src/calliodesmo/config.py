"""应用配置：环境变量 / .env 加载（前缀 CALLIODESMO_）。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CALLIODESMO_", env_file=".env", extra="ignore")

    environment: str = "development"
    debug: bool = True

    database_url: str = "postgresql+asyncpg://calliodesmo:calliodesmo@localhost:5432/calliodesmo"

    # P4.5 Task 2：store 后端选择（memory 默认兼容旧测试；postgres/neo4j 走真后端）
    vector_store_backend: str = "memory"  # memory | postgres
    graph_store_backend: str = "memory"  # memory | neo4j
    community_store_backend: str = "memory"  # memory | postgres

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

    # --- 实体对齐（P4.5 Task 6 三段式：auto_merge / 复核 / 新节点） ---
    # 实体 name+description 向量余弦相似度阈值：>=auto_merge 自动合并；
    # [review, auto_merge) 进人工复核队列；<review 新节点（type 不同一律 new）
    alignment_auto_merge_threshold: float = 0.95
    alignment_review_threshold: float = 0.85

    # --- 模型栈：OCR（PaddleOCR-VL 专职，indoc 逐字转录） ---
    # none（未启用/纯文本文档）| paddleocr（专用引擎）| stub（test/* 自动走桩）
    ocr_provider: str = "none"
    ocr_model: str = "PaddleOCR-VL-1.6"
    ocr_pipeline_version: str = "v1.6"
    # PaddleOCR-VL 识别后端：llama-cpp-server | vllm-server（GGUF / vLLM 部署）
    ocr_vl_backend: str = "llama-cpp-server"
    ocr_server_url: str | None = None  # PaddleOCR 编排 API 地址（llama-server / vLLM）
    ocr_remote: bool = False  # true=远端编排（本机零重型依赖）
    ocr_prompt: str = "OCR:"  # PaddleOCR-VL 提示词（OCR:/Table:/Formula:/Chart:/Seal:）
    ocr_image_max_bytes: int = 15 * 1024 * 1024  # 摄入图片大小上限
    ocr_image_prefer_ocr: bool = False  # 扫描 PDF：pypdf 提取为空才触发 OCR（默认关）

    # --- 模型栈：识图（qwen3-vl 专职，语义理解描述） ---
    # 视觉理解模型（本地 Ollama 默认；云端可切 GPT-4o/Qwen-VL）
    vision_model: str = "ollama/qwen3-vl:8b"
    vision_api_key: str | None = None
    vision_api_base: str | None = None  # 默认空 = Ollama 默认（localhost:11434）
    vision_prompt: str = "请描述这张图片的内容：其中的实体、关系、场景、图表信息等。"
    vision_image_max_bytes: int = 15 * 1024 * 1024  # 提问侧上传图片大小上限

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
