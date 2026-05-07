# OCR Runtime Source

- Source repository: /Users/chushimima1234/projects/nodejs/code-ocr
- Source commit: 31291ba6304f01309815aa254021367a5144df96
- Snapshot date: 2026-05-07

## Copied Files

- ai-provider.js
- handler-ocr.js
- shared.js
- utils.js
- log-sanitizer.js
- prompts/ocr.js copied to ../prompts/ocr.js

## Local Runtime Patch

- ocr_runtime/prompts/index.js re-exports ../../prompts/ocr so the optimizer has exactly one editable prompt file.
- ocr_runtime/package.json declares local runtime dependencies required by utils.js and ai-provider.js.
