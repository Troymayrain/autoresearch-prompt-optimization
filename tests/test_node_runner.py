import json
import stat
from pathlib import Path

import pytest

from optimizer.node_runner import OcrPayload, OcrRunner, OcrRunnerError


def test_ocr_payload_serializes_mode_ocr():
    payload = json.loads(OcrPayload(image="ABC123", origin=0).to_json())

    assert payload["mode"] == "ocr"


@pytest.mark.asyncio
async def test_node_runner_returns_json_payload(tmp_path):
    script = tmp_path / "fake_runner.js"
    script.write_text(
        """
        process.stdin.setEncoding('utf8');
        let body = '';
        process.stdin.on('data', chunk => body += chunk);
        process.stdin.on('end', () => {
          const payload = JSON.parse(body);
          console.error('log line');
          process.stdout.write(JSON.stringify({status: 200, data: [{type: 'E-codes', number: payload.image}], imageStatus: ['ok']}));
        });
        """,
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    runner = OcrRunner(node_binary="node", runner_path=script)

    result = await runner.run_one(OcrPayload(image="ABC123", origin=0))

    assert result["status"] == 200
    assert result["data"][0]["number"] == "ABC123"


@pytest.mark.asyncio
async def test_node_runner_rejects_non_json_stdout(tmp_path):
    script = tmp_path / "bad_runner.js"
    script.write_text("process.stdout.write('not-json')", encoding="utf-8")
    runner = OcrRunner(node_binary="node", runner_path=script)

    with pytest.raises(OcrRunnerError, match="invalid JSON stdout"):
        await runner.run_one(OcrPayload(image="x", origin=0))


@pytest.mark.asyncio
async def test_node_runner_times_out_stuck_process(tmp_path):
    script = tmp_path / "stuck_runner.js"
    script.write_text("setInterval(() => {}, 1000)", encoding="utf-8")
    runner = OcrRunner(node_binary="node", runner_path=script, timeout_seconds=0.01)

    with pytest.raises(OcrRunnerError, match="timed out"):
        await runner.run_one(OcrPayload(image="x", origin=0))


@pytest.mark.asyncio
async def test_node_runner_raises_stderr_when_json_stdout_exits_nonzero(tmp_path):
    script = tmp_path / "failed_runner.js"
    script.write_text(
        """
        process.stdout.write(JSON.stringify({status: 500, message: 'failed'}));
        process.stderr.write('boom from runner');
        process.exitCode = 1;
        """,
        encoding="utf-8",
    )
    runner = OcrRunner(node_binary="node", runner_path=script)

    with pytest.raises(OcrRunnerError, match="boom from runner"):
        await runner.run_one(OcrPayload(image="x", origin=0))


def test_node_runner_resolves_relative_runner_path_from_repo_root(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    runner = OcrRunner(node_binary="node", runner_path="ocr_runtime/run_ocr.js")

    assert runner.runner_path == Path(__file__).resolve().parents[1] / "ocr_runtime/run_ocr.js"
