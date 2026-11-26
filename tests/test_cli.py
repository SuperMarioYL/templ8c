"""CLI tests for the v0.2.0 surfaces: real template sources and the server
probe.

All remote paths run against httpx.MockTransport fixtures via monkeypatched
constructors in templ8c.cli - no network access. Exit codes: 0 conformant,
1 check failure or fetch/load error, 2 malformed options.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

import templ8c.cli as cli_module
from templ8c.cli import app
from templ8c.reference.specs import get_spec
from templ8c.render import Renderer
from templ8c.server_probe import ServerProbe
from templ8c.template_loader import TemplateLoader

runner = CliRunner()

BROKEN_TEMPLATE = "{% for m in messages %}{{ m['content'] }}{% endfor %}"


def _plain(output: str) -> str:
    """Strip ANSI styling, panel borders and line wrapping.

    rich renders error panels at the console width with ANSI colors on CI,
    so a multi-word error message can wrap inside the panel; asserting
    against the unwrapped text keeps the tests width-independent.
    """
    no_ansi = re.sub(r"\x1b\[[0-9;]*m", "", output)
    no_box = re.sub(r"[│╭╮╰╯─┬┴┼┌┐└┘┤├]", " ", no_ansi)
    return re.sub(r"\s+", " ", no_box)


def _write_tokenizer_config(tmp_path: Path, template: str) -> Path:
    path = tmp_path / "tokenizer_config.json"
    path.write_text(json.dumps({"chat_template": template}), encoding="utf-8")
    return path


# -- --tokenizer-config / --source -------------------------------------------


def test_check_bundled_default_passes() -> None:
    result = runner.invoke(app, ["check", "--model", "qwen3.8"])
    assert result.exit_code == 0
    assert "Template source: bundled reference" in result.output
    assert "PASS" in result.output


def test_check_unsupported_model_fails_cleanly() -> None:
    result = runner.invoke(app, ["check", "--model", "llama-4"])
    assert result.exit_code == 1
    assert "unsupported model" in _plain(result.output)
    assert "Traceback" not in result.output


def test_check_real_tokenizer_config_mismatch_fails(tmp_path: Path) -> None:
    cfg = _write_tokenizer_config(tmp_path, BROKEN_TEMPLATE)
    result = runner.invoke(app, ["check", "--model", "qwen3.8", "--tokenizer-config", str(cfg)])
    assert result.exit_code == 1
    assert "FAIL" in result.output
    # (rich may wrap the long tmp path; assert the source-line prefix)
    assert "Template source: tokenizer_config.json (local:" in result.output


def test_check_real_tokenizer_config_conformant_passes(tmp_path: Path) -> None:
    cfg = _write_tokenizer_config(tmp_path, get_spec("qwen3.8").template)
    result = runner.invoke(app, ["check", "--model", "qwen3.8", "--tokenizer-config", str(cfg)])
    assert result.exit_code == 0


def test_check_tokenizer_config_and_source_mutually_exclusive(tmp_path: Path) -> None:
    cfg = _write_tokenizer_config(tmp_path, BROKEN_TEMPLATE)
    result = runner.invoke(
        app,
        ["check", "--model", "qwen3.8", "--tokenizer-config", str(cfg), "--source", "hf:a/b"],
    )
    assert result.exit_code == 2
    assert "mutually exclusive" in _plain(result.output)


def test_check_missing_tokenizer_config_fails_cleanly() -> None:
    result = runner.invoke(
        app, ["check", "--model", "qwen3.8", "--tokenizer-config", "/nonexistent/tok.json"]
    )
    assert result.exit_code == 1
    assert "error" in result.output.lower()
    assert "Traceback" not in result.output


def test_check_tokenizer_config_without_template_field(tmp_path: Path) -> None:
    cfg = tmp_path / "tokenizer_config.json"
    cfg.write_text("{}", encoding="utf-8")
    result = runner.invoke(app, ["check", "--model", "qwen3.8", "--tokenizer-config", str(cfg)])
    assert result.exit_code == 1
    assert "chat_template" in result.output


def test_check_source_hf_via_mock(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == (
            "https://huggingface.co/zai-org/Qwen3.8-Test/resolve/main/tokenizer_config.json"
        )
        return httpx.Response(200, json={"chat_template": get_spec("qwen3.8").template})

    real_loader = TemplateLoader
    monkeypatch.setattr(
        cli_module, "TemplateLoader", lambda: real_loader(transport=httpx.MockTransport(handler))
    )
    result = runner.invoke(
        app, ["check", "--model", "qwen3.8", "--source", "hf:zai-org/Qwen3.8-Test"]
    )
    assert result.exit_code == 0
    assert "Template source: tokenizer_config.json (HuggingFace: zai-org/Qwen3.8-Test)" in (
        result.output
    )


def test_check_source_hf_404_fails_cleanly(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    real_loader = TemplateLoader
    monkeypatch.setattr(
        cli_module, "TemplateLoader", lambda: real_loader(transport=httpx.MockTransport(handler))
    )
    result = runner.invoke(app, ["check", "--model", "qwen3.8", "--source", "hf:nope/nothing"])
    assert result.exit_code == 1
    assert "failed to fetch" in _plain(result.output)
    assert "Traceback" not in result.output


# -- chat_template.jinja fallback (v0.3.0 fix) --------------------------------
#
# Several CN releases ship tokenizer_config.json with chat_template null and put
# the template in the sibling chat_template.jinja (GLM-4.5/4.6, Kimi-K2,
# Qwen3-Omni). The mock serves either artifact by name, for both source schemes.


def _repo_transport(files: dict[str, httpx.Response]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.params.get("FilePath") or request.url.path.rsplit("/", 1)[-1]
        return files.get(name, httpx.Response(404, json={"error": "not found"}))

    return httpx.MockTransport(handler)


def _patch_loader(monkeypatch, transport: httpx.MockTransport) -> None:
    real_loader = TemplateLoader
    monkeypatch.setattr(cli_module, "TemplateLoader", lambda: real_loader(transport=transport))


@pytest.mark.parametrize("scheme,ref", [
    ("hf", "zai-org/GLM-4.5"),
    ("modelscope", "ZhipuAI/GLM-4.5"),
])
def test_check_source_falls_back_to_chat_template_jinja(monkeypatch, scheme, ref) -> None:
    _patch_loader(monkeypatch, _repo_transport({
        "tokenizer_config.json": httpx.Response(200, json={"chat_template": None}),
        "chat_template.jinja": httpx.Response(200, text=get_spec("qwen3.8").template),
    }))
    result = runner.invoke(app, ["check", "--model", "qwen3.8", "--source", f"{scheme}:{ref}"])
    assert result.exit_code == 0, result.output
    assert "Template source: chat_template.jinja (" in result.output
    assert "PASS" in result.output


def test_check_source_reports_inline_artifact_when_present(monkeypatch) -> None:
    _patch_loader(monkeypatch, _repo_transport({
        "tokenizer_config.json": httpx.Response(200, json={"chat_template": get_spec("qwen3.8").template}),
        "chat_template.jinja": httpx.Response(200, text="IGNORED"),
    }))
    result = runner.invoke(app, ["check", "--model", "qwen3.8", "--source", "hf:zai-org/Qwen3.8-Test"])
    assert result.exit_code == 0
    assert "Template source: tokenizer_config.json (HuggingFace:" in result.output


def test_check_source_both_artifacts_unusable_fails_cleanly(monkeypatch) -> None:
    _patch_loader(monkeypatch, _repo_transport({
        "tokenizer_config.json": httpx.Response(200, json={"chat_template": None}),
    }))
    result = runner.invoke(app, ["check", "--model", "qwen3.8", "--source", "hf:no/jinja"])
    assert result.exit_code == 1
    assert "failed to fetch" in _plain(result.output)
    assert "Traceback" not in result.output


# -- malformed tokenizer_config.json (v0.3.0 fix) -----------------------------


@pytest.mark.parametrize("body", [
    {"chat_template": []},
    {"chat_template": [{"name": "default"}]},
])
def test_check_malformed_tokenizer_config_fails_cleanly(tmp_path: Path, body: dict) -> None:
    cfg = tmp_path / "tokenizer_config.json"
    cfg.write_text(json.dumps(body), encoding="utf-8")
    result = runner.invoke(app, ["check", "--model", "qwen3.8", "--tokenizer-config", str(cfg)])
    assert result.exit_code == 1
    assert "chat_template" in result.output
    assert "Traceback" not in result.output


# -- unrenderable templates (v0.3.0 fix) --------------------------------------


def test_check_tokenizer_config_render_failure_fails_cleanly(tmp_path: Path) -> None:
    cfg = _write_tokenizer_config(tmp_path, "{{ nothing() }}")
    result = runner.invoke(app, ["check", "--model", "qwen3.8", "--tokenizer-config", str(cfg)])
    assert result.exit_code == 1
    assert "failed to render" in _plain(result.output)
    assert "Traceback" not in result.output


def test_check_tokenizer_config_sandbox_rejection_fails_cleanly(tmp_path: Path) -> None:
    cfg = _write_tokenizer_config(
        tmp_path, "{{ ().__class__.__bases__[0].__subclasses__() | length }}"
    )
    result = runner.invoke(app, ["check", "--model", "qwen3.8", "--tokenizer-config", str(cfg)])
    assert result.exit_code == 1
    assert "failed to render" in _plain(result.output)
    assert "Traceback" not in result.output


def test_render_render_failure_fails_cleanly(tmp_path: Path) -> None:
    cfg = _write_tokenizer_config(tmp_path, "{{ nothing() }}")
    result = runner.invoke(
        app, ["render", "--model", "qwen3.8", "--tokenizer-config", str(cfg), "--message", "hi"]
    )
    assert result.exit_code == 1
    assert "failed to render" in _plain(result.output)
    assert "Traceback" not in result.output


def test_check_source_bad_format_rejected() -> None:
    result = runner.invoke(app, ["check", "--model", "qwen3.8", "--source", "huggingface:a/b"])
    assert result.exit_code == 2
    assert "--source must be hf:<repo_id> or modelscope:<model_id>" in _plain(result.output)


def test_render_with_tokenizer_config(tmp_path: Path) -> None:
    custom = "CUSTOM-START{% for m in messages %}{{ m['content'] }}{% endfor %}CUSTOM-END"
    cfg = _write_tokenizer_config(tmp_path, custom)
    result = runner.invoke(
        app,
        ["render", "--model", "qwen3.8", "--tokenizer-config", str(cfg), "--message", "hello"],
    )
    assert result.exit_code == 0
    assert "CUSTOM-STARThelloCUSTOM-END" in result.output


# -- prompt and diff text are data, not rich markup (v0.4.0 fix) -------------
#
# rich parses every plain string it prints as markup, so a prompt containing a
# paired bracketed marker ([INST]...[/INST], Mistral/Llama-2 style) or a closing
# tag without an opener ([/CALL_TOOL], this checker's own marker vocabulary when
# a template is malformed) raised
# "MarkupError: closing tag '...' doesn't match any open tag" out of the CLI.

INST_TEMPLATE = "{% for m in messages %}[INST] {{ m['content'] }} [/INST]{% endfor %}"
CLOSING_MARKER_TEMPLATE = (
    "{% for m in messages %}<|user|>{{ m['content'] }}[/CALL_TOOL]{% endfor %}"
)


def test_render_prints_bracketed_prompt_verbatim(tmp_path: Path) -> None:
    cfg = _write_tokenizer_config(tmp_path, INST_TEMPLATE)
    result = runner.invoke(
        app,
        ["render", "--model", "qwen3.8", "--tokenizer-config", str(cfg), "--message", "hi"],
    )
    assert result.exit_code == 0, result.output
    assert "[INST] hi [/INST]" in result.output
    assert "Traceback" not in result.output


def test_check_fail_table_prints_bracketed_snippet_verbatim(tmp_path: Path) -> None:
    cfg = _write_tokenizer_config(tmp_path, CLOSING_MARKER_TEMPLATE)
    result = runner.invoke(app, ["check", "--model", "glm-5.3", "--tokenizer-config", str(cfg)])
    assert result.exit_code == 1
    assert "FAIL" in result.output
    assert "CALL_TOOL" in result.output
    assert "Traceback" not in result.output


def test_error_message_with_closing_tag_is_not_markup() -> None:
    """The --tokenizer-config error path embeds the user's path in the message."""
    result = runner.invoke(
        app, ["check", "--model", "qwen3.8", "--tokenizer-config", "/nonexistent[/x]/tok.json"]
    )
    assert result.exit_code == 1
    assert "error" in _plain(result.output).lower()
    assert "Traceback" not in result.output


# -- local artifact resolution (v0.4.0 fixes) --------------------------------


def test_check_local_artifact_falls_back_to_chat_template_jinja(tmp_path: Path) -> None:
    """tokenizer_config.json with chat_template null + sibling chat_template.jinja
    is the shape --source already handled; the local path must resolve it too."""
    (tmp_path / "chat_template.jinja").write_text(get_spec("qwen3.8").template, encoding="utf-8")
    cfg = tmp_path / "tokenizer_config.json"
    cfg.write_text(json.dumps({"chat_template": None}), encoding="utf-8")

    result = runner.invoke(app, ["check", "--model", "qwen3.8", "--tokenizer-config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "Template source: chat_template.jinja (local:" in result.output
    assert "PASS" in result.output


def test_check_list_form_with_blank_first_entry_uses_the_usable_one(tmp_path: Path) -> None:
    cfg = tmp_path / "tokenizer_config.json"
    cfg.write_text(
        json.dumps(
            {
                "chat_template": [
                    {"name": "default", "template": ""},
                    {"name": "tool_use", "template": get_spec("qwen3.8").template},
                ]
            }
        ),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["check", "--model", "qwen3.8", "--tokenizer-config", str(cfg)])
    assert result.exit_code == 0, result.output


# -- --server probe -----------------------------------------------------------


def _probe_transport(template: str) -> httpx.MockTransport:
    """A fake inference server rendering with the given template."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        if request.url.path == "/tokenize":
            rendered = Renderer().render(template, body["messages"])
            return httpx.Response(
                200, json={"tokens": [ord(c) for c in rendered], "count": len(rendered)}
            )
        if request.url.path == "/detokenize":
            text = "".join(chr(t) for t in body["tokens"])
            return httpx.Response(200, json={"prompt": text, "text": text})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _patch_probe(monkeypatch, transport: httpx.MockTransport) -> None:
    real_probe = ServerProbe
    monkeypatch.setattr(
        cli_module, "ServerProbe", lambda server, url: real_probe(server, url, transport=transport)
    )


def test_check_server_vllm_conformant(monkeypatch) -> None:
    _patch_probe(monkeypatch, _probe_transport(get_spec("qwen3.8").template))
    result = runner.invoke(
        app,
        ["check", "--model", "qwen3.8", "--server", "vllm", "--server-url", "http://fake:1"],
    )
    assert result.exit_code == 0
    assert "Server probe: vllm @ http://fake:1" in result.output
    assert "Server check" in result.output


def test_check_server_vllm_mismatch_fails(monkeypatch) -> None:
    _patch_probe(monkeypatch, _probe_transport(BROKEN_TEMPLATE))
    result = runner.invoke(app, ["check", "--model", "qwen3.8", "--server", "vllm"])
    assert result.exit_code == 1
    assert "Server probe: vllm" in result.output


def test_check_server_sglang_conformant(monkeypatch) -> None:
    _patch_probe(monkeypatch, _probe_transport(get_spec("qwen3.8").template))
    result = runner.invoke(app, ["check", "--model", "qwen3.8", "--server", "sglang"])
    assert result.exit_code == 0
    assert "Server probe: sglang" in result.output


def test_check_server_unknown_kind_rejected() -> None:
    result = runner.invoke(app, ["check", "--model", "qwen3.8", "--server", "llama"])
    assert result.exit_code == 2
    assert "vllm" in result.output and "sglang" in result.output


def test_check_server_connection_error_fails_cleanly(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _patch_probe(monkeypatch, httpx.MockTransport(handler))
    result = runner.invoke(app, ["check", "--model", "qwen3.8", "--server", "sglang"])
    assert result.exit_code == 1
    assert "error" in result.output.lower()
    assert "Traceback" not in result.output


@pytest.mark.parametrize("response", [
    httpx.Response(200, text="<html>gateway error</html>"),
    httpx.Response(200, json=[1, 2, 3]),
])
def test_check_server_non_object_200_fails_cleanly(monkeypatch, response) -> None:
    """A 200 whose body is not a JSON object is a probe error, not a traceback."""
    _patch_probe(monkeypatch, httpx.MockTransport(lambda request: response))
    result = runner.invoke(app, ["check", "--model", "qwen3.8", "--server", "vllm"])
    assert result.exit_code == 1
    assert "error" in result.output.lower()
    assert "Traceback" not in result.output
