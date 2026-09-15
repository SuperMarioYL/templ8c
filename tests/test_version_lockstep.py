"""Lockstep test: every tool-version surface must agree.

Surfaces pinned here: ``templ8c.__version__``, the pyproject ``[project]``
version, the CLI ``--version`` output, and the latest CHANGELOG.md section.
templ8c has no data-format schema version constant (ConformanceSpec is
code-defined), so these are all the versioned surfaces.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from typer.testing import CliRunner

from templ8c import __version__
from templ8c.cli import app

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_version_matches_package() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == __version__


def test_cli_version_output_matches_package() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"templ8c {__version__}"


def test_changelog_latest_section_matches_package() -> None:
    text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    sections = re.findall(r"^## \[([0-9.]+)\]", text, re.MULTILINE)
    assert sections, "no version sections in CHANGELOG.md"
    assert sections[0] == __version__
