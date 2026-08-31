"""离线桩 LLMProvider：``test/*`` 模型路由到此处，零网络、零依赖。

用途：
- CLI 离线演示 / 冒烟测试 —— ``CALLIODESMO_LLM_MODEL=test/stub calliodesmo ingest ...``
- 让 P1 完整管线（Load->Extract->Cognify->Load->社区派生->档案卡）无需任何真实 LLM 即可跑通
- P6 分析任务离线闭环：9 类分析提示词经系统段 ``[ANALYSIS:<type>]`` 标记分发固定报告 JSON

实现：依据系统提示的标记 / 关键词分发（分析标记优先于关键词）：
- 分析标记（``[ANALYSIS:<type>]``，P6 Task 8）-> 对应报告模型的固定 JSON，9 类一次落齐
  （含注册表未交付的 custom，避免批次间回改桩；第二批 3 类已随 Task 21 注册）；
  未知分析标记**显式报错**，不静默回退——钉死「标记写错 → 静默回退抽取输出而测试不红」的坑。
  分析提示词可能含「摘要 / 抽取」等既有分发裸词（如 summary 模板），故标记分发必须
  先于关键词分支判定。
- 评估 judge 标记（``[ANALYSIS:judge]``，P6 Task 17）-> G-Eval rubric 四维固定评分
  （非分析类型，评估域标记；桩对生成质量零区分度，离线证据只承诺结构 / 契约）。
- 抽取（``知识图谱抽取引擎``）-> 返回固定 entities/relations/claims/covariates JSON
- 摘要（``文档摘要引擎``）-> 返回固定 {title, summary} JSON
- 其余未知调用（未携带分析标记）-> 回退为抽取格式（既有行为，避免管线中断）

返回的实体集合与分析桩输出均为**与输入无关**的示例数据（OpenAI/GPT-4、占位报告），
仅用于验证管线联通，不代表真实抽取 / 分析质量。桩分析输出不带证据：固定 JSON 的
quote 无法对应真实源文子串，带证据会使 ``analysis/evidence.py`` ``verify_evidence``
失败占比超阈降 partial，与 Task 10 离线端到端 status=ok 口径冲突；缺证据触发报告模型
的自动降置信校验器（``confidence`` 封顶 ``CONFIDENCE_CAP``），离线证据只承诺结构与契约。
真实抽取 / 分析请切换到 openai/deepseek/ollama 等后端。
"""

from __future__ import annotations

import json
import re
from typing import Any

from calliodesmo.interfaces.llm import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    ToolCall,
    ToolSpec,
)

# 抽取示例：固定实体/关系（演示用，与输入文本无关）
_EXTRACTION = {
    "entities": [
        {"name": "OpenAI", "type": "organization", "description": "AI 研究与部署公司"},
        {"name": "GPT-4", "type": "model", "description": "大规模语言模型"},
    ],
    "relations": [
        {
            "source": "OpenAI",
            "target": "GPT-4",
            "type": "developed",
            "description": "OpenAI 开发了 GPT-4",
        },
    ],
    "claims": [
        {"text": "GPT-4 由 OpenAI 开发", "entity_name": "GPT-4"},
    ],
    "covariates": [],
}

_SUMMARY = {"title": "示例文档社区", "summary": "由离线桩 LLM 生成的占位摘要（演示管线联通）。"}

#: P6 Task 8：9 类分析标记 → 固定报告 JSON（与输入无关，仅保结构契约）。
#: 键为 ``AnalysisType`` 取值（``analysis/specs.py`` 桩标记命名约定 ``[ANALYSIS:<值>]`` 派生源）；
#: 含注册表未交付的 custom（第一批 5 类 + 第二批 3 类已注册）——
#: 桩一次落齐，注册与交付分批由注册表控制，避免批次间回改桩。
#: 不带证据、显式置信见模块 docstring（缺证据 → 模型自动封顶降置信）。
#: 另含评估域 ``judge`` 键（P6 Task 17，非分析类型）：G-Eval 四维固定评分。
_ANALYSIS_PAYLOADS: dict[str, dict[str, Any]] = {
    "summary": {
        "summary": "离线桩占位摘要：由 StubLLM 固定输出，仅验证分析管线联通，不代表真实分析质量。",
        "key_points": ["离线桩占位要点一", "离线桩占位要点二"],
        "confidence": 1.0,
    },
    "key_information": {
        "items": [
            {"label": "时间", "value": "2026年8月29日（离线桩占位）", "confidence": 1.0},
            {"label": "当事方", "value": "示例组织（离线桩占位）", "confidence": 1.0},
        ],
    },
    "timeline": {
        "items": [
            {
                # 精确日期：granularity=exact + ISO 8601 归一化
                "date_raw": "2026年8月29日",
                "date_normalized": "2026-08-29",
                "granularity": "exact",
                "description": "离线桩占位事件（精确日期）",
                "confidence": 1.0,
            },
            {
                # 约略时间：按材料锚点换算（桩为固定示例），粒度落 approximate
                "date_raw": "上个月",
                "date_normalized": "2026-07",
                "granularity": "approximate",
                "description": "离线桩占位事件（约略时间）",
                "confidence": 1.0,
            },
            {
                # 模糊时间：落 relative 且归一化缺省，不得臆造精确日期
                "date_raw": "会后不久",
                "date_normalized": None,
                "granularity": "relative",
                "description": "离线桩占位事件（模糊时间不臆造精确日期）",
                "confidence": 1.0,
            },
        ],
    },
    "entity_recognition": {
        "items": [
            {
                "name": "示例组织",
                "type": "organization",
                "description": "离线桩占位实体（图谱数据组织而来，不重新抽取）",
                "confidence": 1.0,
            },
        ],
    },
    "relation_mapping": {
        "items": [
            {
                "head": "示例组织",
                "tail": "示例产品",
                "type": "developed",
                "description": "离线桩占位关系（图谱数据组织而来，不重新抽取）",
                "confidence": 1.0,
            },
        ],
    },
    "tasks": {
        "items": [
            {
                "action": "离线桩占位行动项",
                "owner_raw": "示例责任方",
                "deadline_raw": "2026年9月1日前",
                "confidence": 1.0,
            },
        ],
    },
    "concepts": {
        "items": [
            {
                "name": "示例概念",
                "definition": "离线桩占位定义（仅验证管线联通）",
                "related": ["相关概念一"],
                "confidence": 1.0,
            },
        ],
    },
    "qa": {
        "question": "离线桩占位问题",
        # 空候选约定（qa 模板）：无可引用材料时答案输出「无可引用证据」
        "answer": "无可引用证据（离线桩固定输出，仅验证管线联通）。",
        "citations": [],
        "confidence": 1.0,
    },
    "custom": {
        "fields": {"placeholder_field": "离线桩占位值（用户 schema 驱动的开放字段示例）"},
        "confidence": 1.0,
    },
    # G-Eval judge 固定评分（P6 Task 17，评估域标记而非分析类型）：四维均 3 的中性分。
    # 桩对生成质量零区分度——固定分仅锁 judge 契约（可解析、1–5 内），离线证据只承诺
    # 结构 / 契约；质量证据由 scripts/eval_p6.py --real 承担（锚点 2026-W45）。
    "judge": {"completeness": 3, "evidence_support": 3, "no_fabrication": 3, "structure": 3},
}

#: 分析标记形状：``[ANALYSIS:<type>]``（系统段，模板首行标记，见 config/analysis_prompts/）
_ANALYSIS_MARKER_RE = re.compile(r"\[ANALYSIS:([^\]]*)\]")

#: P7 T4：agent 脚本标记形状 ``[AGENT:<script>]``（系统段），分发脚本化 tool_calls 序列——
#: 离线桩驱动工具调用循环的地基（全部 agent 离线测试依赖；桩对工具选择恰当性零区分度，
#: 质量证据由 scripts/eval_agent.py --real 承担，锚点 2026-W45）。
_AGENT_MARKER_RE = re.compile(r"\[AGENT:([^\]]*)\]")

#: 脚本化轨迹：steps 为逐回合 tool_calls 清单（按 messages 中已有 assistant tool_calls
#: 轮数取步序，纯函数无状态）；steps 耗尽后回 final 收尾。三基线场景：
#: 两步检索 / 越权工具探测（脚本化调用未授权工具，注册表拒派）/ 证据不足直答。
_AGENT_PAYLOADS: dict[str, dict[str, Any]] = {
    "two_step_search": {
        "steps": [
            [
                {
                    "name": "search_knowledge",
                    "arguments": {"question": "GPT-4 由谁开发", "mode": "native_rag"},
                }
            ],
        ],
        "final": "根据检索结果：GPT-4 由 OpenAI 开发（离线桩固定轨迹）。",
    },
    "forbidden_probe": {
        "steps": [
            [
                {
                    "name": "run_analysis",
                    "arguments": {"task_type": "summary", "subject": "越权探测"},
                }
            ],
        ],
        "final": "探测结束（离线桩固定轨迹）。",
    },
    "insufficient_direct": {
        "steps": [],
        "final": "证据不足，无法回答（离线桩直答，不调用工具）。",
    },
    "multi_tool": {
        # 单回合双工具（工具集匹配指标场景）
        "steps": [
            [
                {
                    "name": "search_knowledge",
                    "arguments": {"question": "GPT-4 由谁开发", "mode": "native_rag"},
                },
                {"name": "graph_neighbors", "arguments": {"name": "OpenAI", "hops": 1}},
            ],
        ],
        "final": "检索 + 图谱联合结论：GPT-4 由 OpenAI 开发（离线桩固定轨迹）。",
    },
    "ghost_probe": {
        # 不存在工具探测：注册表与越权同一消息（不泄漏存在性）
        "steps": [[{"name": "ghost_tool", "arguments": {}}]],
        "final": "探测结束（离线桩固定轨迹）。",
    },
    "injection_probe": {
        # 语料注入探针：工具结果内嵌诱导指令（runner 注入），桩定义上不被诱导——
        # 零工具调用直答；零容忍断言在指标层（工具未被诱导），--real 批次才具区分度。
        "steps": [],
        "final": "工具结果含注入指令亦不执行（离线桩不被内容诱导）。",
    },
    "loop_forever": {
        # 预算帽场景：脚本化持续发工具调用（8 轮），验证超限强制收敛（T10）
        "steps": [
            [{"name": "search_knowledge", "arguments": {"question": "循环", "mode": "native_rag"}}]
        ]
        * 8,
        "final": "不应到达（预算帽先触发强制收敛）。",
    },
}


class StubLLMProvider(LLMProvider):
    """离线桩 LLM：按系统提示的 ``[ANALYSIS:<type>]`` 标记与关键词分发固定响应。"""

    def __init__(self, model: str = "test/stub") -> None:
        self.model = model

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        tools: list[ToolSpec] | None = None,
    ) -> LLMResponse:
        system = next((m.content for m in messages if m.role == "system"), "")
        marker = _ANALYSIS_MARKER_RE.search(system)
        agent_marker = _AGENT_MARKER_RE.search(system)
        if marker is not None:
            # 分析标记分发优先：分析提示词含「摘要 / 抽取」等裸词，须先于关键词分支
            payload = self._analysis_payload(marker.group(1))
            return LLMResponse(
                content=json.dumps(payload, ensure_ascii=False),
                model=self.model,
                usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            )
        if agent_marker is not None:
            # P7 T4：agent 脚本化 tool_calls 序列（先于关键词分支；未知标记显式报错）
            return self._agent_response(agent_marker.group(1), messages)
        if "知识图谱抽取引擎" in system or ("抽取" in system and "entities" in system):
            payload = _EXTRACTION
        elif "文档摘要引擎" in system or "摘要" in system:
            payload = _SUMMARY
        else:
            # 未知调用（非分析）：回退为抽取格式，避免管线中断（既有行为保留）
            payload = _EXTRACTION
        return LLMResponse(
            content=json.dumps(payload, ensure_ascii=False),
            model=self.model,
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )

    def _agent_response(self, script: str, messages: list[LLMMessage]) -> LLMResponse:
        """按 ``[AGENT:<script>]`` 取脚本化轨迹；步序 = 已有 assistant tool_calls 轮数（无状态）。

        钉死的坑同分析标记：未知脚本显式 ValueError，不静默回退——脚本名拼错若静默
        走旧分发，agent 离线轨迹测试全失真而不红。
        """
        payload = _AGENT_PAYLOADS.get(script)
        if payload is None:
            supported = ", ".join(sorted(_AGENT_PAYLOADS))
            raise ValueError(
                f"StubLLM 收到未知 agent 标记 [AGENT:{script}]，支持的脚本: {supported}"
            )
        steps: list[list[dict[str, Any]]] = payload["steps"]
        done_rounds = sum(1 for m in messages if m.role == "assistant" and m.tool_calls)
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        if done_rounds < len(steps):
            calls = tuple(
                ToolCall(
                    id=f"call-{script}-{done_rounds}-{i}",
                    name=step["name"],
                    arguments=dict(step["arguments"]),
                )
                for i, step in enumerate(steps[done_rounds])
            )
            return LLMResponse(content="", model=self.model, usage=usage, tool_calls=calls)
        return LLMResponse(content=payload["final"], model=self.model, usage=usage)

    @staticmethod
    def _analysis_payload(marker_type: str) -> dict[str, Any]:
        """按分析标记取固定报告 JSON；未知标记显式报错，不静默回退抽取输出。

        钉死的坑：标记写错（类型名拼写 / 大小写错误）若静默回退抽取 JSON，
        离线契约测试与评估将全失真而不红，故此处显式抛错。
        """
        payload = _ANALYSIS_PAYLOADS.get(marker_type)
        if payload is None:
            supported = ", ".join(sorted(_ANALYSIS_PAYLOADS))
            raise ValueError(
                f"StubLLM 收到未知分析标记 [ANALYSIS:{marker_type}]，支持的类型: {supported}"
            )
        return payload
