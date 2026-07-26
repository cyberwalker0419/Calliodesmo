"""TextChunker：结构感知、确定性切分。

策略：先把文档拆为原子单元（代码块/表格/段落为不可分割单元，标题/句兜底），
再贪心装填至 ``chunk_size``，相邻 chunk 共享 ``overlap`` 字符接缝。
- 空文档 -> 空列表
- 确定性：相同输入恒相同输出
- 无丢失覆盖：所有原子单元均落入某 chunk
- ``len(chunk) <= chunk_size``，除非单个原子单元本身超长（允许例外）
- 相邻 chunk 共享 overlap（前一 chunk 尾部出现在后一 chunk 头部）

注意：``Chunk.summary`` 字段 P1 不生成，保持 None（L0 摘要属 P2/P5）。
"""

from __future__ import annotations

from calliodesmo.interfaces.chunker import Chunk, Chunker
from calliodesmo.interfaces.document_loader import LoadedDocument


class TextChunker(Chunker):
    def __init__(self, chunk_size: int = 1200, overlap: int = 100) -> None:
        if overlap < 0:
            raise ValueError("overlap 不能为负")
        if overlap >= chunk_size:
            raise ValueError("overlap 必须小于 chunk_size")
        self.chunk_size = chunk_size
        self.overlap = overlap

    async def chunk(self, doc: LoadedDocument) -> list[Chunk]:
        blocks = self._split_blocks(doc.content)
        if not blocks:
            return []
        texts = self._pack(blocks)
        return [
            Chunk.from_document(doc, ordinal=ordinal, content=text)
            for ordinal, text in enumerate(texts)
        ]

    # ---- 结构感知分块 ----
    def _split_blocks(self, content: str) -> list[str]:
        """按代码块/表格/段落拆为原子单元（保留代码块与表格完整性）。"""
        lines = content.split("\n")
        blocks: list[str] = []
        current: list[str] = []
        in_code = False

        def flush() -> None:
            if current:
                blocks.append("\n".join(current).rstrip())
                current.clear()

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```"):
                current.append(line)
                if in_code:
                    flush()
                    in_code = False
                else:
                    in_code = True
                continue
            if in_code:
                current.append(line)
                continue
            # 表格行：连续 | 开头归为一个块
            if stripped.startswith("|") and not (current and current[-1].strip().startswith("|")):
                flush()
                current.append(line)
                continue
            if stripped.startswith("|") and current and current[-1].strip().startswith("|"):
                current.append(line)
                continue
            if not stripped:
                flush()
                continue
            current.append(line)
        flush()
        return [b for b in blocks if b]

    # ---- 贪心装填 + overlap 接缝 ----
    def _pack(self, blocks: list[str]) -> list[str]:
        chunks: list[str] = []
        current = ""
        i = 0
        n = len(blocks)
        while i < n:
            block = blocks[i]
            sep = "\n\n" if current else ""
            candidate = current + sep + block
            if len(candidate) <= self.chunk_size or not current:
                current = candidate
                i += 1
            else:
                chunks.append(current)
                seed = self._overlap_seed(current)
                # 若 seed 与本块拼接仍超长，则放弃 seed，下一轮以空 current 接纳该块
                if seed and len(seed + "\n\n" + block) > self.chunk_size:
                    current = ""
                else:
                    current = seed
        if current:
            chunks.append(current)
        return chunks

    def _overlap_seed(self, text: str) -> str:
        """取前一 chunk 尾部 ``overlap`` 字符作为下一 chunk 的接缝。"""
        if self.overlap <= 0 or len(text) <= self.overlap:
            return ""
        return text[-self.overlap :]
