"""docs/tools.md must match the tool schemas the server actually sends."""

from pathlib import Path

import pytest
from scripts.gen_tool_docs import OUTPUT, render

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.anyio


async def test_tool_reference_is_up_to_date() -> None:
    assert OUTPUT.read_text() == await render(), (
        "docs/tools.md is out of date; run uv run python scripts/gen_tool_docs.py"
    )


def test_readme_links_to_existing_files() -> None:
    readme = (ROOT / "README.md").read_text()
    for target in [
        "docs/tools.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "LICENSE",
        "NOTICE",
    ]:
        assert f"]({target})" in readme
        assert (ROOT / target).exists()


def test_readme_example_matches_golden_summary() -> None:
    readme = (ROOT / "README.md").read_text()
    golden = (ROOT / "tests" / "golden" / "h100_germany_year.txt").read_text()
    assert golden in readme
