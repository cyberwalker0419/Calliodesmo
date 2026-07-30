"""P3 Task 1 Step 8：serve --seed-demo 演示数据注入 + 落盘缓存。"""

import uuid
from pathlib import Path

import calliodesmo.models  # noqa: F401
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, Permission
from calliodesmo.config import Settings

DEMO_MD = """# 演示文档

OpenAI 开发了 GPT-4。GPT-4 是大规模语言模型。
"""


def _test_settings(tmp_path: Path) -> Settings:
    return Settings(
        llm_model="test/stub",
        embedding_provider="hash",
        embedding_dimension=64,
        extraction_template_file="config/extraction_templates.example.yaml",
    )


def _admin_ctx(team_id: uuid.UUID) -> AccessContext:
    return AccessContext(
        user_id=uuid.uuid4(),
        username="admin",
        clearance=ClearanceLevel.SECRET,
        permissions=frozenset(set(Permission)),
        team_ids=frozenset({team_id}),
    )


def _write_demo_tree(base: Path) -> None:
    (base / "public__brief.md").write_text(DEMO_MD, encoding="utf-8")
    (base / "internal__notes.md").write_text(DEMO_MD, encoding="utf-8")
    (base / "confidential__assessment.md").write_text(DEMO_MD, encoding="utf-8")


async def test_seed_demo_populates_stores(tmp_path):
    from calliodesmo.api.deps import AppStores
    from calliodesmo.ecl.demo_seed import seed_demo_stores

    demo_dir = tmp_path / "demo"
    demo_dir.mkdir()
    _write_demo_tree(demo_dir)
    cache = tmp_path / "seed-cache.json"

    stores = AppStores()
    team_id = uuid.uuid4()
    report = await seed_demo_stores(
        stores,
        _test_settings(tmp_path),
        demo_dir=demo_dir,
        cache_file=cache,
        access=_admin_ctx(team_id),
    )
    assert report.source == "pipeline"
    assert report.documents == 3
    assert len(stores.profile_card_store) > 0
    assert len(stores.graph_store) > 0
    assert len(stores.community_store) > 0
    assert len(stores.vector_store) > 0
    assert cache.exists()

    # clearance 梯度：三档数据齐全
    levels = {c.access_level for c in stores.community_store._records.values()}
    assert {ClearanceLevel.PUBLIC, ClearanceLevel.INTERNAL, ClearanceLevel.CONFIDENTIAL} <= levels
    # 库范围为团队库（demo 团队可见）
    scopes = {c.library_scope for c in stores.community_store._records.values()}
    assert scopes.pop().value == "team"


async def test_seed_demo_cache_hit_skips_pipeline(tmp_path):
    from calliodesmo.api.deps import AppStores
    from calliodesmo.ecl.demo_seed import seed_demo_stores

    demo_dir = tmp_path / "demo"
    demo_dir.mkdir()
    _write_demo_tree(demo_dir)
    cache = tmp_path / "seed-cache.json"
    settings = _test_settings(tmp_path)
    team_id = uuid.uuid4()

    first = AppStores()
    report1 = await seed_demo_stores(
        first, settings, demo_dir=demo_dir, cache_file=cache, access=_admin_ctx(team_id)
    )
    assert report1.source == "pipeline"

    # 二次运行：删掉 demo 目录，仅靠缓存也应完整恢复（证明没跑管线）
    for p in demo_dir.iterdir():
        p.unlink()
    second = AppStores()
    report2 = await seed_demo_stores(
        second, settings, demo_dir=demo_dir, cache_file=cache, access=_admin_ctx(team_id)
    )
    assert report2.source == "cache"
    assert len(second.profile_card_store) == len(first.profile_card_store)
    assert len(second.graph_store) == len(first.graph_store)
    assert len(second.community_store) == len(first.community_store)
    assert len(second.vector_store) == len(first.vector_store)
    # 稀疏索引随缓存重建
    assert len(second.sparse_index._docs) == len(first.sparse_index._docs)


async def test_seed_demo_visible_to_team_member(tmp_path):
    """seed 后 /library/profile-cards 对 demo 团队成员非空（UI 演示不面对空库）。"""
    from calliodesmo.api.deps import AppStores
    from calliodesmo.ecl.demo_seed import seed_demo_stores

    demo_dir = tmp_path / "demo"
    demo_dir.mkdir()
    _write_demo_tree(demo_dir)
    stores = AppStores()
    team_id = uuid.uuid4()
    await seed_demo_stores(
        stores,
        _test_settings(tmp_path),
        demo_dir=demo_dir,
        cache_file=tmp_path / "cache.json",
        access=_admin_ctx(team_id),
    )
    member_ctx = AccessContext(
        user_id=uuid.uuid4(),
        username="member",
        clearance=ClearanceLevel.INTERNAL,
        permissions=frozenset({Permission.QUERY}),
        team_ids=frozenset({team_id}),
    )
    cards = await stores.profile_card_store.list(access=member_ctx)
    assert cards  # INTERNAL 成员可见 public+internal
    levels = {c.access_level for c in cards}
    assert ClearanceLevel.CONFIDENTIAL not in levels


def test_serve_seed_demo_flag(tmp_path, monkeypatch, cli_db):
    """serve --seed-demo：uvicorn 启动前完成 seed（mock uvicorn 验证顺序）。"""
    import sys
    from types import SimpleNamespace

    from typer.testing import CliRunner

    from calliodesmo.cli import app
    from calliodesmo.config import get_settings

    runner = CliRunner()
    demo_dir = tmp_path / "demo"
    demo_dir.mkdir()
    _write_demo_tree(demo_dir)

    # cli_db 已 patch create_async_engine 绑定唯一 schema + 设 ADMIN_PASSWORD
    monkeypatch.setenv("CALLIODESMO_LLM_MODEL", "test/stub")
    monkeypatch.setenv("CALLIODESMO_EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("CALLIODESMO_EMBEDDING_DIMENSION", "64")
    monkeypatch.setenv("CALLIODESMO_DEMO_DIR", str(demo_dir))
    monkeypatch.setenv("CALLIODESMO_DEMO_CACHE_FILE", str(tmp_path / "cache.json"))
    get_settings.cache_clear()

    calls: dict = {}

    def fake_run(*args, **kwargs):
        calls["ran"] = True
        # uvicorn 启动时 stores 应已注入
        from calliodesmo.api.deps import get_app_stores

        calls["cards"] = len(get_app_stores().profile_card_store)

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))
    try:
        assert runner.invoke(app, ["db", "init"]).exit_code == 0
        assert runner.invoke(app, ["db", "seed"]).exit_code == 0
        result = runner.invoke(app, ["serve", "--seed-demo"])
        assert result.exit_code == 0, result.output
        assert calls["ran"] is True
        assert calls["cards"] > 0
    finally:
        get_settings.cache_clear()
        from calliodesmo.api.deps import reset_app_stores

        reset_app_stores()
