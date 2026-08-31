"""Checker - orchestrates the load -> render -> compare pipeline for a model.

The m1 milestone supports the template-only path: load the bundled reference
template (or any template source), render each canonical test case, and diff
the output against the model's ConformanceSpec. The optional server probe
(m3) is a follow-on and is not wired here.
"""

from __future__ import annotations

from dataclasses import dataclass

from .comparator import Comparator, TemplateDiff
from .reference.specs import ConformanceSpec, get_spec
from .render import Renderer
from .template_loader import TemplateLoader


@dataclass(frozen=True)
class CheckResult:
    """The outcome of a conformance check for one model."""

    model_id: str
    spec: ConformanceSpec
    diffs: list[TemplateDiff]

    @property
    def passed(self) -> bool:
        return all(d.status == "PASS" for d in self.diffs)

    @property
    def failed_count(self) -> int:
        return sum(1 for d in self.diffs if d.status == "FAIL")


class Checker:
    """Runs the conformance pipeline against a model id."""

    def __init__(
        self,
        loader: TemplateLoader | None = None,
        renderer: Renderer | None = None,
        comparator: Comparator | None = None,
    ) -> None:
        self.loader = loader or TemplateLoader()
        self.renderer = renderer or Renderer()
        self.comparator = comparator or Comparator()

    def check(self, model_id: str) -> CheckResult:
        """Check the bundled reference template for ``model_id``."""
        spec = get_spec(model_id)
        return self._check_source(spec, self.loader.load_from_spec(spec))

    def check_source(self, model_id: str, template_source: str) -> CheckResult:
        """Check an arbitrary template source against ``model_id``'s spec.

        Used to validate a real tokenizer_config template (loaded via
        ``TemplateLoader.load_from_tokenizer_config`` / ``load_from_hf``) or,
        in tests, a deliberately-broken template.
        """
        spec = get_spec(model_id)
        return self._check_source(spec, template_source)

    def render(self, model_id: str, message: str) -> str:
        """Render the model's reference template with a single user message."""
        spec = get_spec(model_id)
        source = self.loader.load_from_spec(spec)
        return self.renderer.render(source, [{"role": "user", "content": message}])

    def _check_source(self, spec: ConformanceSpec, source: str) -> CheckResult:
        rendered = {
            case.name: self.renderer.render(source, case.messages)
            for case in spec.test_cases
        }
        diffs = self.comparator.compare(spec, rendered)
        return CheckResult(model_id=spec.model_id, spec=spec, diffs=diffs)


__all__ = ["Checker", "CheckResult"]
