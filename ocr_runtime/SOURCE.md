# OCR Runtime Source

- Source repository: /Users/chushimima1234/projects/nodejs/code-ocr
- Source commit: 266545823d7d69cf92e9a8530b180b58e21314a0
- Snapshot date: 2026-05-27

## Copied Files

- ai-provider.js
- handler-ocr.js
- shared.js
- utils.js
- local-images.js
- log-sanitizer.js
- prompts/ocr.js copied to ../prompts/ocr.js

## Local Runtime Patch

- ocr_runtime/prompts/index.js re-exports ../../prompts/ocr so the optimizer has exactly one editable prompt file.
- ocr_runtime/package.json declares local runtime dependencies required by utils.js and ai-provider.js.
