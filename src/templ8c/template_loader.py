"""TemplateLoader - obtains a Jinja2 chat-template source string from a
ConformanceSpec, a local tokenizer_config.json, or a remote HF/ModelScope repo.

The m1 happy path uses the bundled reference template carried by each spec
(load_from_spec), which keeps templ8c fully functional offline. The file and
remote loaders exist so a developer can point templ8c at the real
tokenizer_config shipped with a model release and check that, not the bundled
reference.

A repo's template is read from the inline ``chat_template`` field of
tokenizer_config.json, or - when that field is absent or null, as several CN
model releases ship it - from the sibling ``chat_template.jinja`` artifact.
The same pair works for a local download, so ``--tokenizer-config`` and
``--source`` resolve an artifact the same way.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .reference.specs import ConformanceSpec

if TYPE_CHECKING:
    import httpx

TOKENIZER_CONFIG = "tokenizer_config.json"
CHAT_TEMPLATE_JINJA = "chat_template.jinja"


@dataclass(frozen=True)
class LoadedTemplate:
    """A chat template plus the artifact it was read from."""

    template: str
    artifact: str


class TemplateLoader:
    """Sources of Jinja2 chat-template text."""

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        # Optional httpx transport injection so the remote loaders are testable
        # offline (httpx.MockTransport in tests); None means real network.
        self._transport = transport

    def load_from_spec(self, spec: ConformanceSpec) -> str:
        """Return the bundled reference template for a spec (offline happy path)."""
        return spec.template

    def from_string(self, source: str) -> str:
        """Pass through an already-loaded template string (used by tests)."""
        return source

    def load_from_local(self, path: str | Path) -> LoadedTemplate:
        """Read a local template artifact, preferring its inline template.

        Mirrors the remote loader: a tokenizer_config.json that carries no
        usable ``chat_template`` falls back to the sibling
        ``chat_template.jinja`` next to it.
        """
        config_path = Path(path)
        data = json.loads(config_path.read_text(encoding="utf-8"))
        try:
            return LoadedTemplate(_extract_chat_template(data), TOKENIZER_CONFIG)
        except ValueError:
            sibling = config_path.parent / CHAT_TEMPLATE_JINJA
            if not sibling.is_file():
                raise
            template = sibling.read_text(encoding="utf-8")
            if not template.strip():
                raise ValueError(
                    f"{CHAT_TEMPLATE_JINJA} next to {config_path.name} is empty"
                ) from None
            return LoadedTemplate(template, CHAT_TEMPLATE_JINJA)

    def load_from_tokenizer_config(self, path: str | Path) -> str:
        """Extract the ``chat_template`` field from a local tokenizer_config.json.

        Handles both the single-string form and the newer list-of-objects form
        (``[{"name": ..., "template": "..."}]``) that some models ship, and
        falls back to the sibling ``chat_template.jinja`` like the remote loader.
        """
        return self.load_from_local(path).template

    def load_from_hf(self, repo_id: str) -> str:
        """Fetch the chat template from a HuggingFace repo."""
        return self.load_remote("hf", repo_id).template

    def load_from_modelscope(self, model_id: str) -> str:
        """Fetch the chat template from a ModelScope repo."""
        return self.load_remote("modelscope", model_id).template

    def load_remote(self, kind: str, ref: str) -> LoadedTemplate:
        """Fetch a remote repo's chat template and report which artifact held it."""
        if kind == "hf":
            url_for = _hf_url
        elif kind == "modelscope":
            url_for = _modelscope_url
        else:
            raise ValueError(f"unsupported template source kind '{kind}'")
        return _fetch_chat_template(url_for, ref, self._transport)


def _hf_url(ref: str, name: str) -> str:
    return f"https://huggingface.co/{ref}/resolve/main/{name}"


def _modelscope_url(ref: str, name: str) -> str:
    return (
        f"https://modelscope.cn/api/v1/models/{ref}/repo"
        f"?Revision=master&FilePath={name}"
    )


def _extract_chat_template(data: object) -> str:
    """Return the usable template in a parsed tokenizer_config.json.

    Raises ValueError (never IndexError/KeyError/TypeError) for any shape that
    carries no usable template, so callers can report it as a clean error.
    """
    if not isinstance(data, dict):
        raise ValueError("tokenizer_config.json is not a JSON object")
    template = data.get("chat_template")
    if isinstance(template, list):
        template = _first_template_entry(template)
    if not isinstance(template, str) or not template.strip():
        raise ValueError("tokenizer_config.json has no usable 'chat_template' field")
    return template


def _first_template_entry(entries: list) -> str | None:
    """The first usable template from the list-of-objects ``chat_template`` form.

    A blank entry does not shadow a later non-blank one; entry position alone
    must not decide whether the config is usable.
    """
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        template = entry.get("template")
        if isinstance(template, str) and template.strip():
            return template
    return None


def _fetch_chat_template(
    url_for: Callable[[str, str], str],
    ref: str,
    transport: httpx.BaseTransport | None = None,
) -> LoadedTemplate:
    """Fetch a repo's chat template, preferring the inline tokenizer_config field.

    Falls back to the sibling ``chat_template.jinja`` when tokenizer_config.json
    carries no usable template - the form GLM-4.5/4.6, Kimi-K2 and Qwen3-Omni
    releases use.
    """
    data = _get_json(url_for(ref, TOKENIZER_CONFIG), transport)
    try:
        return LoadedTemplate(_extract_chat_template(data), TOKENIZER_CONFIG)
    except ValueError:
        pass
    return LoadedTemplate(
        _get_text(url_for(ref, CHAT_TEMPLATE_JINJA), transport), CHAT_TEMPLATE_JINJA
    )


def _get(url: str, transport: httpx.BaseTransport | None) -> httpx.Response:
    # httpx is imported lazily so the offline path (and tests) do not require
    # it to be importable at module load.
    import httpx

    if transport is not None:
        with httpx.Client(transport=transport, follow_redirects=True, timeout=30.0) as client:
            response = client.get(url)
    else:
        response = httpx.get(url, follow_redirects=True, timeout=30.0)
    response.raise_for_status()
    return response


def _get_json(url: str, transport: httpx.BaseTransport | None) -> object:
    return _get(url, transport).json()


def _get_text(url: str, transport: httpx.BaseTransport | None) -> str:
    return _get(url, transport).text


__all__ = ["LoadedTemplate", "TemplateLoader"]
