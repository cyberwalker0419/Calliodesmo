#requires -Version 5.1
<#
.SYNOPSIS
  Calliodesmo 一键本地引导（无 Docker 原生部署）。
.DESCRIPTION
  检查 uv -> uv sync --extra persistence -> 准备 .env -> db init -> db seed
  -> db migrate（迁移台账核对）-> doctor（配置与连通体检）。
  幂等，重复执行安全。前置：PG 16+（含 pgvector 扩展）与 Neo4j 已按
  docs/deploy/native.md 安装运行，且 .env 指向它们。不再支持 SQLite。
  原生命令（uv 等）把进度写到 stderr：helper 内临时切换为 Continue 偏好，
  仅在其退出码非零时抛错，避免被 stderr 进度信息误判为终止错误。
.EXAMPLE
  .\scripts\bootstrap.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

# 显示原生命令 stdout/stderr（含进度），但仅在其退出码非零时抛错。
function Invoke-Native {
    param([scriptblock]$Block, [string]$Label)
    $ErrorActionPreference = 'Continue'
    $output = & $Block 2>&1
    $code = $LASTEXITCODE
    $output | ForEach-Object { Write-Host "    $_" }
    if ($code -ne 0) {
        throw "$Label 失败（退出码 $code）。"
    }
}

Push-Location $root
try {
    Write-Host '==> [1/7] 检查 uv' -ForegroundColor Cyan
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw '未找到 uv。安装: https://docs.astral.sh/uv/getting-started/installation/'
    }
    Invoke-Native { uv --version } 'uv --version'

    Write-Host '==> [2/7] 同步依赖（persistence：pgvector / neo4j；agent：LangGraph）' -ForegroundColor Cyan
    # Windows 控制台默认 GBK：开 UTF-8 让 CLI 中文输出可读
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    # 两个 extra 都要装：uv sync 不带某 extra 会把上次装的它卸掉（漏 agent 则 Agent 面 503）
    Invoke-Native { uv sync --extra persistence --extra agent } 'uv sync --extra persistence --extra agent'

    Write-Host '==> [3/7] 准备 .env' -ForegroundColor Cyan
    if (-not (Test-Path '.env')) {
        Copy-Item '.env.example' '.env'
        Write-Host '    已从 .env.example 生成 .env（请填 PG/Neo4j 连接串与 JWT_SECRET_KEY）'
    } else {
        Write-Host '    .env 已存在，跳过'
    }

    Write-Host '==> [4/7] 建表与迁移 (db init)' -ForegroundColor Cyan
    Invoke-Native { uv run calliodesmo db init } 'db init'

    Write-Host '==> [5/7] 写入内置角色/管理员/系统账户 (db seed)' -ForegroundColor Cyan
    Invoke-Native { uv run calliodesmo db seed } 'db seed'

    Write-Host '==> [6/7] 迁移台账核对 (db migrate，幂等)' -ForegroundColor Cyan
    Invoke-Native { uv run calliodesmo db migrate } 'db migrate'

    Write-Host '==> [7/7] 配置与连通体检 (doctor)' -ForegroundColor Cyan
    try {
        Invoke-Native { uv run calliodesmo doctor } 'doctor'
        Write-Host '    体检通过'
    } catch {
        Write-Host '    体检报告问题：按上面提示修 .env 后重跑本脚本（建表与种子已完成）' -ForegroundColor Yellow
    }

    if ((Test-Path 'frontend/package.json') -and (-not (Test-Path 'frontend/dist'))) {
        Write-Host ''
        Write-Host '    提示：未找到 frontend/dist，Web UI 需先构建：'
        Write-Host '      cd frontend; npm ci; npm run build'
    }

    Write-Host ''
    Write-Host '引导完成。下一步：' -ForegroundColor Green
    Write-Host '  uv run calliodesmo serve --reload   # 启动 API（/healthz 存活、/readyz 就绪、/docs）'
    Write-Host '  curl http://127.0.0.1:8000/readyz   # 组件级就绪自检（数据库 / 图库 / 配置）'
    Write-Host '  uv run pytest                       # 全量测试（连 .env 的 PG+Neo4j）'
    Write-Host '  uv run pytest -m "not db"           # 仅纯逻辑（CI 等价，不连 DB）'
}
finally {
    Pop-Location
}
