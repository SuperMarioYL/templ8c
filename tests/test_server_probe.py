"""ServerProbe unit tests against httpx.MockTransport fakes.

The fakes implement the endpoint contracts verified from the platforms'
upstream sources: vLLM ``/tokenize`` takes messages + add_generation_prompt
and applies the server's chat template; ``/detokenize`` takes token ids and
returns ``{"prompt": text}``. SGLang exposes the same pair (accepting only
messages on /tokenize) but returns ``{"text": ...}`` from /detokenize and
defaults ``skip_special_tokens`` to true — which strips the <|...|> markers
this checker looks for, so the probe must send false explicitly. The fake
emulates that stripping to make the quirk behaviorally visible.
"""

from __future__ import annotations

import json
import re

import httpx
import pytest

from templ8c.comparator import FAIL, PASS, Comparator
from templ8c.reference.specs import get_spec
from templ8c.render import Renderer
from templ8c.server_probe import ProbeError, ServerProbe

BROKEN_TEMPLATE = "{% for m in messages %}{{ m['content'] }}{% endfor %}"


class FakeInferenceServer:
    """Serves the documented /tokenize + /detokenize contract for one server
    kind, rendering incoming messages with the template it is configured
    with (its "chat template"). Token ids are char ordinals so /detokenize
    round-trips the exact rendered text."""

    def __init__(self, kind: str, template: str) -> None:
        self.kind = kind
        self.template = template
        self.requests: list[tuple[str, dict]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        self.requests.append((request.url.path, body))
        if request.url.path == "/tokenize":
            rendered = Renderer().render(self.template, body["messages"])
            return httpx.Response(
                200,
                json={
                    "tokens": [ord(c) for c in rendered],
                    "count": len(rendered),
                    "max_model_len": 8192,
                },
            )
        if request.url.path == "/detokenize":
            text = "".join(chr(t) for t in body["tokens"])
            if self.kind == "sglang" and body.get("skip_special_tokens", True):
                text = re.sub(r"<\|[^|>]+\|>", "", text)
            key = "prompt" if self.kind == "vllm" else "text"
            return httpx.Response(200, json={key: text})
        return httpx.Response(404, json={"error": "not found"})


def _bodies(fake: FakeInferenceServer, path: str) -> list[dict]:
    return [body for req_path, body in fake.requests if req_path == path]


def test_probe_vllm_conformant_server_passes() -> None:
    spec = get_spec("qwen3.8")
    fake = FakeInferenceServer("vllm", spec.template)
    probe = ServerProbe("vllm", "http://server.test", transport=fake.transport())

    rendered = probe.render_test_cases(spec)
    diffs = Comparator().compare(spec, rendered)

    assert all(d.status == PASS for d in diffs), diffs


def test_probe_vllm_request_shapes() -> None:
    spec = get_spec("qwen3.8")
    fake = FakeInferenceServer("vllm", spec.template)
    ServerProbe("vllm", "http://server.test", transport=fake.transport()).render_test_cases(spec)

    tokenize_bodies = _bodies(fake, "/tokenize")
    assert tokenize_bodies, "no /tokenize request recorded"
    assert all("messages" in b and b["add_generation_prompt"] is True for b in tokenize_bodies)

    detokenize_bodies = _bodies(fake, "/detokenize")
    assert detokenize_bodies, "no /detokenize request recorded"
    # vLLM's DetokenizeRequest has no skip_special_tokens field; the probe
    # must not send one.
    assert all("skip_special_tokens" not in b for b in detokenize_bodies)
    assert all(isinstance(b["tokens"], list) and b["tokens"] for b in detokenize_bodies)


def test_probe_sglang_conformant_server_passes_and_sends_flags() -> None:
    spec = get_spec("qwen3.8")
    fake = FakeInferenceServer("sglang", spec.template)
    probe = ServerProbe("sglang", "http://server.test", transport=fake.transport())

    rendered = probe.render_test_cases(spec)
    diffs = Comparator().compare(spec, rendered)

    # The fake strips <|...|> markers unless skip_special_tokens is false, so
    # all-PASS proves the flag was sent (and the "text" field was read).
    assert all(d.status == PASS for d in diffs), diffs

    tokenize_bodies = _bodies(fake, "/tokenize")
    assert tokenize_bodies
    # SGLang's TokenizeRequest has no add_generation_prompt field.
    assert all("add_generation_prompt" not in b for b in tokenize_bodies)
    detokenize_bodies = _bodies(fake, "/detokenize")
    assert all(b["skip_special_tokens"] is False for b in detokenize_bodies)


def test_probe_flags_mismatched_server_template() -> None:
    spec = get_spec("qwen3.8")
    fake = FakeInferenceServer("vllm", BROKEN_TEMPLATE)
    probe = ServerProbe("vllm", "http://server.test", transport=fake.transport())

    rendered = probe.render_test_cases(spec)
    diffs = Comparator().compare(spec, rendered)

    assert any(d.status == FAIL for d in diffs)
    failed_fields = {d.field for d in diffs if d.status == FAIL}
    assert "system_marker" in failed_fields
    assert "tool_call_wrapper" in failed_fields


def test_probe_unsupported_server_kind_rejected() -> None:
    with pytest.raises(ProbeError, match="unsupported server 'llama'"):
        ServerProbe("llama")


def test_probe_connection_error_becomes_probe_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    probe = ServerProbe("vllm", "http://localhost:9", transport=httpx.MockTransport(handler))
    with pytest.raises(ProbeError, match=r"vllm at http://localhost:9"):
        probe.render_test_cases(get_spec("qwen3.8"))


def test_probe_non_200_response_becomes_probe_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    probe = ServerProbe("sglang", "http://server.test", transport=httpx.MockTransport(handler))
    with pytest.raises(ProbeError, match=r"/tokenize returned HTTP 500"):
        probe.render_test_cases(get_spec("qwen3.8"))
