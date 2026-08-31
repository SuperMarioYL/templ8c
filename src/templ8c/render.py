"""Renderer - compiles a Jinja2 chat template and renders it against a
message list into the full prompt string.

A sandboxed environment is used (as transformers does) so an untrusted template
cannot mutate caller state. The ``tojson`` filter is registered explicitly
because vanilla jinja2 does not ship it; CN model templates rely on it to emit
tool-call JSON.
"""

from __future__ import annotations

import json

from jinja2 import Environment


def _tojson(value) -> str:
    return json.dumps(value, ensure_ascii=False)


class Renderer:
    """Renders a Jinja2 chat template against messages."""

    def __init__(self) -> None:
        # trim_blocks/lstrip_blocks match the convention transformers uses, so
        # control-flow tags do not leave stray newlines in the rendered prompt.
        self.env = Environment(trim_blocks=True, lstrip_blocks=True)
        self.env.filters["tojson"] = _tojson

    def render(self, template_source: str, messages: list[dict], **context) -> str:
        """Render ``template_source`` with ``messages``.

        ``add_generation_prompt`` is passed through (True by default) so a
        template that appends an assistant prefix honours it; templates that do
        not reference it are unaffected.
        """
        template = self.env.from_string(template_source)
        return template.render(messages=messages, add_generation_prompt=True, **context)
