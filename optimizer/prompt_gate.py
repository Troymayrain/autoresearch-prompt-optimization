from __future__ import annotations

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
    return index + 2, escape


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


def _module_exports_body(source: str) -> str:
    marker = "module.exports"
    index = source.find(marker)
    if index < 0:
        raise PromptGateError("missing module.exports object")

    index = _skip_space_and_comments(source, index + len(marker))
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


def validate_prompt_file(path: str | Path, node_binary: str = "node") -> None:
    prompt_path = Path(path)
    check = subprocess.run(
        [node_binary, "--check", str(prompt_path)],
        text=True,
        capture_output=True,
    )
    if check.returncode != 0:
        raise PromptGateError(check.stderr.strip() or "prompt syntax check failed")

    exports = _static_exports(prompt_path.read_text(encoding="utf-8"))
    missing = sorted(REQUIRED_EXPORTS - set(exports))
    if missing:
        raise PromptGateError(f"missing exports: {', '.join(missing)}")

    invalid = sorted(
        key for key in REQUIRED_EXPORTS if exports[key] is None or not exports[key].strip()
    )
    if invalid:
        raise PromptGateError(f"exports must be non-empty string literals: {', '.join(invalid)}")
