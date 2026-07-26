"""标记语言加载器：rst/org/tex（轻解析取纯文本，内置）。"""

from __future__ import annotations

import re
from pathlib import Path

from calliodesmo.providers._base_loader import SingleFileLoader


class RstLoader(SingleFileLoader):
    """reStructuredText：剥离指令/角色标记，保留正文。"""

    suffixes = (".rst",)

    def _extract_text(self, path: Path) -> str:
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"\.\. [^\n]*::[^\n]*\n", "", text)  # 指令行
        text = re.sub(r":[a-z]+:`([^`]+)`", r"\1", text)  # :role:`text`
        text = re.sub(r"``([^`]+)``", r"\1", text)  # ``literal``
        return text.strip()


class OrgLoader(SingleFileLoader):
    """Org-mode：剥离 drawer/属性/标记，保留正文。"""

    suffixes = (".org",)

    def _extract_text(self, path: Path) -> str:
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"^\s*:\w+:\s*$.*?(?=^\s*:\w+:\s*$|\Z)", "", text, flags=re.M | re.S)
        text = re.sub(r"^\s*#\+[A-Z_]+:.*$", "", text, flags=re.M)
        text = re.sub(r"\[\[([^\]]+)\]\[([^\]]+)\]\]", r"\2", text)  # 链接
        return text.strip()


class TexLoader(SingleFileLoader):
    """LaTeX：剥离命令/环境标记，保留正文。"""

    suffixes = (".tex",)

    def _extract_text(self, path: Path) -> str:
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"\\begin\{[^}]*\}", "", text)
        text = re.sub(r"\\end\{[^}]*\}", "", text)
        text = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?\{([^}]*)\}", r"\2", text)
        text = re.sub(r"\\[a-zA-Z]+\*?", "", text)
        text = re.sub(r"%[^\n]*", "", text)
        text = re.sub(r"\{([^}]*)\}", r"\1", text)
        return text.strip()
