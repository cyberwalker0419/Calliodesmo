"""Task 2 测试：RRF 倒数秩融合。"""

from calliodesmo.interfaces.retriever import Candidate
from calliodesmo.retrieval.fusion import rrf


def _cand(chunk_id: str, score: float, rank: int, source: str = "x") -> Candidate:
    return Candidate(
        chunk_id=chunk_id,
        doc_id="d",
        content=f"content-{chunk_id}",
        score=score,
        rank=rank,
        source=source,
    )


class TestRRFSingleLane:
    def test_single_lane_degrades_to_rank_sort(self):
        """单路退化为按原秩排序。"""
        lane = {"vector": [_cand("c3", 0.9, 3), _cand("c1", 0.8, 1), _cand("c2", 0.7, 2)]}
        result = rrf(lane, top_k=3)
        assert [c.chunk_id for c in result] == ["c1", "c2", "c3"]
        # 融合分 = 1/(k+rank)
        assert result[0].score > result[1].score > result[2].score

    def test_top_k_truncation(self):
        lane = {"v": [_cand(f"c{i}", float(i), i) for i in range(1, 6)]}
        result = rrf(lane, top_k=2)
        assert len(result) == 2
        assert result[0].chunk_id == "c1"
        assert result[1].chunk_id == "c2"


class TestRRFDualLane:
    def test_same_chunk_merges_scores(self):
        """同一 chunk_id 跨路分数相加。"""
        lanes = {
            "vector": [_cand("c1", 0.9, 1)],
            "sparse": [_cand("c1", 5.0, 1)],
        }
        result = rrf(lanes, top_k=5)
        assert len(result) == 1
        # 融合分 = 1/(60+1) + 1/(60+1) = 2/61
        assert abs(result[0].score - round(2 / 61, 6)) < 0.001

    def test_union_not_intersection(self):
        """并集：稀疏命中稠密未命中（或反之）的 chunk 仍被保留。"""
        lanes = {
            "vector": [_cand("c1", 0.9, 1), _cand("c2", 0.8, 2)],
            "sparse": [_cand("c2", 5.0, 1), _cand("c3", 4.0, 2)],
        }
        result = rrf(lanes, top_k=10)
        ids = {c.chunk_id for c in result}
        assert ids == {"c1", "c2", "c3"}

    def test_dual_hit_ranks_higher(self):
        """双路命中的 chunk 融合分高于单路命中。"""
        lanes = {
            "vector": [_cand("c1", 0.9, 1), _cand("c2", 0.8, 2)],
            "sparse": [_cand("c2", 5.0, 1), _cand("c3", 4.0, 2)],
        }
        result = rrf(lanes, top_k=10)
        # c2 双路命中，应排第一
        assert result[0].chunk_id == "c2"

    def test_tie_breaks_by_chunk_id(self):
        """平局按 chunk_id 升序（确定性）。"""
        lanes = {
            "vector": [_cand("b", 0.9, 1)],
            "sparse": [_cand("a", 5.0, 1)],
        }
        result = rrf(lanes, top_k=5)
        # 两路 rank 都是 1，融合分相同 -> 按 chunk_id 排序
        assert result[0].chunk_id == "a"
        assert result[1].chunk_id == "b"
        assert abs(result[0].score - result[1].score) < 0.001

    def test_source_marks_all_lanes(self):
        """融合后 source 标注所有命中 lane。"""
        lanes = {
            "vector": [_cand("c1", 0.9, 1)],
            "sparse": [_cand("c1", 5.0, 1)],
        }
        result = rrf(lanes, top_k=5)
        assert result[0].source == "sparse+vector"

    def test_rank_reset_after_fusion(self):
        """融合后 rank 重置为 1..n。"""
        lanes = {"v": [_cand(f"c{i}", float(i), i) for i in range(1, 4)]}
        result = rrf(lanes, top_k=10)
        for i, c in enumerate(result, 1):
            assert c.rank == i


class TestRRFEmptyAndEdge:
    def test_empty_lanes(self):
        result = rrf({}, top_k=5)
        assert result == []

    def test_empty_candidate_list(self):
        result = rrf({"v": []}, top_k=5)
        assert result == []

    def test_custom_k(self):
        lanes = {"v": [_cand("c1", 1.0, 1)]}
        result = rrf(lanes, k=10, top_k=5)
        # score = 1/(10+1) = 0.090909...
        assert abs(result[0].score - round(1 / 11, 6)) < 0.001
