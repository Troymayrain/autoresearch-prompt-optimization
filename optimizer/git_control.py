from __future__ import annotations

import subprocess
from pathlib import Path


def restore_prompt(prompt_path: str | Path, content: str) -> None:
    Path(prompt_path).write_text(content, encoding="utf-8")


def _git(args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
    )
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed"
        raise RuntimeError(message)
    return result


def _repo_paths(prompt_path: str | Path) -> tuple[Path, str]:
    path = Path(prompt_path)
    cwd = path.parent if path.is_absolute() else Path.cwd()
    root = Path(_git(["rev-parse", "--show-toplevel"], cwd).stdout.strip()).resolve()
    absolute = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        relative = absolute.relative_to(root).as_posix()
    except ValueError:
        raise RuntimeError(f"prompt path is outside git repository: {prompt_path}") from None
    return root, relative


def _staged_paths(root: Path) -> list[str]:
    output = _git(["diff", "--cached", "--name-only"], root).stdout
    return [line.strip() for line in output.splitlines() if line.strip()]


def prompt_diff(prompt_path: str | Path) -> str:
    root, relative = _repo_paths(prompt_path)
    return _git(["diff", "HEAD", "--", relative], root).stdout


def commit_prompt(prompt_path: str | Path, message: str) -> None:
    root, relative = _repo_paths(prompt_path)
    staged_other = [path for path in _staged_paths(root) if path != relative]
    if staged_other:
        raise RuntimeError(f"staged changes outside prompt: {', '.join(staged_other)}")

    _git(["add", "--", relative], root)
    if _git(["diff", "--cached", "--quiet", "--", relative], root, check=False).returncode == 0:
        raise RuntimeError("no prompt changes to commit")

    staged_other = [path for path in _staged_paths(root) if path != relative]
    if staged_other:
        raise RuntimeError(f"staged changes outside prompt: {', '.join(staged_other)}")

    _git(["commit", "-m", message, "--", relative], root)
