"""单文件加载器基类与可选依赖懒加载助手。

默认 ``load``（async）仅做编排，阻塞式文件 I/O 全部下沉到同步 ``_load_sync``，
避免在 async 函数中直接调用 pathlib.Path 方法（ASYNC240）。产出多文档的格式
（如 PDF 按页、Excel 按 sheet）重写 ``_load_sync`` 即可。

重依赖格式经 ``import_optional`` 懒导入，缺依赖时抛清晰错误并提示安装对应 extra。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from calliodesmo.interfaces.document_loader import DocumentLoader, LoadedDocument


def import_optional(dep_name: str, extra: str):
    """懒导入可选依赖；缺失时抛 RuntimeError 提示安装 extra。"""
    try:
        return __import__(dep_name)
    except ImportError as exc:  # pragma: no cover - 由各 loader 的测试覆盖
        raise RuntimeError(f"解析该格式需安装 {dep_name}：uv sync --extra {extra}") from exc


def dependency_available(dep_name: str) -> bool:
    """检查可选依赖是否可导入（注册表据此决定是否注册重依赖 loader）。"""
    if not dep_name:
        return True
    return importlib.util.find_spec(dep_name) is not None


class SingleFileLoader(DocumentLoader):
    """单文件加载器基类：async load 编排 + 同步 _load_sync 做 I/O。"""

    suffixes: tuple[str, ...] = ()
    dependency: str = ""
    extra: str = ""

    async def load(self, source: str | Path) -> list[LoadedDocument]:
        return self._load_sync(Path(source))

    def _load_sync(self, path: Path) -> list[LoadedDocument]:
        if not path.exists():
            raise FileNotFoundError(f"文档源不存在: {path}")
        if path.is_dir():
            raise ValueError(f"单文件加载器不支持目录，请经 LoaderRegistry 分发: {path}")
        content = self._extract_text(path)
        return [
            LoadedDocument(
                doc_id=path.name,
                content=content,
                metadata={
                    "source_path": str(path),
                    "suffix": path.suffix.lower(),
                    "size_bytes": path.stat().st_size,
                    **self._extra_metadata(path),
                },
            )
        ]

    def _extract_text(self, path: Path) -> str:
        raise NotImplementedError

    def _extra_metadata(self, path: Path) -> dict:
        return {}

    def _require_dep(self):
        """子类在 _load_sync 中调用以懒导入重依赖，缺时抛友好错误。"""
        if self.dependency:
            return import_optional(self.dependency, self.extra)
        return None
