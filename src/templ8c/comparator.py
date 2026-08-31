"""Comparator - diffs rendered template output against a ConformanceSpec,
producing a list of TemplateDiff (one per checked field per test case).

The comparator is pure logic: it takes a spec plus a mapping of
{test_case_name: rendered_string} and returns field-level PASS/FAIL diffs.
It does not depend on jinja2, so it can be unit-tested with synthetic renders.
"""

from __future__ import annotations

from dataclasses import dataclass

from .reference.specs import ConformanceSpec, TestCase

PASS = "PASS"
FAIL = "FAIL"


@dataclass(frozen=True)
class TemplateDiff:
    """A single field-level comparison result.

    Attributes:
        field: the spec field being checked, e.g. ``tool_call_wrapper`` or
            ``system_marker``.
        expected: the expected value/marker from the spec.
        actual: a short description of what the rendered output contained
            (``found`` / ``all present`` on PASS, a snippet on FAIL).
        status: ``PASS`` or ``FAIL``.
    """

    field: str
    expected: str
    actual: str
    status: str


def _snippet(text: str, width: int = 80) -> str:
    collapsed = text.replace("\n", "\\n")
    if len(collapsed) <= width:
        return collapsed
    return collapsed[:width] + "..."


def _function_names(test_case: TestCase) -> list[str]:
    names: list[str] = []
    for message in test_case.messages:
        for call in message.get("tool_calls", []) or []:
            function = call.get("function", {}) or {}
            if "name" in function:
                names.append(function["name"])
    return names


class Comparator:
    """Compares rendered output against a ConformanceSpec, field by field."""

    def compare(
        self,
        spec: ConformanceSpec,
        rendered: dict[str, str],
    ) -> list[TemplateDiff]:
        """Return a TemplateDiff per field per test case.

        ``rendered`` maps each ``spec.test_cases[*].name`` to the string the
        template produced for that case.
        """
        diffs: list[TemplateDiff] = []
        for case in spec.test_cases:
            output = rendered.get(case.name, "")
            for field in case.fields:
                diffs.append(self._check_field(field, spec, case, output))
        return diffs

    def _check_field(
        self,
        field: str,
        spec: ConformanceSpec,
        case: TestCase,
        output: str,
    ) -> TemplateDiff:
        if field.endswith("_marker"):
            return self._check_marker(field, spec, output)
        if field == "tool_call_wrapper":
            return self._check_wrapper(spec, output)
        if field == "tool_call_schema":
            return self._check_schema(spec, case, output)
        return TemplateDiff(field, field, "unknown field", FAIL)

    def _check_marker(self, field: str, spec: ConformanceSpec, output: str) -> TemplateDiff:
        role = field[: -len("_marker")]
        rule = next((r for r in spec.message_render_rules if r.role == role), None)
        if rule is None:
            return TemplateDiff(field, f"rule for {role}", "no rule defined", FAIL)
        found = rule.marker in output
        return TemplateDiff(
            field=field,
            expected=rule.marker,
            actual="found" if found else _snippet(output),
            status=PASS if found else FAIL,
        )

    def _check_wrapper(self, spec: ConformanceSpec, output: str) -> TemplateDiff:
        found = spec.tool_call_wrapper in output
        return TemplateDiff(
            field="tool_call_wrapper",
            expected=spec.tool_call_wrapper,
            actual="found" if found else _snippet(output),
            status=PASS if found else FAIL,
        )

    def _check_schema(
        self,
        spec: ConformanceSpec,
        case: TestCase,
        output: str,
    ) -> TemplateDiff:
        names = _function_names(case)
        keys = spec.tool_call_json_schema.get("keys", [])
        present = all(name in output for name in names) and all(key in output for key in keys)
        expected = ",".join([*names, *keys]) if (names or keys) else "(function name)"
        return TemplateDiff(
            field="tool_call_schema",
            expected=expected,
            actual="all present" if present else _snippet(output),
            status=PASS if present else FAIL,
        )


__all__ = ["Comparator", "TemplateDiff", "PASS", "FAIL"]
