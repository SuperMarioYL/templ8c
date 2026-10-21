"""Renderer - compiles a Jinja2 chat template and renders it against a
message list into the full prompt string.

A sandboxed environment is used (as transformers does) so an untrusted template
cannot mutate caller state. The ``tojson`` filter is registered explicitly
because vanilla jinja2 does not ship it; CN model templates rely on it to emit
tool-call JSON. Like transformers, the filter accepts the keyword arguments real
templates pass (``tojson(ensure_ascii=False)``, ``tojson(separators=...)``).
"""

from __future__ import annotations

import json
from typing import Any

from jinja2.sandbox import ImmutableSandboxedEnvironment


def _tojson(
    value: Any,
    indent: int | None = None,
    ensure_ascii: bool = False,
    separators: tuple[str, str] | None = None,
    sort_keys: bool = False,
) -> str:
    """``json.dumps`` with the arguments Jinja's built-in ``tojson`` lacks.

    transformers overrides the filter the same way, because real chat templates
    call it with these keywords; a single-argument filter raises TypeError on
    them.
    """
    return json.dumps(
        value,
        indent=indent,
        ensure_ascii=ensure_ascii,
        separators=separators,
        sort_keys=sort_keys,
    )


class Renderer:
    """Renders a Jinja2 chat template against messages."""

    def __init__(self) -> None:
        # trim_blocks/lstrip_blocks match the convention transformers uses, so
        # control-flow tags do not leave stray newlines in the rendered prompt.
        # The environment is sandboxed (as transformers does) because templates
        # come from tokenizer_config.json files of third-party model releases:
        # a plain Environment lets a template walk the Python class tree.
        self.env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
        self.env.filters["tojson"] = _tojson

    def render(self, template_source: str, messages: list[dict], **context) -> str:
        """Render ``template_source`` with ``messages``.

        ``add_generation_prompt`` is passed through (True by default) so a
        template that appends an assistant prefix honours it; templates that do
        not reference it are unaffected.
        """
        template = self.env.from_string(template_source)
        return template.render(messages=messages, add_generation_prompt=True, **context)
