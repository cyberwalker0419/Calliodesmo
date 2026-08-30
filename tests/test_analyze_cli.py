"""P6 Task 24：analyze CLI 测试（CliRunner + cli_db 唯一 schema + 离线桩配置）。

执行路径复用分析域既有组件：管理员（``settings.admin_username``，须先 ``db seed``）
提交 analyze job -> ``run_analysis_job`` + barrier 同步等待 -> 打印报告摘要；
材料全经 ``visible_to``（worker 自库重建提交者上下文二次把关），报告落库口径与
worker 一致（ok / partial 落 ``analysis_reports``，完全失败不落空报告）。

离线纪律：测试内以 env 覆盖 ``CALLIODESMO_LLM_MODEL=test/stub`` +
``CALLIODESMO_EMBEDDING_PROVIDER=hash`` 等（不依赖 ``.env`` 真模型）；
桩对生成质量零区分度，本文件只承诺命令契约 / 状态机 / 落库结构，不承诺分析质量。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from typer.testing import CliRunner

from calliodesmo.cli import app
from calliodesmo.config import get_settings

runner = CliRunner()


@pytest.fixture(autouse=True)
def _offline_stub_env(monkeypatch):
    """离线桩 settings：test/stub LLM + hash 嵌入（零网络，不读 .env 真模型）。"""
    monkeypatch.setenv("CALLIODESMO_LLM_MODEL", "test/stub")
    monkeypatch.setenv("CALLIODESMO_ANALYSIS_MODEL", "")
    monkeypatch.setenv("CALLIODESMO_LLM_API_KEY", "")
    monkeypatch.setenv("CALLIODESMO_LLM_API_BASE", "")
    monkeypatch.setenv("CALLIODESMO_EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("CALLIODESMO_RERANKER_PROVIDER", "none")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _fresh_stores():
    """每用例重置 AppStores 单例（内存向量库隔离，worker 经同一单例读材料）。"""
    from calliodesmo.api.deps import reset_app_stores

    reset_app_stores()
    yield
    reset_app_stores()


def _init_and_seed() -> None:
    """cli_db 已预建表；跑 db init（幂等）+ db seed（角色 + 管理员）。"""
    get_settings.cache_clear()
    try:
        assert runner.invoke(app, ["db", "init"]).exit_code == 0
        assert runner.invoke(app, ["db", "seed"]).exit_code == 0
    finally:
        get_settings.cache_clear()


def _admin_id(cli_inspect) -> uuid.UUID:
    """取种子管理员 id（db seed 经 CALLIODESMO_ADMIN_* 创建，cli_db 已设密码）。"""
    rows = cli_inspect("SELECT id FROM users WHERE username = 'admin'")
    assert rows, "db seed 应创建管理员 admin"
    raw = rows[0][0]
    return raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))


def _seed_material_chunks(owner_id: uuid.UUID, docs: dict[str, str]) -> None:
    """向 AppStores 单例内存向量库注入 admin 名下的可见材料块。"""
    from calliodesmo.api.deps import get_app_stores
    from calliodesmo.auth.models import ClearanceLevel, LibraryScope
    from calliodesmo.interfaces.vector_store import ChunkRecord

    dim = get_settings().embedding_dimension or 64
    vec = [0.0] * dim
    vec[0] = 1.0
    records = [
        ChunkRecord(
            chunk_id=f"{doc_id}#0",
            doc_id=doc_id,
            content=content,
            vector=list(vec),
            metadata={"title": doc_id},
            access_level=ClearanceLevel.INTERNAL,
            library_scope=LibraryScope.PERSONAL,
            owner_id=owner_id,
            project_id=None,
            team_id=None,
        )
        for doc_id, content in docs.items()
    ]
    asyncio.run(get_app_stores().vector_store.upsert_chunks(records))


def _invoke_analyze(args: list[str]):
    """跑 analyze 命令（前后清 settings 缓存，仿 test_ingest_cli 纪律）。"""
    get_settings.cache_clear()
    try:
        return runner.invoke(app, ["analyze", *args])
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 成功路径：提交 + 同步等待 + 报告落库 + 摘要打印（离线桩，不依赖 .env 真模型）
# ---------------------------------------------------------------------------


def test_analyze_summary_success_with_doc_ids_filter(cli_db, cli_inspect):
    """summary 成功路径：退出码 0 + 报告落库 + --doc-ids 成员筛选 + 审计双点。"""
    _init_and_seed()
    admin_id = _admin_id(cli_inspect)
    _seed_material_chunks(admin_id, {"alpha.md": "阿尔法材料。", "beta.md": "贝塔材料。"})

    result = _invoke_analyze(["--task-type", "summary", "--doc-ids", "alpha.md"])

    assert result.exit_code == 0, result.output
    assert "[报告已落库]" in result.output
    assert "type=summary" in result.output
    assert "status=ok" in result.output

    # job 终态 succeeded + 报告落库（--doc-ids 成员筛选：仅 alpha.md 入源文档）
    jobs = cli_inspect("SELECT status, result FROM jobs WHERE task_type = 'analyze'")
    assert len(jobs) == 1
    assert jobs[0][0] == "succeeded"
    reports = cli_inspect("SELECT task_type, status, source_doc_ids, payload FROM analysis_reports")
    assert len(reports) == 1
    assert reports[0][0] == "summary"
    assert reports[0][1] == "ok"
    assert reports[0][2] == ["alpha.md"]
    assert reports[0][3]["payload"]["summary"]  # SummaryReport 载荷落位

    # 审计：提交侧 analyze_submit（cli）+ worker 终态 analyze
    audits = cli_inspect("SELECT action, source FROM audit_logs ORDER BY action")
    assert ("analyze", "api") in audits
    assert ("analyze_submit", "cli") in audits


def test_analyze_qa_success(cli_db, cli_inspect):
    """qa 成功路径：退出码 0 + 报告落库（QAReport 载荷含非空 answer）。"""
    _init_and_seed()
    admin_id = _admin_id(cli_inspect)
    _seed_material_chunks(admin_id, {"alpha.md": "阿尔法材料。"})

    result = _invoke_analyze(["--task-type", "qa", "--question", "材料里有什么？"])

    assert result.exit_code == 0, result.output
    assert "type=qa" in result.output
    assert "status=ok" in result.output
    reports = cli_inspect("SELECT task_type, status, payload FROM analysis_reports")
    assert len(reports) == 1
    assert reports[0][0] == "qa"
    assert reports[0][1] == "ok"
    assert reports[0][2]["payload"]["answer"]  # QAReport.answer 非空


# ---------------------------------------------------------------------------
# 边界校验：未注册类型 / qa 缺 question / custom 缺 instruction（可读退出）
# ---------------------------------------------------------------------------


def test_analyze_unregistered_type(cli_db):
    """未注册分析类型 -> 退出码 1 + 可读错误。"""
    _init_and_seed()
    result = _invoke_analyze(["--task-type", "bogus"])
    assert result.exit_code == 1
    assert "未注册的分析类型" in result.output


def test_analyze_qa_requires_question(cli_db, cli_inspect):
    """qa 缺 --question -> 退出码 1，且不产生 job / 报告。"""
    _init_and_seed()
    result = _invoke_analyze(["--task-type", "qa"])
    assert result.exit_code == 1
    assert "question" in result.output
    assert cli_inspect("SELECT count(*) FROM jobs") == [(0,)]


def test_analyze_custom_requires_instruction(cli_db):
    """custom 缺 --instruction -> 退出码 1 + 可读错误。"""
    _init_and_seed()
    result = _invoke_analyze(["--task-type", "custom"])
    assert result.exit_code == 1
    assert "instruction" in result.output


# ---------------------------------------------------------------------------
# 运行期失败：无可见材料（非零退出 + 不落空报告）；doc_ids 含不可见文档（边界拦）
# ---------------------------------------------------------------------------


def test_analyze_no_visible_materials(cli_db, cli_inspect):
    """无可见材料 -> job failed -> 退出码 1 + 可读错误 + 不落空报告。"""
    _init_and_seed()
    result = _invoke_analyze(["--task-type", "summary"])
    assert result.exit_code == 1
    assert "无可见材料" in result.output

    jobs = cli_inspect("SELECT status, error FROM jobs WHERE task_type = 'analyze'")
    assert len(jobs) == 1
    assert jobs[0][0] == "failed"
    assert "无可见材料" in jobs[0][1]
    assert cli_inspect("SELECT count(*) FROM analysis_reports") == [(0,)]


def test_analyze_doc_ids_invisible_rejected(cli_db, cli_inspect):
    """--doc-ids 含不可见文档 -> 边界拦（退出码 1），不建 job。"""
    _init_and_seed()
    admin_id = _admin_id(cli_inspect)
    _seed_material_chunks(admin_id, {"alpha.md": "阿尔法材料。"})
    result = _invoke_analyze(["--task-type", "summary", "--doc-ids", "ghost.md"])
    assert result.exit_code == 1
    assert "不可见" in result.output
    assert cli_inspect("SELECT count(*) FROM jobs") == [(0,)]
