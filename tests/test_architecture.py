"""Executable dependency rules for the hexagonal package boundaries."""

import ast
from importlib.util import resolve_name
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "career_autofill"


def imports(path: Path):
    package = "career_autofill." + ".".join(path.relative_to(ROOT).parts[:-1])
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            yield resolve_name("." * node.level + module, package) if node.level else module


def test_dependencies_point_inward():
    for layer in ("domain", "application", "adapters/inbound", "adapters/outbound"):
        for path in (ROOT / layer).rglob("*.py"):
            for module in imports(path):
                if module.startswith("career_autofill"):
                    if layer == "domain":
                        assert module.startswith("career_autofill.domain"), (path, module)
                    elif layer == "application":
                        assert module.startswith(
                            ("career_autofill.domain", "career_autofill.application")
                        ), (path, module)
                    else:
                        assert not module.startswith("career_autofill.bootstrap"), (path, module)
                        opposite = "outbound" if layer.endswith("inbound") else "inbound"
                        assert not module.startswith(f"career_autofill.adapters.{opposite}"), (
                            path,
                            module,
                        )
                if layer in ("domain", "application"):
                    assert module.split(".")[0] not in {
                        "mcp",
                        "playwright",
                        "os",
                        "pathlib",
                        "tempfile",
                        "httpx",
                        "subprocess",
                    }, (path, module)
