# Changelog

All notable changes to templ8c are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-09-16

### Fixed

- **Sandboxed rendering.** The Renderer now builds an
  `ImmutableSandboxedEnvironment` (as its docstring always claimed and as
  transformers does), so an untrusted `tokenizer_config.json` template can no
  longer walk the Python class tree through Jinja attribute access.
- **Check real templates from the CLI.** `templ8c check` and `templ8c render`
  gain `--tokenizer-config <path>` and `--source hf:<repo_id>` /
  `--source modelscope:<model_id>`. Previously the CLI could only compare the
  bundled reference template against its own spec; checking a real model's
  tokenizer_config.json required dropping to the Python API. The
  `Template source:` line now reports which source was checked, and fetch or
  load failures exit 1 with a clear message instead of a traceback.
- **Inference-server probe (plan m3).** `templ8c check --server vllm|sglang`
  now performs the probe for real instead of printing a "not implemented"
  notice: each conformance test case is rendered through the server's chat
  template via the documented `POST /tokenize` (messages form) + `POST
  /detokenize` endpoints, and the server-rendered prompts are diffed against
  the same ConformanceSpec. `--server-url` overrides the default
  `http://localhost:8000`. SGLang's `skip_special_tokens=false` quirk and
  `text` response field are handled per its API; exit code is 1 if the
  template check or the probe fails.

### Added

- `templ8c --version`, this CHANGELOG.md, and a lockstep test that pins
  `templ8c.__version__`, the pyproject version, the CLI output and the
  changelog headline to the same value.

## [0.1.0] - 2026-08-31

Initial release: ConformanceSpec + bundled reference templates for GLM-5.3,
Qwen3.8 and DeepSeek-V4; template-only `check` / `render` / `models` CLI with
field-level PASS/FAIL diffs; TemplateLoader with local tokenizer_config.json
extraction and HuggingFace/ModelScope fetch helpers (Python API).

[Unreleased]: https://github.com/SuperMarioYL/templ8c/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/SuperMarioYL/templ8c/releases/tag/v0.2.0
[0.1.0]: https://github.com/SuperMarioYL/templ8c/releases/tag/v0.1.0
