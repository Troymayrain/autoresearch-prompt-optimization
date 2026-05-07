import pytest

from optimizer.prompt_gate import PromptGateError, validate_prompt_file


def test_validate_prompt_file_accepts_required_exports(tmp_path):
    prompt = tmp_path / "ocr.js"
    prompt.write_text(
        "module.exports={PROMPT_PREFIX:'a',PROMPT_SIMPLE:'b',PROMPT_COMPLEX:'c',PROMPT_COMPLET:'d',PROMPT_DETECT:'e'};",
        encoding="utf-8",
    )

    validate_prompt_file(prompt, node_binary="node")


def test_validate_prompt_file_rejects_missing_export(tmp_path):
    prompt = tmp_path / "ocr.js"
    prompt.write_text("module.exports={PROMPT_PREFIX:'a'};", encoding="utf-8")

    with pytest.raises(PromptGateError, match="missing exports"):
        validate_prompt_file(prompt, node_binary="node")


def test_validate_prompt_file_rejects_syntax_error(tmp_path):
    prompt = tmp_path / "ocr.js"
    prompt.write_text("module.exports={PROMPT_PREFIX:;", encoding="utf-8")

    with pytest.raises(PromptGateError, match="SyntaxError|syntax"):
        validate_prompt_file(prompt, node_binary="node")
