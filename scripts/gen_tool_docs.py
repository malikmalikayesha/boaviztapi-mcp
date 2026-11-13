"""Generate docs/tools.md from the server's own tool definitions.

Usage:
    uv run python scripts/gen_tool_docs.py          # write docs/tools.md
    uv run python scripts/gen_tool_docs.py --check  # fail if it is out of date

The reference is built from the schemas the server sends to clients, so it can
never describe a parameter the server does not have.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

import httpx2
import mcp

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from boaviztapi_mcp.config import Settings  # noqa: E402
from boaviztapi_mcp.server import create_server  # noqa: E402

OUTPUT = ROOT / "docs" / "tools.md"

HEADER = """\
# Tool reference

Generated from the server's tool schemas by `scripts/gen_tool_docs.py`; do not
edit by hand. Every tool is read-only, idempotent and calls BoaviztAPI over the
network. Every tool returns structured content and a plain-text `summary`.
"""


def _offline(_: httpx2.Request) -> httpx2.Response:
    raise AssertionError("listing tools must not call BoaviztAPI")


async def render() -> str:
    server = create_server(Settings(), transport=httpx2.MockTransport(_offline))
    async with mcp.Client(server) as client:
        tools = (await client.list_tools()).tools
    parts = [HEADER, "## Contents\n"]
    parts += [f"- [`{tool.name}`](#{tool.name}): {tool.title}" for tool in tools]
    shared: dict[str, Any] = {}
    for tool in tools:
        schema = tool.input_schema
        shared.update(schema.get("$defs", {}))
        parts.append(f"\n## `{tool.name}`\n")
        parts.append(f"**{tool.title}**\n")
        parts.append(_dedent(tool.description or "") + "\n")
        parts.append(_parameters(schema))
        output = (tool.output_schema or {}).get("title")
        if output:
            parts.append(f"Returns `{output}`.")
    if shared:
        parts.append("\n## Input types\n")
        for name in sorted(shared):
            parts.append(f"### `{name}`\n")
            parts.append(_parameters(shared[name]))
    return "\n".join(parts).rstrip() + "\n"


def _parameters(schema: dict[str, Any]) -> str:
    properties = schema.get("properties", {})
    if not properties:
        return "No parameters.\n"
    required = set(schema.get("required", []))
    rows = [
        "| Parameter | Type | Required | Default | Description |",
        "|---|---|---|---|---|",
    ]
    for name, spec in properties.items():
        default = f"`{spec['default']}`" if spec.get("default") is not None else ""
        description = (spec.get("description") or "").replace("|", "\\|")
        rows.append(
            f"| `{name}` | {_type(spec)} | {'yes' if name in required else 'no'}"
            f" | {default} | {description} |"
        )
    return "\n".join(rows) + "\n"


def _type(spec: dict[str, Any]) -> str:
    if "$ref" in spec:
        name = spec["$ref"].rsplit("/", 1)[-1]
        return f"[`{name}`](#{name.lower()})"
    if "anyOf" in spec:
        options = [s for s in spec["anyOf"] if s.get("type") != "null"]
        return " or ".join(_type(s) for s in options) or "null"
    if "enum" in spec:
        return "one of " + ", ".join(f"`{v}`" for v in spec["enum"])
    if "const" in spec:
        return f"`{spec['const']}`"
    kind = spec.get("type", "any")
    if kind == "array":
        text = f"list of {_type(spec.get('items', {}))}"
    elif kind == "object":
        text = "object"
    else:
        text = kind
    return text + _constraints(spec)


def _constraints(spec: dict[str, Any]) -> str:
    bits = []
    if "minimum" in spec:
        bits.append(f">= {spec['minimum']}")
    if "exclusiveMinimum" in spec:
        bits.append(f"> {spec['exclusiveMinimum']}")
    if "maximum" in spec:
        bits.append(f"<= {spec['maximum']}")
    if "minItems" in spec:
        bits.append(f"at least {spec['minItems']} items")
    if "maxItems" in spec:
        bits.append(f"at most {spec['maxItems']} items")
    return f" ({', '.join(bits)})" if bits else ""


def _dedent(text: str) -> str:
    lines = [line.strip() for line in text.strip().splitlines()]
    paragraphs, current = [], []
    for line in lines:
        if line:
            current.append(line)
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate docs/tools.md.")
    parser.add_argument("--check", action="store_true", help="fail if out of date")
    args = parser.parse_args()
    text = asyncio.run(render())
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text() != text:
            print("docs/tools.md is out of date; run scripts/gen_tool_docs.py")
            sys.exit(1)
        return
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(text)
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
