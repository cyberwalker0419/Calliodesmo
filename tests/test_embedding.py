import math
import sys

import pytest

from calliodesmo.providers.bge_m3 import BgeM3EmbeddingProvider
from calliodesmo.providers.hash_embedding import HashEmbeddingProvider


async def test_hash_embedding_deterministic_and_normalized():
    provider = HashEmbeddingProvider(dimension=32)
    assert provider.dimension == 32

    r1 = await provider.embed(["情报分析", "知识图谱"])
    r2 = await provider.embed(["情报分析"])

    assert r1.dimension == 32
    assert len(r1.vectors) == 2
    assert r1.vectors[0] == r2.vectors[0]  # 确定性
    norm = math.sqrt(sum(x * x for x in r1.vectors[0]))
    assert norm == pytest.approx(1.0)  # 单位归一化
    assert r1.vectors[0] != r1.vectors[1]  # 不同文本不同向量


async def test_bge_m3_missing_dependency(monkeypatch):
    monkeypatch.setitem(sys.modules, "FlagEmbedding", None)  # 模拟未安装可选依赖
    provider = BgeM3EmbeddingProvider()
    assert provider.dimension == 1024
    with pytest.raises(RuntimeError, match="FlagEmbedding"):
        await provider.embed(["x"])
