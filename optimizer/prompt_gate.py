from __future__ import annotations

import subprocess
from pathlib import Path

from optimizer.dataset import TaskName

REQUIRED_EXPORTS = {
    "PROMPT_PREFIX",
    "PROMPT_SIMPLE",
    "PROMPT_COMPLEX",
    "PROMPT_COMPLET",
    "PROMPT_DETECT",
}
TYPE_RULE_START = "## 类型判断"
TYPE_RULE_END_MARKERS = ("## 输出格式", "## 字段说明")


class PromptGateError(RuntimeError):
    pass


def _decode_js_escape(source: str, index: int) -> tuple[int, str]:
    if index + 1 >= len(source):
        raise PromptGateError("unterminated string literal")

    escape = source[index + 1]
    simple = {
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "v": "\v",
        "f": "\f",
        "b": "\b",
        "\\": "\\",
        "'": "'",
        '"': '"',
        "`": "`",
    }
    if escape in simple:
        return index + 2, simple[escape]
    if escape == "x":
        hex_value = source[index + 2 : index + 4]
        if len(hex_value) != 2 or any(char not in "0123456789abcdefABCDEF" for char in hex_value):
            raise PromptGateError("invalid hex escape")
        return index + 4, chr(int(hex_value, 16))
    if escape == "u":
        hex_value = source[index + 2 : index + 6]
        if len(hex_value) != 4 or any(char not in "0123456789abcdefABCDEF" for char in hex_value):
            raise PromptGateError("invalid unicode escape")
        return index + 6, chr(int(hex_value, 16))
    if escape.isdigit():
        raise PromptGateError("legacy octal escapes are not allowed")
    raise PromptGateError("unknown escape sequence")


def _skip_space_and_comments(source: str, index: int) -> int:
    while index < len(source):
        if source[index].isspace():
            index += 1
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            return len(source) if newline < 0 else _skip_space_and_comments(source, newline + 1)
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0:
                raise PromptGateError("unterminated comment")
            index = end + 2
            continue
        break
    return index


def _scan_string(source: str, index: int) -> tuple[int, str]:
    quote = source[index]
    index += 1
    chunks: list[str] = []
    while index < len(source):
        char = source[index]
        if char == "\\":
            index, decoded = _decode_js_escape(source, index)
            chunks.append(decoded)
            continue
        if quote == "`" and source.startswith("${", index):
            raise PromptGateError("template expressions are not string literals")
        if char == quote:
            return index + 1, "".join(chunks)
        chunks.append(char)
        index += 1
    raise PromptGateError("unterminated string literal")


def _scan_identifier(source: str, index: int) -> tuple[int, str]:
    if index >= len(source) or not (source[index].isalpha() or source[index] in "_$"):
        raise PromptGateError("expected export key")
    start = index
    index += 1
    while index < len(source) and (source[index].isalnum() or source[index] in "_$"):
        index += 1
    return index, source[start:index]


def _identifier_at(source: str, index: int) -> tuple[int, str] | None:
    if index >= len(source) or not (source[index].isalpha() or source[index] in "_$"):
        return None
    return _scan_identifier(source, index)


def _find_module_exports(source: str) -> int:
    index = 0
    while index < len(source):
        index = _skip_space_and_comments(source, index)
        if index >= len(source):
            break
        if source[index] in "'\"`":
            index, _ = _scan_string(source, index)
            continue

        identifier = _identifier_at(source, index)
        if identifier is None:
            index += 1
            continue

        index, name = identifier
        if name != "module":
            continue
        index = _skip_space_and_comments(source, index)
        if index >= len(source) or source[index] != ".":
            continue
        index = _skip_space_and_comments(source, index + 1)
        identifier = _identifier_at(source, index)
        if identifier is None:
            continue
        index, name = identifier
        if name == "exports":
            return index

    raise PromptGateError("missing module.exports object")


def _module_exports_body(source: str) -> str:
    index = _skip_space_and_comments(source, _find_module_exports(source))
    if index >= len(source) or source[index] != "=":
        raise PromptGateError("missing module.exports assignment")
    index = _skip_space_and_comments(source, index + 1)
    if index >= len(source) or source[index] != "{":
        raise PromptGateError("module.exports must be an object literal")

    start = index + 1
    depth = 1
    index += 1
    while index < len(source):
        index = _skip_space_and_comments(source, index)
        if index >= len(source):
            break
        char = source[index]
        if char in "'\"`":
            index, _ = _scan_string(source, index)
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start:index]
        index += 1
    raise PromptGateError("unterminated module.exports object")


def _static_exports(source: str) -> dict[str, str | None]:
    body = _module_exports_body(source)
    exports: dict[str, str | None] = {}
    index = 0
    while True:
        index = _skip_space_and_comments(body, index)
        if index >= len(body):
            return exports
        if body[index] == ",":
            index += 1
            continue

        if body[index] in "'\"":
            index, key = _scan_string(body, index)
        else:
            index, key = _scan_identifier(body, index)

        index = _skip_space_and_comments(body, index)
        if index >= len(body) or body[index] != ":":
            raise PromptGateError(f"export {key} must use key: value syntax")
        index = _skip_space_and_comments(body, index + 1)
        if index < len(body) and body[index] in "'\"`":
            index, value = _scan_string(body, index)
            exports[key] = value
            continue

        exports[key] = None
        while index < len(body) and body[index] != ",":
            if body[index] in "'\"`":
                index, _ = _scan_string(body, index)
            else:
                index += 1


def _required_string_exports(source: str) -> dict[str, str]:
    exports = _static_exports(source)
    missing = sorted(REQUIRED_EXPORTS - set(exports))
    if missing:
        raise PromptGateError(f"missing exports: {', '.join(missing)}")

    invalid = sorted(
        key for key in REQUIRED_EXPORTS if exports[key] is None or not exports[key].strip()
    )
    if invalid:
        raise PromptGateError(f"exports must be non-empty string literals: {', '.join(invalid)}")
    return {key: str(exports[key]) for key in REQUIRED_EXPORTS}


def _without_type_rules(value: str) -> str:
    start = value.find(TYPE_RULE_START)
    if start < 0:
        return value
    search_from = start + len(TYPE_RULE_START)
    ends = []
    for marker in TYPE_RULE_END_MARKERS:
        marker_index = value.find(marker, search_from)
        if marker_index >= 0:
            ends.append(marker_index)
    end = min(ends) if ends else len(value)
    return value[:start] + value[end:]


def _validate_task_boundary(
    proposed: dict[str, str],
    baseline: dict[str, str],
    task: TaskName,
) -> None:
    if task == "code":
        changed = [
            key for key in ("PROMPT_COMPLEX", "PROMPT_COMPLET") if proposed[key] != baseline[key]
        ]
        if changed:
            raise PromptGateError(f"code task cannot change protected exports: {', '.join(changed)}")
        return

    if task == "type":
        protected = REQUIRED_EXPORTS - {"PROMPT_COMPLEX", "PROMPT_COMPLET"}
        changed = [key for key in sorted(protected) if proposed[key] != baseline[key]]
        type_rule_leaks = [
            key
            for key in ("PROMPT_COMPLEX", "PROMPT_COMPLET")
            if _without_type_rules(proposed[key]) != _without_type_rules(baseline[key])
        ]
        if changed or type_rule_leaks:
            blocked = changed + type_rule_leaks
            raise PromptGateError(f"type task cannot change protected exports: {', '.join(blocked)}")
        return

    raise PromptGateError(f"unsupported task: {task}")


def validate_prompt_file(
    path: str | Path,
    node_binary: str = "node",
    task: TaskName | None = None,
    baseline_path: str | Path | None = None,
) -> None:
    prompt_path = Path(path)
    check = subprocess.run(
        [node_binary, "--check", str(prompt_path)],
        text=True,
        capture_output=True,
    )
    if check.returncode != 0:
        raise PromptGateError(check.stderr.strip() or "prompt syntax check failed")

    exports = _required_string_exports(prompt_path.read_text(encoding="utf-8"))
    if task is None and baseline_path is None:
        return
    if task is None or baseline_path is None:
        raise PromptGateError("task boundary validation requires task and baseline_path")
    baseline = _required_string_exports(Path(baseline_path).read_text(encoding="utf-8"))
    _validate_task_boundary(exports, baseline, task)
