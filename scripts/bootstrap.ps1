#requires -Version 5.1
<#
.SYNOPSIS
  Calliodesmo 一键本地引导（无 Docker 原生部署）。
.DESCRIPTION
  检查 uv -> uv sync --extra persistence -> 准备 .env -> db init -> db seed。
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
    Write-Host '==> [1/5] 检查 uv' -ForegroundColor Cyan
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw '未找到 uv。安装: https://docs.astral.sh/uv/getting-started/installation/'
    }
    Invoke-Native { uv --version } 'uv --version'

    Write-Host '==> [2/5] 同步依赖（含 persistence extra：pgvector / neo4j）' -ForegroundColor Cyan
    Invoke-Native { uv sync --extra persistence } 'uv sync --extra persistence'

    Write-Host '==> [3/5] 准备 .env' -ForegroundColor Cyan
    if (-not (Test-Path '.env')) {
        Copy-Item '.env.example' '.env'
        Write-Host '    已从 .env.example 生成 .env（请填 PG/Neo4j 连接串与 JWT_SECRET_KEY）'
    } else {
        Write-Host '    .env 已存在，跳过'
    }

    Write-Host '==> [4/5] 建表 (db init)' -ForegroundColor Cyan
    Invoke-Native { uv run calliodesmo db init } 'db init'

    Write-Host '==> [5/5] 写入内置角色/管理员/系统账户 (db seed)' -ForegroundColor Cyan
    Invoke-Native { uv run calliodesmo db seed } 'db seed'

    Write-Host ''
    Write-Host '引导完成。下一步：' -ForegroundColor Green
    Write-Host '  uv run calliodesmo serve --reload   # 启动 API（/healthz、/docs）'
    Write-Host '  uv run pytest                       # 全量测试（连 .env 的 PG+Neo4j）'
    Write-Host '  uv run pytest -m "not db"           # 仅纯逻辑（CI 等价，不连 DB）'
}
finally {
    Pop-Location
}
