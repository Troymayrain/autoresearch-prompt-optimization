import json
import stat

import pytest

from optimizer.node_runner import OcrPayload, OcrRunner, OcrRunnerError


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
