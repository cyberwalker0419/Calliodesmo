"""Task 7 测试：CLI ask 命令。"""

from typer.testing import CliRunner

from calliodesmo.cli import app

runner = CliRunner()


def test_ask_native_rag():
    """CLI ask 默认 native_rag 模式，退出码 0。"""
    result = runner.invoke(app, ["ask", "What is AI?"])
    assert result.exit_code == 0
    assert "[模式]" in result.output
    assert "[答案]" in result.output


def test_ask_with_mode():
    """CLI ask --mode local，退出码 0。"""
    result = runner.invoke(app, ["ask", "What is AI?", "--mode", "local"])
    assert result.exit_code == 0
    assert "local" in result.output


def test_ask_invalid_mode():
    """非法 mode -> 退出码 1。"""
    result = runner.invoke(app, ["ask", "test", "--mode", "invalid"])
    assert result.exit_code == 1
