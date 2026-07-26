"""邮件加载器（extra: documents-email）：eml 经标准库 email / msg 经 extract-msg。"""

from __future__ import annotations

import email
from email import policy
from pathlib import Path

from calliodesmo.providers._base_loader import SingleFileLoader


class EmlLoader(SingleFileLoader):
    """标准库 email 解析 .eml，无重依赖。"""

    suffixes = (".eml",)
    dependency = ""
    extra = "documents-email"

    def _extract_text(self, path: Path) -> str:
        msg = email.message_from_binary_file(path.open("rb"), policy=policy.default)
        parts = []
        if msg.get("subject"):
            parts.append(f"Subject: {msg.get('subject')}")
        body = msg.get_body(preferencelist=("plain",))
        if body is not None:
            content = body.get_content()
            if content:
                parts.append(content.strip())
        attachments = [a.get_filename() for a in msg.iter_attachments() if a.get_filename()]
        if attachments:
            parts.append("Attachments: " + ", ".join(attachments))
        return "\n".join(parts)

    def _extra_metadata(self, path: Path) -> dict:
        msg = email.message_from_binary_file(path.open("rb"), policy=policy.default)
        return {
            "subject": msg.get("subject"),
            "from": msg.get("from"),
            "attachments": [a.get_filename() for a in msg.iter_attachments() if a.get_filename()],
        }


class MsgLoader(SingleFileLoader):
    """.msg 经 extract-msg。"""

    suffixes = (".msg",)
    dependency = "extract_msg"
    extra = "documents-email"

    def _extract_text(self, path: Path) -> str:
        extract_msg = self._require_dep()
        msg = extract_msg.Message(str(path))
        try:
            parts = []
            if msg.subject:
                parts.append(f"Subject: {msg.subject}")
            if msg.body:
                parts.append(msg.body.strip())
            return "\n".join(parts)
        finally:
            msg.close()
