import ast
from pathlib import Path


def test_supporting_library_does_not_depend_on_application_services():
    library = Path(__file__).resolve().parents[1] / "lib"
    for path in library.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            assert not any(
                module == "app" or module.startswith("app.") for module in modules
            ), path
