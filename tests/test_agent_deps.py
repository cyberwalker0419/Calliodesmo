"""P7 T2：agent extra 钉版验证 + 懒导入守卫（装齐后 import 成功 + 版本断言；缺依赖友好报错）。"""

from importlib.metadata import version

import pytest


def _ver(s: str) -> tuple[int, ...]:
    return tuple(int(x) for x in s.split(".")[:3])


def test_agent_extra_installed_imports():
    """extra 装齐：langgraph / AsyncPostgresSaver / psycopg[binary] import 成功 + 版本断言。"""
    import langgraph  # noqa: F401
    import psycopg  # noqa: F401
    import psycopg_pool  # noqa: F401
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # noqa: F401

    # 钉版区间断言（与 pyproject extra agent 一致）
    assert (1, 2) <= _ver(version("langgraph"))[:2] < (2, 0)
    assert (3, 1, 1) <= _ver(version("langgraph-checkpoint-postgres")) < (4, 0)
    assert (3, 2) <= _ver(version("psycopg"))[:2] < (3, 4)
    # Windows wheel 路径：psycopg-binary 与 psycopg 同版（[binary] extra 同版锁定）
    assert version("psycopg-binary") == version("psycopg")


def test_require_langgraph_missing_dep_friendly_error(monkeypatch):
    """缺依赖：RuntimeError 友好报错含安装指令（不裸抛 ImportError）。"""
    import sys

    from calliodesmo.agent.extras import require_langgraph

    monkeypatch.setitem(sys.modules, "langgraph", None)  # import 即 ImportError
    with pytest.raises(RuntimeError, match="uv sync --extra agent"):
        require_langgraph()


def test_require_pg_checkpointer_missing_dep_friendly_error(monkeypatch):
    # 模拟 checkpoint postgres 子包缺失
    import sys

    from calliodesmo.agent.extras import require_pg_checkpointer

    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.postgres.aio", None)
    with pytest.raises(RuntimeError, match="uv sync --extra agent"):
        require_pg_checkpointer()


def test_require_langgraph_installed():
    """装齐后守卫返回模块本体（懒导入不旁落所有权）。"""
    import langgraph

    from calliodesmo.agent.extras import require_langgraph, require_pg_checkpointer

    assert require_langgraph() is langgraph
    assert require_pg_checkpointer().__name__ == "AsyncPostgresSaver"
