from __future__ import annotations

import json
import subprocess
from pathlib import Path

REQUIRED_EXPORTS = {
    "PROMPT_PREFIX",
    "PROMPT_SIMPLE",
    "PROMPT_COMPLEX",
    "PROMPT_COMPLET",
    "PROMPT_DETECT",
}


class PromptGateError(RuntimeError):
    pass


def validate_prompt_file(path: str | Path, node_binary: str = "node") -> None:
    prompt_path = Path(path)
    check = subprocess.run(
        [node_binary, "--check", str(prompt_path)],
        text=True,
        capture_output=True,
    )
    if check.returncode != 0:
        raise PromptGateError(check.stderr.strip() or "prompt syntax check failed")

    script = (
        "const prompt=require(process.argv[1]);"
        "process.stdout.write(JSON.stringify(Object.keys(prompt)));"
    )
    exports = subprocess.run(
        [node_binary, "-e", script, str(prompt_path.resolve())],
        text=True,
        capture_output=True,
    )
    if exports.returncode != 0:
        raise PromptGateError(exports.stderr.strip() or "prompt export check failed")

    try:
        keys = set(json.loads(exports.stdout))
    except json.JSONDecodeError as exc:
        raise PromptGateError("prompt export check returned invalid JSON") from exc

    missing = sorted(REQUIRED_EXPORTS - keys)
    if missing:
        raise PromptGateError(f"missing exports: {', '.join(missing)}")
