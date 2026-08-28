"""Guards against the specific defects this rewrite removed.

These are structural tests. They are cheap, and each one corresponds to a bug
that actually shipped in the previous version — the kind that reappears quietly
during a refactor unless something fails loudly.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SOURCE_ROOTS = (Path("bot"), Path("admin"), Path("tools"))


def python_files() -> list[Path]:
    files: list[Path] = []
    for root in SOURCE_ROOTS:
        if root.exists():
            files.extend(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)
    return files


def test_there_are_source_files_to_check() -> None:
    assert python_files(), "the guards below would silently pass with no files"


@pytest.mark.parametrize("path", python_files(), ids=str)
def test_no_dynamic_code_evaluation(path: Path) -> None:
    """`eval` on a generated string was how the old generator computed answers."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in ("eval", "exec", "compile"), (
                f"{path}:{node.lineno} calls {node.func.id}()"
            )


@pytest.mark.parametrize("path", python_files(), ids=str)
def test_no_fire_and_forget_state_mutations(path: Path) -> None:
    """State writes must be awaited.

    The old handlers wrapped every `update_data` / `set_state` / `clear` in an
    unawaited `asyncio.create_task`, so a score could be written after the next
    problem had been generated — and, with no reference kept, the task could be
    collected before it ran at all.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mutations = {"update_data", "set_state", "clear", "set_data"}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "create_task"):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr in mutations
            ):
                pytest.fail(
                    f"{path}:{node.lineno} schedules {inner.func.attr}() without awaiting it"
                )


@pytest.mark.parametrize("path", python_files(), ids=str)
def test_no_secrets_are_logged_unmasked(path: Path) -> None:
    """A token or API key must never be interpolated straight into a log call."""
    source = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(source.splitlines(), start=1):
        if "_LOGGER" not in line and "logger" not in line.lower():
            continue
        for secret in ("bot_token", "api_key", "llm_api_key", "_api_key"):
            if secret in line and "mask" not in line:
                pytest.fail(f"{path}:{lineno} may log a secret: {line.strip()}")
