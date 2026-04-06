"""Tests for CLI entrypoint and command registration."""

import re

from typer.testing import CliRunner

from ein_agent_cli.command import app

runner = CliRunner()


def _strip_ansi(text: str) -> str:
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


def test_help_exits_zero():
    result = runner.invoke(app, ['--help'])
    assert result.exit_code == 0


def test_investigate_command_registered():
    result = runner.invoke(app, ['investigate', '--help'])
    assert result.exit_code == 0
    assert 'investigation session' in _strip_ansi(result.output).lower()


def test_connect_command_registered():
    result = runner.invoke(app, ['connect', '--help'])
    assert result.exit_code == 0
    assert 'workflow-id' in _strip_ansi(result.output).lower()
