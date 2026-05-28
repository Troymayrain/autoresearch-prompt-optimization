import pytest

from optimizer.prompt_gate import PromptGateError, validate_prompt_file


def _prompt(
    prefix="code rules",
    simple="simple output",
    complex_rules="## 类型判断\nold type\n## 输出格式\nnumber output",
    complet_rules=(
        "## 类型判断\nold type\n## 字段说明\n"
        "| 字段 | 判断规则 |\n|------|----------|\n"
        "| brand | protected brand |\n| number | code number |\n"
        "## 输出格式\nold output"
    ),
    detect="detect rules",
):
    return f"""
module.exports = {{
    PROMPT_PREFIX: {prefix!r},
    PROMPT_SIMPLE: {simple!r},
    PROMPT_COMPLEX: {complex_rules!r},
    PROMPT_COMPLET: {complet_rules!r},
    PROMPT_DETECT: {detect!r},
}};
"""


def _write_prompt(path, **kwargs):
    path.write_text(_prompt(**kwargs), encoding="utf-8")


def test_validate_prompt_file_accepts_required_exports(tmp_path):
    prompt = tmp_path / "ocr.js"
    prompt.write_text(
        'module.exports={PROMPT_PREFIX:`a`,PROMPT_SIMPLE:\'b\',"PROMPT_COMPLEX":"c",PROMPT_COMPLET:"d",PROMPT_DETECT:"e"};',
        encoding="utf-8",
    )

    validate_prompt_file(prompt, node_binary="node")


def test_validate_prompt_file_accepts_code_detect_change(tmp_path):
    accepted = tmp_path / "accepted.js"
    proposed = tmp_path / "proposed.js"
    _write_prompt(accepted)
    _write_prompt(proposed, detect="detect rules plus safer candidate recall")

    validate_prompt_file(proposed, node_binary="node", task="code", baseline_path=accepted)


def test_validate_prompt_file_accepts_code_output_rule_changes(tmp_path):
    accepted = tmp_path / "accepted.js"
    proposed = tmp_path / "proposed.js"
    _write_prompt(accepted)
    _write_prompt(
        proposed,
        complex_rules="## 类型判断\nold type\n## 输出格式\nnumber output plus stricter code extraction",
        complet_rules=(
            "## 类型判断\nold type\n## 字段说明\n"
            "| 字段 | 判断规则 |\n|------|----------|\n"
            "| brand | protected brand |\n| number | accepts visible hyphens |\n"
            "## 输出格式\ncode output"
        ),
    )

    validate_prompt_file(proposed, node_binary="node", task="code", baseline_path=accepted)


@pytest.mark.parametrize(
    "changed",
    [
        {"complex_rules": "## 类型判断\nnew type\n## 输出格式\nnumber output"},
        {
            "complet_rules": (
                "## 类型判断\nold type\n## 字段说明\n"
                "| 字段 | 判断规则 |\n|------|----------|\n"
                "| brand | changed |\n| number | code number |\n"
                "## 输出格式\nold output"
            )
        },
    ],
)
def test_validate_prompt_file_rejects_code_type_or_metadata_change(tmp_path, changed):
    accepted = tmp_path / "accepted.js"
    proposed = tmp_path / "proposed.js"
    _write_prompt(accepted)
    _write_prompt(proposed, **changed)

    with pytest.raises(PromptGateError, match="code task cannot change"):
        validate_prompt_file(proposed, node_binary="node", task="code", baseline_path=accepted)


def test_validate_prompt_file_accepts_type_rule_changes_only(tmp_path):
    accepted = tmp_path / "accepted.js"
    proposed = tmp_path / "proposed.js"
    _write_prompt(accepted)
    _write_prompt(
        proposed,
        complex_rules="## 类型判断\nnew type\n## 输出格式\nnumber output",
        complet_rules=(
            "## 类型判断\nnew type\n## 字段说明\n"
            "| 字段 | 判断规则 |\n|------|----------|\n"
            "| brand | protected brand |\n| number | code number |\n"
            "## 输出格式\nold output"
        ),
    )

    validate_prompt_file(proposed, node_binary="node", task="type", baseline_path=accepted)


@pytest.mark.parametrize(
    "changed",
    [
        {"complex_rules": "## 类型判断\nnew complex type\n## 输出格式\nnumber output"},
        {
            "complet_rules": (
                "## 类型判断\nnew complete type\n## 字段说明\n"
                "| 字段 | 判断规则 |\n|------|----------|\n"
                "| brand | protected brand |\n| number | code number |\n"
                "## 输出格式\nold output"
            )
        },
    ],
)
def test_validate_prompt_file_rejects_type_rule_divergence(tmp_path, changed):
    accepted = tmp_path / "accepted.js"
    proposed = tmp_path / "proposed.js"
    _write_prompt(accepted)
    _write_prompt(proposed, **changed)

    with pytest.raises(PromptGateError, match="type task requires aligned type rules"):
        validate_prompt_file(proposed, node_binary="node", task="type", baseline_path=accepted)


@pytest.mark.parametrize(
    "changed",
    [
        {"detect": "changed detect"},
        {"prefix": "changed number output"},
        {
            "complet_rules": (
                "## 类型判断\nold type\n## 字段说明\n"
                "| 字段 | 判断规则 |\n|------|----------|\n"
                "| brand | changed |\n| number | code number |\n"
                "## 输出格式\nold output"
            )
        },
    ],
)
def test_validate_prompt_file_rejects_type_forbidden_changes(tmp_path, changed):
    accepted = tmp_path / "accepted.js"
    proposed = tmp_path / "proposed.js"
    _write_prompt(accepted)
    _write_prompt(proposed, **changed)

    with pytest.raises(PromptGateError, match="type task cannot change"):
        validate_prompt_file(proposed, node_binary="node", task="type", baseline_path=accepted)


def test_validate_prompt_file_rejects_missing_export(tmp_path):
    prompt = tmp_path / "ocr.js"
    prompt.write_text("module.exports={PROMPT_PREFIX:'a'};", encoding="utf-8")

    with pytest.raises(PromptGateError, match="missing exports"):
        validate_prompt_file(prompt, node_binary="node")


@pytest.mark.parametrize(
    "decoy",
    [
        "// module.exports={PROMPT_PREFIX:'a',PROMPT_SIMPLE:'b',PROMPT_COMPLEX:'c',PROMPT_COMPLET:'d',PROMPT_DETECT:'e'};",
        "/* module.exports={PROMPT_PREFIX:'a',PROMPT_SIMPLE:'b',PROMPT_COMPLEX:'c',PROMPT_COMPLET:'d',PROMPT_DETECT:'e'}; */",
        "'module.exports={PROMPT_PREFIX:\"a\",PROMPT_SIMPLE:\"b\",PROMPT_COMPLEX:\"c\",PROMPT_COMPLET:\"d\",PROMPT_DETECT:\"e\"}';",
        '"module.exports={PROMPT_PREFIX:\'a\',PROMPT_SIMPLE:\'b\',PROMPT_COMPLEX:\'c\',PROMPT_COMPLET:\'d\',PROMPT_DETECT:\'e\'}";',
        "`module.exports={PROMPT_PREFIX:'a',PROMPT_SIMPLE:'b',PROMPT_COMPLEX:'c',PROMPT_COMPLET:'d',PROMPT_DETECT:'e'}`;",
    ],
)
def test_validate_prompt_file_ignores_module_exports_decoys(tmp_path, decoy):
    prompt = tmp_path / "ocr.js"
    prompt.write_text(
        f"""
{decoy}
module.exports = {{}};
""",
        encoding="utf-8",
    )

    with pytest.raises(PromptGateError, match="missing exports"):
        validate_prompt_file(prompt, node_binary="node")


def test_validate_prompt_file_does_not_execute_top_level_js(tmp_path):
    marker = tmp_path / "executed"
    prompt = tmp_path / "ocr.js"
    prompt.write_text(
        f"""
const fs = require('fs');
fs.writeFileSync({str(marker)!r}, 'bad');
module.exports = {{
    PROMPT_PREFIX: 'a',
    PROMPT_SIMPLE: 'b',
    PROMPT_COMPLEX: 'c',
    PROMPT_COMPLET: 'd',
    PROMPT_DETECT: 'e',
}};
""",
        encoding="utf-8",
    )

    validate_prompt_file(prompt, node_binary="node")

    assert not marker.exists()


def test_validate_prompt_file_rejects_non_string_export(tmp_path):
    prompt = tmp_path / "ocr.js"
    prompt.write_text(
        "module.exports={PROMPT_PREFIX:'a',PROMPT_SIMPLE:'b',PROMPT_COMPLEX:'c',PROMPT_COMPLET:'d',PROMPT_DETECT:123};",
        encoding="utf-8",
    )

    with pytest.raises(PromptGateError, match="PROMPT_DETECT"):
        validate_prompt_file(prompt, node_binary="node")


@pytest.mark.parametrize("prefix", [r"'\n'", r"'\u0020'"])
def test_validate_prompt_file_rejects_escaped_whitespace_prefix(tmp_path, prefix):
    prompt = tmp_path / "ocr.js"
    prompt.write_text(
        f"module.exports={{PROMPT_PREFIX:{prefix},PROMPT_SIMPLE:'b',PROMPT_COMPLEX:'c',PROMPT_COMPLET:'d',PROMPT_DETECT:'e'}};",
        encoding="utf-8",
    )

    with pytest.raises(PromptGateError, match="PROMPT_PREFIX"):
        validate_prompt_file(prompt, node_binary="node")


@pytest.mark.parametrize("prefix", [r"'\040'", r"'\q'"])
def test_validate_prompt_file_rejects_disallowed_escape(tmp_path, prefix):
    prompt = tmp_path / "ocr.js"
    prompt.write_text(
        f"module.exports={{PROMPT_PREFIX:{prefix},PROMPT_SIMPLE:'b',PROMPT_COMPLEX:'c',PROMPT_COMPLET:'d',PROMPT_DETECT:'e'}};",
        encoding="utf-8",
    )

    with pytest.raises(PromptGateError, match="escape"):
        validate_prompt_file(prompt, node_binary="node")


def test_validate_prompt_file_rejects_syntax_error(tmp_path):
    prompt = tmp_path / "ocr.js"
    prompt.write_text("module.exports={PROMPT_PREFIX:;", encoding="utf-8")

    with pytest.raises(PromptGateError, match="SyntaxError|syntax"):
        validate_prompt_file(prompt, node_binary="node")
