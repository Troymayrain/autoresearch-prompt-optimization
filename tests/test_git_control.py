import subprocess

import pytest

from optimizer.git_control import commit_prompt, restore_prompt


def test_restore_prompt_uses_saved_content(tmp_path):
    prompt = tmp_path / "ocr.js"
    prompt.write_text("new", encoding="utf-8")

    restore_prompt(prompt, "old")

    assert prompt.read_text(encoding="utf-8") == "old"


def test_commit_prompt_refuses_staged_non_prompt_changes(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    prompt = tmp_path / "prompts" / "ocr.js"
    prompt.parent.mkdir()
    prompt.write_text("old", encoding="utf-8")
    other = tmp_path / "other.txt"
    other.write_text("old", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True)

    prompt.write_text("new", encoding="utf-8")
    other.write_text("new", encoding="utf-8")
    subprocess.run(["git", "add", "other.txt"], cwd=tmp_path, check=True)

    with pytest.raises(RuntimeError, match="staged changes outside prompt"):
        commit_prompt(prompt, "prompt change")

    assert subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip() == "other.txt"


def test_commit_prompt_commits_only_prompt_with_unstaged_unrelated_changes(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    prompt = tmp_path / "prompts" / "ocr.js"
    prompt.parent.mkdir()
    prompt.write_text("old", encoding="utf-8")
    other = tmp_path / "other.txt"
    other.write_text("old", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True)

    prompt.write_text("new", encoding="utf-8")
    other.write_text("new", encoding="utf-8")

    commit_prompt(prompt, "prompt change")

    committed = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip().splitlines()
    assert committed == ["prompts/ocr.js"]
    assert subprocess.run(
        ["git", "diff", "--", "other.txt"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
