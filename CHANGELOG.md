# Changelog

All notable changes to templ8c are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-10-22

### Fixed

- **`tojson` accepts the arguments real templates pass.** The filter registered
  by the Renderer was `tojson(value)`, so rendering a real model's own template
  died with `TypeError: _tojson() got an unexpected keyword argument
  'ensure_ascii'` — which is exactly what the official `chat_template.jinja` of
  GLM-4.5 and GLM-4.6 (`tojson(ensure_ascii=False)`) and Kimi-K2
  (`tojson(separators=(',', ':'))`) call. It now mirrors transformers' override:
  `tojson(value, indent=None, ensure_ascii=False, separators=None,
  sort_keys=False)`, with the previous output preserved for a bare `tojson`.
- **Check models whose template lives in `chat_template.jinja`.** Several CN
  releases ship `tokenizer_config.json` with `chat_template: null` and keep the
  template in the sibling `chat_template.jinja` (GLM-4.5/4.6, Kimi-K2,
  Qwen3-Omni on both HuggingFace and ModelScope). `--source` now falls back to
  that artifact when the inline field is absent, and the `Template source:` line
  names the file actually used instead of always claiming
  `tokenizer_config.json`.
- **Malformed `chat_template` no longer prints a traceback.** An empty list, a
  list entry without a `template` key, a list of strings or a non-object
  tokenizer_config.json used to escape the CLI's error handling as
  IndexError/KeyError/TypeError. `_extract_chat_template` now validates the
  shape and raises the existing `ValueError`, so every malformed input exits 1
  with a one-line `error:` message — the behaviour the 0.2.0 entry above
  promised.
- **Probe responses that are not JSON objects are probe errors.** A 200 whose
  body is HTML (a proxy error page) raised `json.JSONDecodeError` and a 200 JSON
  array raised `AttributeError`, both escaping the CLI as tracebacks.
  `ServerProbe._post` now rejects a non-JSON or non-object 200 with a
  `ProbeError` naming the server kind and path.
- **A template that cannot be rendered is a clean error.** Reaching real
  templates (or pointing `--tokenizer-config` at one) made the render path throw
  a bare `jinja2.TemplateError` out of the CLI — a template that needs data the
  canonical test cases do not carry, or one the sandbox rejects, printed a
  traceback. `Checker` now converts it to a `ValueError` naming the failing test
  case (or the render call), so the CLI reports it as a one-line error and exits
  1.

### Added

- `web/site.json`'s `meta.content_version` is now pinned by the version-lockstep
  test alongside `__version__`, the pyproject version, the CLI output and the
  changelog headline.

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

[Unreleased]: https://github.com/SuperMarioYL/templ8c/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/SuperMarioYL/templ8c/releases/tag/v0.3.0
[0.2.0]: https://github.com/SuperMarioYL/templ8c/releases/tag/v0.2.0
[0.1.0]: https://github.com/SuperMarioYL/templ8c/releases/tag/v0.1.0
