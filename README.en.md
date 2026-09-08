[简体中文](./README.md) · [Website](https://templ8c.lei6393.com) · [GitHub](https://github.com/SuperMarioYL/templ8c)

<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="./assets/presentation/hero-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="./assets/presentation/hero-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="./assets/presentation/hero-dark.svg">
  <img src="./assets/presentation/hero-light.svg" width="960" alt="Hero diagram">
</picture>

# templ8c

**Check chat-template structure before serving**

templ8c renders canonical message sequences through a Jinja chat template and compares expected role markers, tool wrappers and field names. Its bundled templates demonstrate the checker’s own contracts.

## Why use it

A template change can alter the text surrounding a tool call while leaving the application code unchanged. Keeping message examples and expected markers together makes that structural drift visible in a repeatable local check.

- **Exercise multiple roles** — Canonical cases include system/user messages, tool calls and multi-turn output.
- **Name the missing field** — Each diff includes the field, expected marker, observed text and PASS/FAIL.
- **Read local configs** — TemplateLoader extracts chat_template from tokenizer_config.json for check_source.

## Architecture

<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="./assets/presentation/architecture-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="./assets/presentation/architecture-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="./assets/presentation/architecture-dark.svg">
  <img src="./assets/presentation/architecture-light.svg" width="960" alt="Architecture diagram">
</picture>

ConformanceSpec owns role markers, tool-call expectations and canonical cases. TemplateLoader reads a bundled template or a selected source. Renderer supplies a Jinja environment; Comparator checks marker/wrapper/name presence, and Checker assembles field-level results.

| Component | Responsibility |
| --- | --- |
| `ConformanceSpec` | markers and message cases |
| `TemplateLoader` | Jinja source |
| `Renderer` | canonical message outputs |
| `Comparator` | field-level PASS / FAIL |

## Install and quickstart

Python 3.12+ and uv. No model weights or inference server are required for template checks.

```bash
git clone https://github.com/SuperMarioYL/templ8c.git
cd templ8c
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e .
```

The example creates a local tokenizer_config.json from the bundled qwen3.8 template, loads it through the actual loader and repeats the check after removing the expected wrapper. No upstream template is downloaded.

```bash
.venv/bin/python examples/presentation_demo.py
```

## Recorded demo

<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="./assets/presentation/process-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="./assets/presentation/process-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="./assets/presentation/process-dark.svg">
  <img src="./assets/presentation/process-light.svg" width="960" alt="Process diagram">
</picture>

Ten checks pass for the bundled example; removing its wrapper creates two failing fields.

```text
{"input": "bundled example", "passed": true, "checks": 10, "failed_fields": []}
{"input": "wrapper removed", "passed": false, "checks": 10, "failed_fields": ["tool_call_wrapper", "tool_call_wrapper"]}
Scope: repository-authored reference templates; no upstream model release or inference server tested.
```

The complete command and output are recorded in [docs/demo-results.json](./docs/demo-results.json). Inputs and reproduction code are included in the repository.

![Existing terminal recording](./assets/demo.gif)

The existing recording is retained for context; the text example above documents the reproducible scenario.

## Usage

The CLI model IDs select repository-defined families and aliases. For a local artifact in Python, source = TemplateLoader().load_from_tokenizer_config("tokenizer_config.json"), followed by Checker().check_source("qwen3.8", source). Read result.diffs and result.failed_count; update the specification only when you have an authoritative reason to change the expected contract.

```bash
.venv/bin/templ8c models
.venv/bin/templ8c render --model qwen3.8 --message "请查询天气。"
.venv/bin/templ8c check --model qwen3.8
```

## Configuration

Specifications live in src/templ8c/reference/specs.py. Template config input accepts a chat_template string or a list of named entries, using the first template in the latter form. Remote helper methods fetch repository defaults rather than pinning an immutable revision; download a chosen revision locally when reproducibility matters. --server prints a notice and still checks the bundled template.

## Integrations and responsibilities

<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="./assets/presentation/integrations-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="./assets/presentation/integrations-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="./assets/presentation/integrations-dark.svg">
  <img src="./assets/presentation/integrations-light.svg" width="960" alt="Integrations diagram">
</picture>

The default check command compares a repository-authored reference with its matching repository spec. To inspect a real model artifact, load its actual tokenizer_config.json and call check_source. A successful bundled check is not verification of an upstream model release.

| Route | Implemented role |
| --- | --- |
| Jinja source | render canonical messages |
| tokenizer_config.json | local template extraction |
| HF / ModelScope | explicit remote loader methods |
| Python API | check_source for custom templates |
| CLI | render / check / models |

## Limits and next steps

- The comparator primarily checks substring presence. It does not parse all tool JSON semantics or prove template equivalence.
- Bundled specs and family names are repository fixtures, not verified upstream contracts.
- Inference-server probes are not implemented. A template PASS says nothing about live tool-call quality.

Implemented: local rendering, reference contracts, source loaders and field-level comparison. Future directions include validated upstream references, deeper structural comparison and actual inference-server probes.

## License and contributions

See [LICENSE](./LICENSE). When reporting an issue, include a minimal input, the command, and the observed output.
