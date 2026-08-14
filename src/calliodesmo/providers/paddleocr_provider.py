"""OCR 专职实现：PaddleOCR-VL 1.6（专用文档 OCR 引擎，逐字保真，可切换）。

两种部署（``ocr_remote`` 配置切换）：
- **local**：本机装 ``paddleocr[doc-parser]>=3.6``（重型 extra ``documents-ocr``），懒加载，
  缺依赖抛友好错误提示安装；``vl_rec_backend`` 指向本地/远端的 llama.cpp / vLLM 编排服务。
- **remote**：仅向 ``ocr_server_url``（PaddleOCR 编排 HTTP 服务）发请求，本机零重型依赖
  （对应当前项目 Ollama/llama.cpp 远程免 key 思维）。

default 保持确定性、零重依赖、离线可测（test/* 走 ``StubOcrProvider``）。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from calliodesmo.interfaces.ocr import OcrProvider, OcrResult
from calliodesmo.providers._base_loader import import_optional

_EXTRA = "documents-ocr"
_DEP = "paddleocr"


def _save_tmp_image(image: bytes, mime: str) -> tuple[str, str]:
    """图片字节 -> 临时文件（PaddleOCR predict 接收路径）。按 mime 推断后缀；返回 (路径, 后缀)。"""
    suffix = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
        "image/tiff": ".tiff",
    }.get(mime, ".png")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(image)
        tmp.flush()
        return tmp.name, suffix
    finally:
        tmp.close()


def _extract_text_from_result(res) -> str:
    """从 PaddleOCR-VL predict 结果解析逐字转录文本。

    Result 支持 ``save_to_json()`` 返回 dict（含 rec_texts 等字段）；这里取 JSON 后优先
    ``rec_texts``（识别文本列表）拼成多行，其次 ``text``/``markdown`` 字段回退。
    """
    try:
        data = res.save_to_json()
    except Exception:
        data = None
    if isinstance(data, dict):
        rec = data.get("rec_texts")
        if isinstance(rec, list) and rec:
            return "\n".join(str(t) for t in rec)
        for key in ("text", "markdown", "res_str"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val
    return ""


class PaddleOcrProvider(OcrProvider):
    """PaddleOCR-VL 专用 OCR。local=本机 paddleocr；remote=HTTP 编排（零重型依赖）。"""

    def __init__(
        self,
        *,
        pipeline_version: str = "v1.6",
        vl_backend: str = "llama-cpp-server",
        server_url: str | None = None,
        prompt: str | None = None,
        remote: bool = False,
        model: str = "PaddleOCR-VL-1.6",
    ) -> None:
        self.pipeline_version = pipeline_version
        self.vl_backend = vl_backend
        self.server_url = server_url
        self.prompt = prompt
        self.remote = remote
        self.model = model
        self._pipeline = None  # local 模式懒加载产物

    async def extract_text(
        self,
        image: bytes,
        *,
        mime: str,
        prompt: str | None = None,
    ) -> OcrResult:
        effective_prompt = prompt or self.prompt or "OCR:"
        if self.remote:
            text = await self._extract_remote(image, mime)
        else:
            text = self._extract_local(image, mime, effective_prompt)
        return OcrResult(text=text, model=self.model, metadata={"remote": self.remote})

    # ---- local：本机 paddleocr ----

    def _get_pipeline(self):
        """懒加载 PaddleOCRVL 编排管线；缺依赖抛出安装引导。"""
        if self._pipeline is not None:
            return self._pipeline
        # import_optional 抛 RuntimeError 引导 uv sync --extra documents-ocr
        import_optional(_DEP, _EXTRA)
        from paddleocr import PaddleOCRVL  # 延迟导入重型依赖

        kwargs: dict = {
            "pipeline_version": self.pipeline_version,
            "vl_rec_backend": self.vl_backend,
        }
        # 提示词默认经引擎侧 "OCR:"（PaddleOCR-VL 识别默认），不做非文档化参数强传；
        # 自定义提示词（Table:/Formula:/Chart: 等）属真机验证边界，实施时按安装版本核对签名。
        if self.server_url:
            kwargs["vl_rec_server_url"] = self.server_url
        self._pipeline = PaddleOCRVL(**kwargs)
        return self._pipeline

    def _extract_local(self, image: bytes, mime: str, prompt: str) -> str:
        pipeline = self._get_pipeline()
        tmp_path, _ = _save_tmp_image(image, mime)
        try:
            output = pipeline.predict(tmp_path)
            texts: list[str] = []
            for res in output or []:
                t = _extract_text_from_result(res)
                if t.strip():
                    texts.append(t)
            return "\n".join(texts)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    # ---- remote：HTTP 编排（本机零重型依赖） ----

    async def _extract_remote(self, image: bytes, mime: str) -> str:
        if not self.server_url:
            raise RuntimeError(
                "OCR remote 模式缺编排地址：设 CALLIODESMO_OCR_SERVER_URL"
                "（PaddleOCR llama-server / vLLM 的 HTTP 服务地址）"
            )
        import httpx  # 延迟导入（项目基础依赖组已含）

        tmp_path, suffix = _save_tmp_image(image, mime)
        payload: dict
        try:
            # 文件字节在 async 体外读好（ASYNC230 规避），post 时仅带字节内容
            with open(tmp_path, "rb") as f:  # noqa: ASYNC230 - 一次性同步读，非阻塞式副作用
                img_bytes = f.read()
            async with httpx.AsyncClient(timeout=120) as client:
                files = {"file": (f"doc{suffix}", img_bytes, mime)}
                data = {"text_input": "OCR:"}
                resp = await client.post(self.server_url, files=files, data=data)
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"OCR remote 编排失败：HTTP {exc.response.status_code} -> "
                f"{exc.response.text}"
            ) from exc
        finally:
            Path(tmp_path).unlink(missing_ok=True)  # noqa: ASYNC240 - 见 _extract_local
        # PaddleOCR 编排服务的响应多为 {"results":[{...}]}，逐条取 rec_texts/text 拼合；
        # 形态因部署版本而异，稳妥遍历 dict 中的文本字段回退。
        texts: list[str] = []

        def _collect(node):
            if isinstance(node, dict):
                rec = node.get("rec_texts")
                if isinstance(rec, list):
                    texts.extend(str(t) for t in rec if str(t).strip())
                for key in ("text", "markdown"):
                    val = node.get(key)
                    if isinstance(val, str) and val.strip():
                        texts.append(val)
                for v in node.values():
                    _collect(v)
            elif isinstance(node, list):
                for v in node:
                    _collect(v)

        _collect(payload)
        return "\n".join(texts)
