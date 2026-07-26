#requires -Version 5.1
<#
.SYNOPSIS
  Calliodesmo 一键本地引导（无 Docker 原生部署）。
.DESCRIPTION
  检查 uv -> uv sync -> 准备 .env -> db init -> db seed。
  幂等，重复执行安全。数据库需已按 docs/deploy/native.md 原生安装并启动；
  或用 -Sqlite 走零依赖开发模式（无 pgvector/Neo4j，功能受限）。
.EXAMPLE
  .\scripts\bootstrap.ps1
  .\scripts\bootstrap.ps1 -Sqlite
#>
[CmdletBinding()]
param(
    [switch]$Sqlite
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    Write-Host '==> [1/5] 检查 uv' -ForegroundColor Cyan
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw '未找到 uv。安装: https://docs.astral.sh/uv/getting-started/installation/'
    }
    uv --version

    Write-Host '==> [2/5] 同步依赖 (uv sync)' -ForegroundColor Cyan
    uv sync

    Write-Host '==> [3/5] 准备 .env' -ForegroundColor Cyan
    if (-not (Test-Path '.env')) {
        Copy-Item '.env.example' '.env'
        Write-Host '    已从 .env.example 生成 .env（请按需修改密钥与连接串）'
    } else {
        Write-Host '    .env 已存在，跳过'
    }

    if ($Sqlite) {
        Write-Host '==> 使用 SQLite 开发模式（功能受限，见 docs/deploy/native.md）' -ForegroundColor Yellow
        $env:CALLIODESMO_DATABASE_URL = 'sqlite+aiosqlite:///./data/calliodesmo-dev.db'
        New-Item -ItemType Directory -Force 'data' | Out-Null
        if (-not $env:CALLIODESMO_ADMIN_PASSWORD) { $env:CALLIODESMO_ADMIN_PASSWORD = 'admin-dev-only' }
    }

    Write-Host '==> [4/5] 建表 (db init)' -ForegroundColor Cyan
    uv run calliodesmo db init

    Write-Host '==> [5/5] 写入内置角色/管理员 (db seed)' -ForegroundColor Cyan
    uv run calliodesmo db seed

    Write-Host ''
    Write-Host '引导完成。下一步：' -ForegroundColor Green
    Write-Host '  uv run calliodesmo serve --reload   # 启动 API（/healthz、/docs）'
    Write-Host '  uv run pytest                       # 运行测试'
}
finally {
    Pop-Location
}