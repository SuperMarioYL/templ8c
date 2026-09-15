"""CLI tests for the v0.2.0 surfaces: real template sources and the server
probe.

All remote paths run against httpx.MockTransport fixtures via monkeypatched
constructors in templ8c.cli - no network access. Exit codes: 0 conformant,
1 check failure or fetch/load error, 2 malformed options.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from typer.testing import CliRunner

import templ8c.cli as cli_module
from templ8c.cli import app
from templ8c.reference.specs import get_spec
from templ8c.render import Renderer
from templ8c.server_probe import ServerProbe
from templ8c.template_loader import TemplateLoader

runner = CliRunner()

BROKEN_TEMPLATE = "{% for m in messages %}{{ m['content'] }}{% endfor %}"


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
    assert "unsupported model" in result.output
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
    assert "mutually exclusive" in result.output


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
    assert "failed to fetch" in result.output
    assert "Traceback" not in result.output


def test_check_source_bad_format_rejected() -> None:
    result = runner.invoke(app, ["check", "--model", "qwen3.8", "--source", "huggingface:a/b"])
    assert result.exit_code == 2
    assert "--source must be hf:<repo_id> or modelscope:<model_id>" in result.output


def test_render_with_tokenizer_config(tmp_path: Path) -> None:
    custom = "CUSTOM-START{% for m in messages %}{{ m['content'] }}{% endfor %}CUSTOM-END"
    cfg = _write_tokenizer_config(tmp_path, custom)
    result = runner.invoke(
        app,
        ["render", "--model", "qwen3.8", "--tokenizer-config", str(cfg), "--message", "hello"],
    )
    assert result.exit_code == 0
    assert "CUSTOM-STARThelloCUSTOM-END" in result.output


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
