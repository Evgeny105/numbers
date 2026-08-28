"""Guards against the specific defects this rewrite removed.

These are structural tests. They are cheap, and each one corresponds to a bug
that actually shipped in the previous version — the kind that reappears quietly
during a refactor unless something fails loudly.
"""

from __future__ import annotations

import ast
import re
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


@pytest.mark.parametrize("path", python_files(), ids=str)
def test_no_private_network_addresses_in_code(path: Path) -> None:
    """Host addresses are configuration, not literals.

    A repository that names the home network's addresses leaks its layout to
    anyone who reads it, and pins the project to one particular house.
    """
    source = path.read_text(encoding="utf-8")
    for match in re.finditer(r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.[\d.]+", source):
        pytest.fail(f"{path} contains the private address {match.group(0)}")


def test_no_private_network_addresses_in_config_files() -> None:
    """Same rule for the files a reader looks at first."""
    pattern = re.compile(r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.[\d.]+")
    for name in (".env.example", "README.md", "docker-compose.yml", "docker-compose.ubuser.yml"):
        path = Path(name)
        if not path.exists():
            continue
        match = pattern.search(path.read_text(encoding="utf-8"))
        assert match is None, f"{name} contains the private address {match.group(0)}"


#: This repository is public. None of these belong in it: they identify the
#: author's machines, accounts and other projects, or are outright secrets.
PRIVATE_PATTERNS = (
    (r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.[\d.]+", "a private network address"),
    (r"/home/[a-z][a-z0-9_-]*/", "an absolute home directory path"),
    (r"\b\d{8,10}:AA[\w-]{30,}", "a Telegram bot token"),
    (r"sk-or-v1-[\w-]{20,}", "an OpenRouter API key"),
    (r"\bsk-[a-zA-Z0-9]{32,}", "an API key"),
)


def tracked_text_files() -> list[Path]:
    """Every tracked file that would be published, minus vendored blobs."""
    import subprocess

    output = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, text=True, check=True
    ).stdout
    files = [Path(name) for name in output.split("\0") if name]
    return [
        path
        for path in files
        if path.is_file() and path.suffix not in {".min.js", ".png", ".jpg", ".ico", ".lock"}
    ]


@pytest.mark.parametrize("path", tracked_text_files(), ids=str)
def test_tracked_files_carry_nothing_private(path: Path) -> None:
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return
    for pattern, description in PRIVATE_PATTERNS:
        match = re.search(pattern, source)
        assert match is None, f"{path} contains {description}: {match.group(0)[:24]}…"


def test_no_env_file_is_tracked() -> None:
    """Only the example may ever be committed."""
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout.split()
    env_files = [name for name in tracked if Path(name).name.startswith(".env")]
    assert env_files == [".env.example"], f"unexpected env files tracked: {env_files}"
