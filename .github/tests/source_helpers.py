"""Keep historical method harnesses attached to the refactored implementation."""

import ast
from pathlib import Path


def parse_source(source: str) -> ast.Module:
    """Resolve inherited coordinator methods for existing isolated AST tests."""
    tree = ast.parse(source)
    coordinator = next((node for node in tree.body if isinstance(node, ast.ClassDef)
                        and node.name == "ScooterCoordinator"), None)
    if coordinator is None or "from .runtime." not in source:
        return tree
    root = Path(__file__).resolve().parents[2] / "custom_components/ninebot_e_scooters/runtime"
    for path in sorted(root.glob("*.py")):
        module = ast.parse(path.read_text())
        for node in module.body:
            if isinstance(node, ast.ClassDef) and node.name.endswith("Mixin"):
                coordinator.body.extend(node.body[1:])
            elif isinstance(node, (ast.Assign, ast.AnnAssign)) and path.name == "constants.py":
                tree.body.insert(0, node)
    return tree
