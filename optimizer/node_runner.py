from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class OcrRunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class OcrPayload:
    image: str
    origin: int
    channel: str = "TB"
    type: str = "complex"

    def to_json(self) -> str:
        return json.dumps(
            {
                "image": self.image,
                "origin": self.origin,
                "channel": self.channel,
                "type": self.type,
            },
            ensure_ascii=False,
        )


class OcrRunner:
    def __init__(self, node_binary: str, runner_path: str | Path):
        self.node_binary = node_binary
        self.runner_path = Path(runner_path)

    async def run_one(self, payload: OcrPayload) -> dict[str, Any]:
        proc = await asyncio.create_subprocess_exec(
            self.node_binary,
            str(self.runner_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(payload.to_json().encode("utf-8"))
        if proc.returncode != 0:
            raise OcrRunnerError(
                stderr.decode("utf-8", errors="replace") or f"node exited {proc.returncode}"
            )
        try:
            result = json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise OcrRunnerError(f"invalid JSON stdout: {stdout[:200]!r}") from exc
        if not isinstance(result, dict):
            raise OcrRunnerError("node runner returned non-object JSON")
        return result
