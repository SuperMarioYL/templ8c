"""ServerProbe - captures the prompt an inference server actually renders.

The probe exercises the server's chat-template application (the same path its
OpenAI chat endpoint uses) and detokenizes the result, so the Comparator can
diff the server-rendered prompt against a ConformanceSpec. The per-server
request/response contracts follow each platform's documented API:

- vLLM: ``POST /tokenize`` with ``{"messages": [...], "add_generation_prompt":
  true}`` applies the server's chat template and returns token ids;
  ``POST /detokenize`` with ``{"tokens": [...]}`` returns
  ``{"prompt": <text>}`` (the server decodes with transformers' default
  ``skip_special_tokens=False``, so special-token markers survive).
- SGLang: the same pair is registered at ``/tokenize`` (and ``/v1/tokenize``).
  ``/tokenize`` accepts ``{"messages": [...]}`` (exactly one of prompt or
  messages); ``/detokenize`` accepts ``{"tokens": [...],
  "skip_special_tokens": false}`` and returns ``{"text": <text>}``. The flag
  must be sent explicitly - SGLang defaults it to true, which would strip the
  special-token markers this checker looks for.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .reference.specs import ConformanceSpec, TestCase

if TYPE_CHECKING:
    import httpx

SUPPORTED_SERVERS = ("vllm", "sglang")
DEFAULT_SERVER_URL = "http://localhost:8000"


class ProbeError(RuntimeError):
    """A server probe could not be completed (bad kind, transport, or response)."""


class ServerProbe:
    """Renders a spec's test cases through an inference server's chat template."""

    def __init__(
        self,
        server: str,
        base_url: str = DEFAULT_SERVER_URL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if server not in SUPPORTED_SERVERS:
            raise ProbeError(
                f"unsupported server '{server}'; supported: {', '.join(SUPPORTED_SERVERS)}"
            )
        self.server = server
        self.base_url = base_url.rstrip("/")
        # Optional httpx transport injection so the probe is testable offline
        # (httpx.MockTransport in tests); None means real network.
        self._transport = transport

    def render_test_cases(self, spec: ConformanceSpec) -> dict[str, str]:
        """Return ``{test_case_name: server_rendered_prompt}`` for a spec."""
        import httpx

        try:
            if self._transport is not None:
                with httpx.Client(transport=self._transport, timeout=30.0) as client:
                    return self._render_all(client, spec)
            with httpx.Client(timeout=30.0) as client:
                return self._render_all(client, spec)
        except ProbeError:
            raise
        except httpx.HTTPError as exc:
            raise ProbeError(
                f"server probe failed ({self.server} at {self.base_url}): {exc}"
            ) from exc

    def _render_all(self, client: httpx.Client, spec: ConformanceSpec) -> dict[str, str]:
        return {case.name: self._render_case(client, case) for case in spec.test_cases}

    def _render_case(self, client: httpx.Client, case: TestCase) -> str:
        # /tokenize applies the server's own chat template to the messages.
        tokenize_body: dict = {"messages": case.messages}
        if self.server == "vllm":
            tokenize_body["add_generation_prompt"] = True
        tokens = self._post(client, "/tokenize", tokenize_body).get("tokens")
        if not isinstance(tokens, list) or not all(isinstance(t, int) for t in tokens):
            raise ProbeError(f"{self.server} /tokenize returned no token ids")

        detokenize_body: dict = {"tokens": tokens}
        if self.server == "sglang":
            # SGLang defaults skip_special_tokens to true, which would strip
            # the <|...|> markers the conformance spec checks for.
            detokenize_body["skip_special_tokens"] = False
        response = self._post(client, "/detokenize", detokenize_body)
        text_key = "prompt" if self.server == "vllm" else "text"
        text = response.get(text_key)
        if not isinstance(text, str):
            raise ProbeError(f"{self.server} /detokenize returned no '{text_key}' text")
        return text

    def _post(self, client: httpx.Client, path: str, body: dict) -> dict:
        response = client.post(f"{self.base_url}{path}", json=body)
        if response.status_code != 200:
            raise ProbeError(
                f"{self.server} {path} returned HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )
        return response.json()


__all__ = ["ServerProbe", "ProbeError", "SUPPORTED_SERVERS", "DEFAULT_SERVER_URL"]
