"""LoaderRegistry：按后缀分发 DocumentLoader，未注册时提示安装对应 extra。

基础格式默认注册；重依赖格式懒注册（用到且依赖在时注册）。新增格式只需
``register(suffix, loader)`` 一行，不动核心。
"""

from __future__ import annotations

from pathlib import Path

from calliodesmo.interfaces.document_loader import DocumentLoader, LoadedDocument
from calliodesmo.interfaces.ocr import OcrProvider
from calliodesmo.interfaces.vision import VisionProvider
from calliodesmo.providers._base_loader import dependency_available
from calliodesmo.providers.markup_loader import OrgLoader, RstLoader, TexLoader
from calliodesmo.providers.structured_loader import (
    CsvLoader,
    HtmlLoader,
    JsonLoader,
    XmlLoader,
    YamlLoader,
)
from calliodesmo.providers.text_loader import TextDocumentLoader

#: 已知重依赖后缀 -> extra 分组（resolve 未注册时给出安装提示）
SUFFIX_EXTRA_HINT: dict[str, str] = {
    ".pdf": "documents-pdf",
    ".docx": "documents-office",
    ".xlsx": "documents-office",
    ".pptx": "documents-office",
    ".odt": "documents-opendocument",
    ".ods": "documents-opendocument",
    ".odp": "documents-opendocument",
    ".rtf": "documents-rich",
    ".epub": "documents-rich",
    ".mobi": "documents-rich",
    ".eml": "documents-email",
    ".msg": "documents-email",
    ".ipynb": "documents-notebooks",
}


class LoaderRegistry(DocumentLoader):
    """按后缀分发的复合加载器；既是注册表也是 DocumentLoader。"""

    def __init__(self) -> None:
        self._loaders: dict[str, DocumentLoader] = {}

    def register(self, suffix: str, loader: DocumentLoader) -> None:
        self._loaders[suffix.lower()] = loader

    def resolve(self, source: str | Path) -> DocumentLoader:
        suffix = Path(source).suffix.lower()
        loader = self._loaders.get(suffix)
        if loader is not None:
            return loader
        extra = SUFFIX_EXTRA_HINT.get(suffix)
        if extra:
            raise ValueError(
                f"未注册的文件类型: {suffix}（安装对应 extra 后可用：uv sync --extra {extra}）"
            )
        raise ValueError(f"未注册的文件类型: {suffix}")

    @property
    def registered_suffixes(self) -> set[str]:
        return set(self._loaders)

    async def load(self, source: str | Path) -> list[LoadedDocument]:
        source = Path(source)
        if not source.exists():
            raise FileNotFoundError(f"文档源不存在: {source}")
        if source.is_file():
            return await self.resolve(source).load(source)
        # 目录：递归遍历，按后缀分发
        docs: list[LoadedDocument] = []
        for p in sorted(source.rglob("*")):
            if p.is_file() and p.suffix.lower() in self._loaders:
                docs.extend(await self._loaders[p.suffix.lower()].load(p))
        return docs


def _register_heavy(registry: LoaderRegistry) -> None:
    """懒注册重依赖格式：依赖可导入才注册。"""
    # 延迟导入避免在未安装 extra 时拖累基础导入
    from calliodesmo.providers.email_loader import EmlLoader, MsgLoader
    from calliodesmo.providers.notebook_loader import NotebookLoader
    from calliodesmo.providers.office_loader import DocxLoader, PptxLoader, XlsxLoader
    from calliodesmo.providers.opendocument_loader import (
        OdpLoader,
        OdsLoader,
        OdtLoader,
    )
    from calliodesmo.providers.pdf_loader import PdfLoader
    from calliodesmo.providers.rich_loader import EpubLoader, RtfLoader

    heavy = [
        (PdfLoader, [".pdf"]),
        (DocxLoader, [".docx"]),
        (XlsxLoader, [".xlsx"]),
        (PptxLoader, [".pptx"]),
        (OdtLoader, [".odt"]),
        (OdsLoader, [".ods"]),
        (OdpLoader, [".odp"]),
        (RtfLoader, [".rtf"]),
        (EpubLoader, [".epub"]),
        (EmlLoader, [".eml"]),
        (MsgLoader, [".msg"]),
        (NotebookLoader, [".ipynb"]),
    ]
    for loader_cls, suffixes in heavy:
        if loader_cls.dependency and not dependency_available(loader_cls.dependency):
            continue
        loader = loader_cls()
        for s in suffixes:
            registry.register(s, loader)


#: 图片后缀（经 OCR/识图模型加载，需 provider 注册时才挂载）
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp")


def default_registry(
    ocr: OcrProvider | None = None,
    vision: VisionProvider | None = None,
    vision_prompt: str | None = None,
) -> LoaderRegistry:
    """默认注册表：内置格式全注册，重依赖格式懒注册。

    传了 ``ocr`` / ``vision`` provider 才注册图片后缀（ImageLoader）；
    两者皆 None 时不注册（离线兼容旧调用，图片文档无法加载并给出引导）。
    """
    reg = LoaderRegistry()
    text = TextDocumentLoader()
    for s in (".txt", ".log", ".md", ".markdown"):
        reg.register(s, text)
    reg.register(".csv", CsvLoader(delimiter=","))
    reg.register(".tsv", CsvLoader(delimiter="\t"))
    reg.register(".json", JsonLoader())
    for s in (".yaml", ".yml"):
        reg.register(s, YamlLoader())
    reg.register(".xml", XmlLoader())
    for s in (".html", ".htm"):
        reg.register(s, HtmlLoader())
    reg.register(".rst", RstLoader())
    reg.register(".org", OrgLoader())
    reg.register(".tex", TexLoader())
    _register_heavy(reg)
    if ocr is not None or vision is not None:
        from calliodesmo.providers.image_loader import ImageLoader

        img = ImageLoader(ocr=ocr, vision=vision, vision_prompt=vision_prompt)
        for s in IMAGE_SUFFIXES:
            reg.register(s, img)
    return reg
