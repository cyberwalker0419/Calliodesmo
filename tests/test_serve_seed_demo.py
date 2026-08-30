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

    # 二次运行：语料与 team 均未漂移，缓存命中、跳过管线（source 仅在缓存路径置 "cache"）
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


def _write_nested_demo_tree(base: Path) -> None:
    """嵌套语料：顶层一篇 + 子目录两篇（P7 T1：rglob 递归发现）。"""
    (base / "public__brief.md").write_text(DEMO_MD, encoding="utf-8")
    nested = base / "01"
    nested.mkdir()
    (nested / "internal__notes.md").write_text(DEMO_MD, encoding="utf-8")
    (nested / "confidential__assessment.md").write_text(DEMO_MD, encoding="utf-8")


async def test_seed_demo_discovers_nested_files(tmp_path):
    """嵌套目录语料递归发现（顶层 glob 缺口修复，P7 T1）。"""
    from calliodesmo.api.deps import AppStores
    from calliodesmo.ecl.demo_seed import seed_demo_stores

    demo_dir = tmp_path / "demo"
    demo_dir.mkdir()
    _write_nested_demo_tree(demo_dir)
    stores = AppStores()
    report = await seed_demo_stores(
        stores,
        _test_settings(tmp_path),
        demo_dir=demo_dir,
        cache_file=tmp_path / "cache.json",
        access=_admin_ctx(uuid.uuid4()),
    )
    assert report.source == "pipeline"
    assert report.documents == 3  # 子目录两篇不得漏
    doc_ids = {c.doc_id for c in stores.vector_store._records.values()}
    assert len(doc_ids) == 3


async def test_seed_demo_cache_invalidated_on_corpus_drift(tmp_path):
    """语料漂移（新增文件）→ 旧缓存迁移 .stale 并重建（P7 T1）。"""
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

    # 漂移：新增一篇语料
    (demo_dir / "public__extra.md").write_text(DEMO_MD, encoding="utf-8")
    second = AppStores()
    report2 = await seed_demo_stores(
        second, settings, demo_dir=demo_dir, cache_file=cache, access=_admin_ctx(team_id)
    )
    assert report2.source == "pipeline"  # 重建而非命中
    assert report2.documents == 4
    stale = tmp_path / "seed-cache.json.stale"
    assert stale.exists()  # 旧缓存迁移留痕
    assert cache.exists()  # 新缓存落盘


async def test_seed_demo_cache_invalidated_on_team_drift(tmp_path):
    """team 漂移 → 缓存失效重建（access 梯度随 team 变化，缓存不得复用）。"""
    from calliodesmo.api.deps import AppStores
    from calliodesmo.ecl.demo_seed import seed_demo_stores

    demo_dir = tmp_path / "demo"
    demo_dir.mkdir()
    _write_demo_tree(demo_dir)
    cache = tmp_path / "seed-cache.json"
    settings = _test_settings(tmp_path)

    first = AppStores()
    report1 = await seed_demo_stores(
        first, settings, demo_dir=demo_dir, cache_file=cache, access=_admin_ctx(uuid.uuid4())
    )
    assert report1.source == "pipeline"

    second = AppStores()
    report2 = await seed_demo_stores(
        second, settings, demo_dir=demo_dir, cache_file=cache, access=_admin_ctx(uuid.uuid4())
    )
    assert report2.source == "pipeline"
    assert (tmp_path / "seed-cache.json.stale").exists()


async def test_seed_demo_legacy_cache_migrated_to_stale(tmp_path):
    """遗留缓存（无 seed_key 标记）→ 迁移 .stale 并重建（P7 T1）。"""
    import json as _json

    from calliodesmo.api.deps import AppStores
    from calliodesmo.ecl.demo_seed import seed_demo_stores

    demo_dir = tmp_path / "demo"
    demo_dir.mkdir()
    _write_demo_tree(demo_dir)
    cache = tmp_path / "seed-cache.json"
    # 伪造旧版缓存：version=1 但无 seed_key
    cache.write_text(
        _json.dumps(
            {
                "version": 1,
                "chunks": [],
                "entities": [],
                "relations": [],
                "communities": [],
                "profile_cards": [],
            }
        ),
        encoding="utf-8",
    )

    stores = AppStores()
    report = await seed_demo_stores(
        stores,
        _test_settings(tmp_path),
        demo_dir=demo_dir,
        cache_file=cache,
        access=_admin_ctx(uuid.uuid4()),
    )
    assert report.source == "pipeline"
    assert report.documents == 3
    assert (tmp_path / "seed-cache.json.stale").exists()
    # 新缓存带 seed_key 标记
    raw = _json.loads(cache.read_text(encoding="utf-8"))
    assert raw.get("seed_key")


async def test_seed_demo_excludes_cache_artifacts_in_demo_dir(tmp_path):
    """缓存落在语料目录内（默认配置形态）不得被当语料摄入。"""
    from calliodesmo.api.deps import AppStores
    from calliodesmo.ecl.demo_seed import seed_demo_stores

    demo_dir = tmp_path / "demo"
    demo_dir.mkdir()
    _write_demo_tree(demo_dir)
    cache = demo_dir / "seed-cache.json"  # 默认配置：缓存在语料目录内

    first = AppStores()
    report1 = await seed_demo_stores(
        first,
        _test_settings(tmp_path),
        demo_dir=demo_dir,
        cache_file=cache,
        access=_admin_ctx(uuid.uuid4()),
    )
    assert report1.source == "pipeline"
    assert report1.documents == 3  # seed-cache.json 不算语料

    # 漂移触发重建：缓存与 .stale 均不得被摄入
    (demo_dir / "public__extra.md").write_text(DEMO_MD, encoding="utf-8")
    second = AppStores()
    report2 = await seed_demo_stores(
        second,
        _test_settings(tmp_path),
        demo_dir=demo_dir,
        cache_file=cache,
        access=_admin_ctx(uuid.uuid4()),
    )
    assert report2.source == "pipeline"
    assert report2.documents == 4
    doc_ids = {str(c.doc_id) for c in second.vector_store._records.values()}
    assert not any("seed-cache" in d for d in doc_ids)


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


def test_serve_seed_demo_flag_nested(tmp_path, monkeypatch, cli_db):
    """serve --seed-demo 嵌套语料：顶层 glob 缺口修复后不再 FileNotFoundError（P7 T1）。"""
    import sys
    from types import SimpleNamespace

    from typer.testing import CliRunner

    from calliodesmo.cli import app
    from calliodesmo.config import get_settings

    runner = CliRunner()
    demo_dir = tmp_path / "demo"
    demo_dir.mkdir()
    _write_nested_demo_tree(demo_dir)  # 两篇在 01/ 子目录

    monkeypatch.setenv("CALLIODESMO_LLM_MODEL", "test/stub")
    monkeypatch.setenv("CALLIODESMO_EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("CALLIODESMO_EMBEDDING_DIMENSION", "64")
    monkeypatch.setenv("CALLIODESMO_DEMO_DIR", str(demo_dir))
    monkeypatch.setenv("CALLIODESMO_DEMO_CACHE_FILE", str(tmp_path / "cache.json"))
    get_settings.cache_clear()

    calls: dict = {}

    def fake_run(*args, **kwargs):
        calls["ran"] = True
        from calliodesmo.api.deps import get_app_stores

        stores = get_app_stores()
        calls["docs"] = len({c.doc_id for c in stores.vector_store._records.values()})

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))
    try:
        assert runner.invoke(app, ["db", "init"]).exit_code == 0
        assert runner.invoke(app, ["db", "seed"]).exit_code == 0
        result = runner.invoke(app, ["serve", "--seed-demo"])
        assert result.exit_code == 0, result.output
        assert calls["ran"] is True
        assert calls["docs"] == 3  # 子目录两篇 + 顶层一篇
    finally:
        get_settings.cache_clear()
        from calliodesmo.api.deps import reset_app_stores

        reset_app_stores()
