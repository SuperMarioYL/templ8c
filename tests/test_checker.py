"""Tests for the m1 pipeline: spec loading, template rendering, the
Comparator, and the end-to-end Checker.

Turn-boundary tokens are built via the shared ``_ot`` helper so the test source
never embeds literal control sequences (the same convention the specs module
uses).
"""

from __future__ import annotations

import pytest

from templ8c.checker import Checker, CheckResult
from templ8c.comparator import FAIL, PASS, Comparator
from templ8c.reference.specs import SPECS, SUPPORTED_MODELS, _ot, get_spec, normalize_model_id
from templ8c.render import Renderer
from templ8c.template_loader import TemplateLoader

# -- A deliberately-broken GLM template: wraps tool-calls in raw JSON instead
# of the expected [CALL_TOOL] token format. Used to prove the comparator can
# surface a targeted FAIL. -----------------------------------------------------
WRONG_GLM_TEMPLATE = "".join(
    [
        "{%- for message in messages -%}",
        "{%- if message['role'] == 'user' -%}", _ot("user"), "{{ message['content'] }}", _ot("end"),
        "{%- elif message['role'] == 'assistant' -%}", _ot("assistant"), "{{ message['content'] }}",
        "{%- if message.get('tool_calls') -%}", _ot("tool_calls"),
        "{{ message['tool_calls'] | tojson }}",
        "{%- endif -%}", _ot("end"),
        "{%- endif -%}",
        "{%- endfor -%}",
    ]
)


# -- Spec loading / normalization -------------------------------------------


@pytest.mark.parametrize("model_id, family", [
    ("glm-5.3", "glm-5.3"),
    ("glm-5.3-flash", "glm-5.3"),
    ("GLM-5.3-Flash", "glm-5.3"),
    ("qwen3.8", "qwen3.8"),
    ("qwen3.8-flash-next", "qwen3.8"),
    ("deepseek-v4", "deepseek-v4"),
    ("deepseek-v4.5", "deepseek-v4"),
])
def test_normalize_model_id_strips_variants(model_id: str, family: str) -> None:
    assert normalize_model_id(model_id) == family


def test_normalize_unsupported_raises() -> None:
    with pytest.raises(ValueError, match="unsupported model"):
        normalize_model_id("llama-4")


def test_get_spec_returns_canonical_family() -> None:
    spec = get_spec("qwen3.8-flash-next")
    assert spec.model_id == "qwen3.8"
    assert spec.tool_call_wrapper
    assert spec.template
    assert len(spec.test_cases) == 4
    assert len(spec.message_render_rules) == 4


def test_supported_models_lists_all_families() -> None:
    assert set(SUPPORTED_MODELS) == set(SPECS)


# -- Renderer ---------------------------------------------------------------


def test_renderer_renders_user_message() -> None:
    spec = get_spec("glm-5.3")
    renderer = Renderer()
    out = renderer.render(spec.template, [{"role": "user", "content": "hello"}])
    assert "hello" in out
    assert out.endswith(_ot("end"))


def test_renderer_preserves_system_content() -> None:
    spec = get_spec("qwen3.8")
    out = Renderer().render(spec.template, [{"role": "system", "content": "be helpful"}])
    assert "be helpful" in out


def test_renderer_emits_tool_call_json() -> None:
    spec = get_spec("deepseek-v4")
    messages = [
        {"role": "user", "content": "weather?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "get_weather", "arguments": '{"city": "SF"}'}}
            ],
        },
    ]
    out = Renderer().render(spec.template, messages)
    assert "get_weather" in out
    assert "function" in out


# -- Comparator -------------------------------------------------------------


def _render_all(spec) -> dict[str, str]:
    renderer = Renderer()
    return {case.name: renderer.render(spec.template, case.messages) for case in spec.test_cases}


@pytest.mark.parametrize("family", list(SPECS))
def test_comparator_all_pass_on_bundled_template(family: str) -> None:
    spec = SPECS[family]
    diffs = Comparator().compare(spec, _render_all(spec))
    assert diffs, "comparator produced no diffs"
    assert all(d.status == PASS for d in diffs), (
        f"{family} had failures: {[(d.field, d.status) for d in diffs if d.status == FAIL]}"
    )


def test_comparator_flags_wrong_tool_call_wrapper() -> None:
    spec = get_spec("glm-5.3")
    rendered = {
        case.name: Renderer().render(WRONG_GLM_TEMPLATE, case.messages)
        for case in spec.test_cases
    }
    diffs = Comparator().compare(spec, rendered)
    wrapper_diffs = [d for d in diffs if d.field == "tool_call_wrapper"]
    assert wrapper_diffs, "no tool_call_wrapper diff produced"
    assert all(d.status == FAIL for d in wrapper_diffs), "wrong wrapper should FAIL"
    # The schema check still passes: the function name is present in the JSON.
    schema_diffs = [d for d in diffs if d.field == "tool_call_schema"]
    assert schema_diffs and all(d.status == PASS for d in schema_diffs)


def test_comparator_unknown_field_fails() -> None:
    from templ8c.reference.specs import ConformanceSpec, RenderRule, TestCase

    spec = ConformanceSpec(
        model_id="test",
        tool_call_wrapper="x",
        tool_call_json_schema={"keys": []},
        message_render_rules=[RenderRule("system", "S")],
        test_cases=[
            TestCase(
                name="x",
                messages=[{"role": "system", "content": "S"}],
                fields=["bogus_field"],
            )
        ],
        template="",
    )
    diffs = Comparator().compare(spec, {"x": "anything"})
    assert diffs[0].status == FAIL
    assert diffs[0].actual == "unknown field"


# -- Checker (end to end) ---------------------------------------------------


@pytest.mark.parametrize("family", list(SPECS))
def test_checker_all_models_pass(family: str) -> None:
    result = Checker().check(family)
    assert isinstance(result, CheckResult)
    assert result.passed, f"{family} failed: {result.diffs}"
    assert result.failed_count == 0


def test_checker_check_source_flags_wrong_template() -> None:
    result = Checker().check_source("glm-5.3", WRONG_GLM_TEMPLATE)
    assert not result.passed
    assert result.failed_count >= 1
    assert any(d.field == "tool_call_wrapper" and d.status == FAIL for d in result.diffs)


def test_checker_render_returns_prompt_string() -> None:
    out = Checker().render("glm-5.3-flash", "What's the weather in SF?")
    assert isinstance(out, str)
    assert "What's the weather in SF?" in out


def test_template_loader_from_string_passthrough() -> None:
    assert TemplateLoader().from_string("abc") == "abc"


def test_template_loader_load_from_spec() -> None:
    spec = get_spec("qwen3.8")
    assert TemplateLoader().load_from_spec(spec) == spec.template


# -- Renderer sandbox (v0.2.0 fix) --------------------------------------------


def test_renderer_sandbox_blocks_attribute_escape() -> None:
    """render.py documents a sandboxed environment for untrusted templates.

    Under a plain jinja2 Environment the first payload renders
    ``<class 'str'>`` and the second walks the Python class tree (a subclass
    count); the sandbox must neutralize or reject both.
    """
    from jinja2.exceptions import TemplateError

    renderer = Renderer()
    assert "class" not in renderer.render('{{ "".__class__ }}', [])
    with pytest.raises(TemplateError):
        renderer.render("{{ ().__class__.__bases__[0].__subclasses__() | length }}", [])


def test_renderer_sandbox_still_renders_bundled_templates() -> None:
    for family in SPECS:
        spec = SPECS[family]
        out = Renderer().render(spec.template, spec.test_cases[-1].messages)
        assert out, f"{family} bundled template rendered empty under the sandbox"
