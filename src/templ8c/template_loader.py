"""TemplateLoader - obtains a Jinja2 chat-template source string from a
ConformanceSpec, a local tokenizer_config.json, or a remote HF/ModelScope repo.

The m1 happy path uses the bundled reference template carried by each spec
(load_from_spec), which keeps templ8c fully functional offline. The file and
remote loaders exist so a developer can point templ8c at the real
tokenizer_config shipped with a model release and check that, not the bundled
reference.
"""

from __future__ import annotations

import json
from pathlib import Path

from .reference.specs import ConformanceSpec


class TemplateLoader:
    """Sources of Jinja2 chat-template text."""

    def load_from_spec(self, spec: ConformanceSpec) -> str:
        """Return the bundled reference template for a spec (offline happy path)."""
        return spec.template

    def from_string(self, source: str) -> str:
        """Pass through an already-loaded template string (used by tests)."""
        return source

    def load_from_tokenizer_config(self, path: str | Path) -> str:
        """Extract the ``chat_template`` field from a local tokenizer_config.json.

        Handles both the single-string form and the newer list-of-objects form
        (``[{"name": ..., "template": "..."}]``) that some models ship.
        """
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return _extract_chat_template(data)

    def load_from_hf(self, repo_id: str) -> str:
        """Fetch tokenizer_config.json from HuggingFace and return its template."""
        return _fetch_remote(f"https://huggingface.co/{repo_id}/resolve/main/tokenizer_config.json")

    def load_from_modelscope(self, model_id: str) -> str:
        """Fetch tokenizer_config.json from ModelScope and return its template."""
        return _fetch_remote(
            f"https://modelscope.cn/api/v1/models/{model_id}/repo?Revision=master&FilePath=tokenizer_config.json"
        )


def _extract_chat_template(data: dict) -> str:
    template = data.get("chat_template")
    if isinstance(template, list):
        template = template[0]["template"]
    if not isinstance(template, str) or not template.strip():
        raise ValueError("tokenizer_config.json has no usable 'chat_template' field")
    return template


def _fetch_remote(url: str) -> str:
    # httpx is imported lazily so the m1 offline path (and tests) do not require
    # it to be importable at module load.
    import httpx

    resp = httpx.get(url, follow_redirects=True, timeout=30.0)
    resp.raise_for_status()
    return _extract_chat_template(resp.json())
