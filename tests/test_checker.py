"""Tests for the m1 pipeline: spec loading, template rendering, the
Comparator, and the end-to-end Checker.

Turn-boundary tokens are built via the shared ``_ot`` helper so the test source
never embeds literal control sequences (the same convention the specs module
uses).
"""

from __future__ import annotations

import json

import pytest

from templ8c.checker import Checker, CheckResult
from templ8c.comparator import FAIL, PASS, Comparator
from templ8c.reference.specs import (
    SPECS,
    SUPPORTED_MODELS,
    ConformanceSpec,
    RenderRule,
    _ot,
    get_spec,
    normalize_model_id,
)
from templ8c.reference.specs import (
    TestCase as SpecTestCase,
)
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
    spec = ConformanceSpec(
        model_id="test",
        tool_call_wrapper="x",
        tool_call_json_schema={"keys": []},
        message_render_rules=[RenderRule("system", "S")],
        test_cases=[
            SpecTestCase(
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


def _one_case_spec(
    fields: list[str],
    *,
    messages: list[dict] | None = None,
    keys: list[str] | None = None,
    marker: str = "M",
    wrapper: str = "W",
) -> ConformanceSpec:
    return ConformanceSpec(
        model_id="test",
        tool_call_wrapper=wrapper,
        tool_call_json_schema={"keys": keys or []},
        message_render_rules=[RenderRule("user", marker)],
        test_cases=[
            SpecTestCase(
                name="case",
                messages=messages or [{"role": "user", "content": "hi"}],
                fields=fields,
            )
        ],
        template="",
    )


# -- no vacuous PASS (v0.4.0 fix) ---------------------------------------------
#
# A check whose expectation is empty (no function name and no spec key, an
# empty marker or an empty wrapper) verified nothing yet returned PASS, because
# all()-over-nothing is True and "" in output is always True.


def test_comparator_schema_without_expectations_fails() -> None:
    spec = _one_case_spec(["tool_call_schema"])
    diff = Comparator().compare(spec, {"case": ""})[0]
    assert diff.status == FAIL
    assert diff.actual != "all present"


def test_comparator_schema_without_function_name_fails() -> None:
    """A tool-call case whose call carries no function name has nothing to look for."""
    spec = _one_case_spec(
        ["tool_call_schema"],
        messages=[{"role": "assistant", "content": "", "tool_calls": [{"function": {}}]}],
    )
    diff = Comparator().compare(spec, {"case": ""})[0]
    assert diff.status == FAIL


def test_comparator_empty_marker_fails() -> None:
    spec = _one_case_spec(["user_marker"], marker="")
    diff = Comparator().compare(spec, {"case": "anything"})[0]
    assert diff.status == FAIL


def test_comparator_empty_wrapper_fails() -> None:
    spec = _one_case_spec(["tool_call_wrapper"], wrapper="")
    diff = Comparator().compare(spec, {"case": "anything"})[0]
    assert diff.status == FAIL


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


# -- local artifact resolution (v0.4.0 fixes) ---------------------------------


def test_load_from_local_falls_back_to_sibling_jinja(tmp_path) -> None:
    """The remote loader falls back to the sibling chat_template.jinja when the
    inline template is null; the local path must resolve the same artifact pair."""
    template = get_spec("qwen3.8").template
    (tmp_path / "chat_template.jinja").write_text(template, encoding="utf-8")
    config = tmp_path / "tokenizer_config.json"
    config.write_text(json.dumps({"chat_template": None}), encoding="utf-8")

    loaded = TemplateLoader().load_from_local(config)
    assert loaded.template == template
    assert loaded.artifact == "chat_template.jinja"


def test_load_from_local_reports_artifact_name(tmp_path) -> None:
    config = tmp_path / "tokenizer_config.json"
    config.write_text(json.dumps({"chat_template": "inline"}), encoding="utf-8")

    loaded = TemplateLoader().load_from_local(config)
    assert loaded.template == "inline"
    assert loaded.artifact == "tokenizer_config.json"


def test_load_from_local_without_inline_or_sibling_raises(tmp_path) -> None:
    config = tmp_path / "tokenizer_config.json"
    config.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="chat_template"):
        TemplateLoader().load_from_local(config)


def test_load_from_local_blank_sibling_raises(tmp_path) -> None:
    (tmp_path / "chat_template.jinja").write_text(" \n", encoding="utf-8")
    config = tmp_path / "tokenizer_config.json"
    config.write_text(json.dumps({"chat_template": None}), encoding="utf-8")

    with pytest.raises(ValueError, match="chat_template.jinja"):
        TemplateLoader().load_from_local(config)


def test_extract_chat_template_skips_blank_entries() -> None:
    """A blank first entry must not shadow a later usable one."""
    from templ8c.template_loader import _extract_chat_template

    entries = [{"name": "default", "template": ""}, {"name": "tool_use", "template": "T"}]
    assert _extract_chat_template({"chat_template": entries}) == "T"
    assert _extract_chat_template({"chat_template": list(reversed(entries))}) == "T"


def test_extract_chat_template_all_blank_entries_raise() -> None:
    from templ8c.template_loader import _extract_chat_template

    with pytest.raises(ValueError, match="chat_template"):
        _extract_chat_template({"chat_template": [{"template": " "}, {"template": ""}]})


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


# -- tojson filter arguments (v0.3.0 fix) -------------------------------------


def test_tojson_default_unchanged() -> None:
    """The widened filter keeps the shipped default (ensure_ascii=False)."""
    out = Renderer().render("{{ data | tojson }}", [], data={"city": "北京"})
    assert out == '{"city": "北京"}'


def test_tojson_filter_accepts_real_template_arguments() -> None:
    """Real CN templates pass keyword arguments; a one-argument filter raised
    TypeError on both of these (zai-org/GLM-4.5 uses ensure_ascii, Kimi-K2 uses
    separators)."""
    renderer = Renderer()
    assert renderer.render(
        "{{ data | tojson(ensure_ascii=False) }}", [], data={"city": "北京"}
    ) == '{"city": "北京"}'
    assert renderer.render(
        "{{ data | tojson(separators=(',', ':')) }}", [], data={"a": 1, "b": 2}
    ) == '{"a":1,"b":2}'


# -- malformed tokenizer_config shapes (v0.3.0 fix) ---------------------------


@pytest.mark.parametrize("data", [
    {"chat_template": []},
    {"chat_template": [{"name": "default"}]},
    {"chat_template": ["not a mapping"]},
    {"chat_template": [{"name": "x", "template": 3}]},
    ["not", "an", "object"],
    "a bare string",
])
def test_extract_chat_template_rejects_malformed_shapes(data) -> None:
    """Every unusable shape raises ValueError, never IndexError/KeyError/TypeError."""
    from templ8c.template_loader import _extract_chat_template

    with pytest.raises(ValueError, match="chat_template|JSON object"):
        _extract_chat_template(data)


def test_extract_chat_template_accepts_both_real_forms() -> None:
    from templ8c.template_loader import _extract_chat_template

    assert _extract_chat_template({"chat_template": "A"}) == "A"
    assert _extract_chat_template(
        {"chat_template": [{"name": "tool_use", "template": "T"}, {"name": "default", "template": "D"}]}
    ) == "T"


# -- unrenderable templates (v0.3.0 fix) --------------------------------------


def test_checker_names_the_case_that_failed_to_render() -> None:
    """A real template may need data the canonical cases do not carry (e.g. the
    GLM-4.5/4.6 templates iterate ``arguments`` as a mapping); the failure must
    be a ValueError naming the case, never a bare jinja2 TemplateError."""
    template = (
        "{% for m in messages %}{% for tc in m.get('tool_calls') or [] %}"
        "{{ tc['function']['arguments'].items() }}{% endfor %}{% endfor %}"
    )
    with pytest.raises(ValueError, match="test case 'tool_call'"):
        Checker().check_source("glm-5.3", template)


def test_checker_reports_sandbox_rejection_as_value_error() -> None:
    """The sandbox rejecting an untrusted template is a clean error too."""
    with pytest.raises(ValueError, match="test case 'system_prompt'"):
        Checker().check_source(
            "glm-5.3", "{{ ().__class__.__bases__[0].__subclasses__() | length }}"
        )


def test_checker_render_reports_render_failure_as_value_error() -> None:
    with pytest.raises(ValueError, match="failed to render"):
        Checker().render("glm-5.3", "hi", template_source="{{ nothing() }}")
