"""ECLIndexingEngine：串联 Load -> Extract -> Cognify -> Load -> 文档社区派生 -> 档案卡。

依赖注入 loader/chunker/extractor/cognify/load_service/deriver/profile_deriver/
profile_card_store，端到端离线可跑通（桩 LLM + Hash 嵌入 + 内存 stores）。返回
IngestStats（documents/chunks/entities/relations/communities/profile_cards）。
"""

from __future__ import annotations

from pathlib import Path

from calliodesmo.auth.context import AccessContext
from calliodesmo.ecl.cognify import CognifyPipeline
from calliodesmo.ecl.community_deriver import DocumentCommunityDeriver
from calliodesmo.ecl.load import LoadService
from calliodesmo.ecl.profile_card_deriver import DeterministicProfileCardDeriver
from calliodesmo.interfaces.chunker import Chunker
from calliodesmo.interfaces.document_loader import DocumentLoader
from calliodesmo.interfaces.extractor import Entity, ExtractionResult, Extractor
from calliodesmo.interfaces.indexing_engine import IndexingEngine, IngestStats
from calliodesmo.interfaces.profile_card import ProfileCardDeriver
from calliodesmo.stores.profile_card_store import InMemoryProfileCardStore


class ECLIndexingEngine(IndexingEngine):
    def __init__(
        self,
        *,
        loader: DocumentLoader,
        chunker: Chunker,
        extractor: Extractor,
        cognify: CognifyPipeline,
        load_service: LoadService,
        deriver: DocumentCommunityDeriver,
        profile_deriver: ProfileCardDeriver | None = None,
        profile_card_store: InMemoryProfileCardStore | None = None,
        enable_profile_cards: bool = True,
    ) -> None:
        self.loader = loader
        self.chunker = chunker
        self.extractor = extractor
        self.cognify = cognify
        self.load_service = load_service
        self.deriver = deriver
        self.profile_deriver = profile_deriver
        self.profile_card_store = profile_card_store
        self.enable_profile_cards = enable_profile_cards

    async def ingest(self, source: str | Path, *, access: AccessContext) -> IngestStats:
        docs = await self.loader.load(source)

        # 切分（按文档）
        chunks_by_doc: dict[str, list] = {}
        all_chunks: list = []
        for doc in docs:
            doc_chunks = await self.chunker.chunk(doc)
            chunks_by_doc[doc.doc_id] = doc_chunks
            all_chunks.extend(doc_chunks)

        # 抽取（按文档，合并结果）
        merged = ExtractionResult()
        for doc in docs:
            if not chunks_by_doc[doc.doc_id]:
                continue
            result = await self.extractor.extract(chunks_by_doc[doc.doc_id], access=access)
            merged.entities.extend(result.entities)
            merged.relations.extend(result.relations)
            merged.claims.extend(result.claims)
            merged.covariates.extend(result.covariates)
            merged.discovered_types = sorted(
                set(merged.discovered_types) | set(result.discovered_types)
            )
            merged.schema_mode = result.schema_mode

        # Cognify：建图 + 消解 + 社区检测 + 摘要
        communities, graph = await self.cognify.run(merged, access=access)

        # Load：落三层个人库
        await self.load_service.load(all_chunks, merged, communities, access=access)

        # 文档社区派生（level=1）
        doc_communities = await self.deriver.derive(all_chunks, graph, access=access)

        # 档案卡生成（可选，不阻塞主链路）
        profile_count = await self._derive_profile_cards(merged, graph, access=access)

        return IngestStats(
            documents=len(docs),
            chunks=len(all_chunks),
            entities=len(merged.entities),
            relations=len(merged.relations),
            communities=len(communities) + len(doc_communities),
            profile_cards=profile_count,
        )

    async def _derive_profile_cards(
        self, merged: ExtractionResult, graph: dict, *, access: AccessContext
    ) -> int:
        # 注意：用 `is not None` 而非真值判断——store 实现了 __len__，空时为假
        if (
            not self.enable_profile_cards
            or self.profile_deriver is None
            or self.profile_card_store is None
        ):
            return 0
        nodes = graph.get("nodes", {})
        aliases_map = graph.get("aliases", {})
        cards = []
        for name, node in nodes.items():
            entity = Entity(
                name=node.name,
                type=node.type,
                description=node.description,
                source_chunk_ids=list(node.source_chunk_ids),
                template_conforming=node.template_conforming,
            )
            card = await self.profile_deriver.derive(
                name,
                graph=self.load_service.graph_store,
                covariates=merged.covariates,
                entity=entity,
                access=access,
                aliases=aliases_map.get(name, []),
            )
            cards.append(card)
        await self.profile_card_store.upsert(cards)
        return len(cards)


def build_default_indexing_engine(settings) -> ECLIndexingEngine:
    """按 settings 构造默认 ECLIndexingEngine（内存 stores + Hash 嵌入 + LiteLLM）。

    - LLM 缺 API key（且非本地模型）-> 抛 RuntimeError 指引 CALLIODESMO_LLM_API_KEY
    - 内存 stores 为 P1 默认；pgvector/Neo4j 真后端列为 extra
    - 档案卡生成默认开启（确定性聚合，narrative 默认不生成以省 LLM 调用）
    """
    from calliodesmo.ecl.chunker import TextChunker
    from calliodesmo.ecl.extraction_template import ExtractionTemplateRegistry
    from calliodesmo.ecl.extractor import LLMExtractor
    from calliodesmo.providers.hash_embedding import HashEmbeddingProvider
    from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore
    from calliodesmo.providers.in_memory_graph_store import InMemoryGraphStore
    from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore
    from calliodesmo.providers.litellm_provider import LiteLLMProvider
    from calliodesmo.providers.registry import default_registry

    model = settings.llm_model
    # 本地推理服务（Ollama / LM Studio / llama.cpp 等）经 api_base 指向 localhost，
    # 通常无需 API key；仅当指向远端云服务且未显式豁免时才强制要求 key。
    local_hosts = ("localhost", "127.0.0.1", "0.0.0.0", "::1")
    is_local = bool(settings.llm_api_base) and any(
        h in (settings.llm_api_base or "") for h in local_hosts
    )
    exempt = (
        model.startswith("ollama/")
        or model.startswith("test")
        or model.startswith("lm-studio/")
        or is_local
    )
    if not exempt and not settings.llm_api_key:
        raise RuntimeError(
            "LLM 缺 API key：设置环境变量 CALLIODESMO_LLM_API_KEY"
            "（本地服务可设 CALLIODESMO_LLM_API_BASE 指向 http://localhost:... 自动豁免）"
        )

    llm = LiteLLMProvider(model=model, api_key=settings.llm_api_key, api_base=settings.llm_api_base)
    registry = ExtractionTemplateRegistry.from_yaml(settings.extraction_template_file)
    extractor = LLMExtractor(llm, registry)
    cognify = CognifyPipeline(summarizer=None)  # CLI 默认不跑 LLM 社区摘要（省调用）
    vector_store = InMemoryVectorStore()
    graph_store = InMemoryGraphStore()
    community_store = InMemoryCommunityStore()
    load_service = LoadService(
        vector_store, graph_store, community_store, HashEmbeddingProvider(dimension=64)
    )
    deriver = DocumentCommunityDeriver(llm, community_store)
    profile_card_store = InMemoryProfileCardStore()
    profile_deriver = DeterministicProfileCardDeriver(llm=None)  # 确定性聚合，narrative 默认不生成
    return ECLIndexingEngine(
        loader=default_registry(),
        chunker=TextChunker(chunk_size=settings.chunk_size, overlap=settings.chunk_overlap),
        extractor=extractor,
        cognify=cognify,
        load_service=load_service,
        deriver=deriver,
        profile_deriver=profile_deriver,
        profile_card_store=profile_card_store,
        enable_profile_cards=True,
    )
