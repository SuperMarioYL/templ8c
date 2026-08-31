"""ConformanceSpec - declarative primitive defining what a model's chat
template should produce, plus bundled reference templates for the supported
CN model families (GLM-5.3, Qwen3.8, DeepSeek-V4).

The spec turns the implicit knowledge of what tool-call format a model emits
into an explicit, executable contract.
"""

from __future__ import annotations

from dataclasses import dataclass


def _ot(name: str) -> str:
    """Assemble a turn-boundary token of the form with-name from individual
    code points so literal control sequences never appear in source text."""
    return chr(60) + chr(124) + name + chr(124) + chr(62)


@dataclass(frozen=True)
class RenderRule:
    """How a single message role should be rendered (the marker it must emit)."""

    role: str
    marker: str
    description: str = ""


@dataclass(frozen=True)
class TestCase:
    """A canonical message sequence to feed the template, and which spec fields
    the rendered output should satisfy."""

    name: str
    messages: list[dict]
    fields: list[str]
    description: str = ""


@dataclass(frozen=True)
class ConformanceSpec:
    """The conformance contract for one model family.

    Attributes:
        model_id: canonical family id, e.g. glm-5.3.
        tool_call_wrapper: substring the rendered tool-call region must contain.
        tool_call_json_schema: expected JSON shape; keys lists substrings
            (key names) that must appear in the rendered tool-call output.
        message_render_rules: per-role markers the template must emit.
        test_cases: canonical message sequences used to exercise the template.
        template: the bundled reference Jinja2 chat template for this family.
    """

    model_id: str
    tool_call_wrapper: str
    tool_call_json_schema: dict
    message_render_rules: list[RenderRule]
    test_cases: list[TestCase]
    template: str


# -- Reference Jinja2 chat templates ----------------------------------------
# Each template is written to satisfy its own ConformanceSpec, so a fresh
# bundled template reports all-PASS (the happy path). A real tokenizer_config
# fetched from HF/ModelScope may diverge, which the comparator catches. The
# tojson filter is registered by the Renderer environment (vanilla jinja2
# does not ship it). Turn-boundary tokens are built via _ot().

_GLM_TEMPLATE = "".join(
    [
        "{%- for message in messages -%}",
        "{%- if message['role'] == 'system' -%}", _ot("system"), "{{ message['content'] }}", _ot("end"),
        "{%- elif message['role'] == 'user' -%}", _ot("user"), "{{ message['content'] }}", _ot("end"),
        "{%- elif message['role'] == 'assistant' -%}", _ot("assistant"), "{{ message['content'] }}",
        "{%- if message.get('tool_calls') -%}", _ot("tool_calls"), "[CALL_TOOL]",
        "{%- for tc in message['tool_calls'] -%}",
        "{{ tc['function']['name'] }}({{ tc['function']['arguments'] }})",
        "{%- endfor -%}",
        "[/CALL_TOOL]{%- endif -%}", _ot("end"),
        "{%- elif message['role'] == 'tool' -%}", _ot("observation"), "{{ message['content'] }}", _ot("end"),
        "{%- endif -%}",
        "{%- endfor -%}",
    ]
)

_QWEN_TEMPLATE = "".join(
    [
        "{%- for message in messages -%}",
        "{%- if message['role'] == 'system' -%}", _ot("im_start"), "system\n{{ message['content'] }}", _ot("im_end"),
        "{%- elif message['role'] == 'user' -%}", _ot("im_start"), "user\n{{ message['content'] }}", _ot("im_end"),
        "{%- elif message['role'] == 'assistant' -%}", _ot("im_start"), "assistant\n{{ message['content'] }}",
        "{%- if message.get('tool_calls') -%}", _ot("tool_call"),
        "{{ message['tool_calls'] | tojson }}",
        "{%- endif -%}", _ot("im_end"),
        "{%- elif message['role'] == 'tool' -%}", _ot("im_start"), "tool\n{{ message['content'] }}", _ot("im_end"),
        "{%- endif -%}",
        "{%- endfor -%}",
    ]
)

_DEEPSEEK_TEMPLATE = "".join(
    [
        "{%- for message in messages -%}",
        "{%- if message['role'] == 'system' -%}", _ot("sys"), "{{ message['content'] }}", _ot("end"),
        "{%- elif message['role'] == 'user' -%}", _ot("usr"), "{{ message['content'] }}", _ot("end"),
        "{%- elif message['role'] == 'assistant' -%}", _ot("asst"), "{{ message['content'] }}",
        "{%- if message.get('tool_calls') -%}", "<tool_request>",
        "{{ message['tool_calls'] | tojson }}",
        "</tool_request>{%- endif -%}", _ot("end"),
        "{%- elif message['role'] == 'tool' -%}", _ot("tool_result"), "{{ message['content'] }}", _ot("end"),
        "{%- endif -%}",
        "{%- endfor -%}",
    ]
)


# -- Canonical test messages (shared across families; templates are role-generic) --

_SYSTEM_MSGS = [{"role": "system", "content": "You are a helpful assistant."}]
_USER_MSGS = [{"role": "user", "content": "What's the weather in SF?"}]
_TOOL_CALL_MSGS = [
    {"role": "user", "content": "What's the weather in SF?"},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city": "SF"}'},
            }
        ],
    },
]
_MULTI_TURN_MSGS = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What's the weather in SF?"},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city": "SF"}'},
            }
        ],
    },
    {"role": "tool", "content": '{"city": "SF", "temp": "65F"}'},
    {"role": "assistant", "content": "The weather in SF is 65F."},
]

_FULL_FIELDS = [
    "system_marker",
    "user_marker",
    "assistant_marker",
    "tool_call_wrapper",
    "tool_call_schema",
    "tool_marker",
]


def _common_cases() -> list[TestCase]:
    return [
        TestCase(
            name="system_prompt",
            messages=_SYSTEM_MSGS,
            fields=["system_marker"],
            description="system prompt rendering",
        ),
        TestCase(
            name="user_message",
            messages=_USER_MSGS,
            fields=["user_marker"],
            description="single user message rendering",
        ),
        TestCase(
            name="tool_call",
            messages=_TOOL_CALL_MSGS,
            fields=["tool_call_wrapper", "tool_call_schema"],
            description="assistant tool-call rendering",
        ),
        TestCase(
            name="multi_turn",
            messages=_MULTI_TURN_MSGS,
            fields=list(_FULL_FIELDS),
            description="full multi-turn with tool response",
        ),
    ]


# -- Specs -------------------------------------------------------------------

GLM_SPEC = ConformanceSpec(
    model_id="glm-5.3",
    tool_call_wrapper="[CALL_TOOL]",
    tool_call_json_schema={"format": "calltool", "keys": []},
    message_render_rules=[
        RenderRule("system", _ot("system"), "GLM system turn boundary"),
        RenderRule("user", _ot("user"), "GLM user turn boundary"),
        RenderRule("assistant", _ot("assistant"), "GLM assistant turn boundary"),
        RenderRule("tool", _ot("observation"), "GLM tool-response observation boundary"),
    ],
    test_cases=_common_cases(),
    template=_GLM_TEMPLATE,
)

QWEN_SPEC = ConformanceSpec(
    model_id="qwen3.8",
    tool_call_wrapper=_ot("tool_call"),
    tool_call_json_schema={"format": "json", "keys": ["type", "function", "name", "arguments"]},
    message_render_rules=[
        RenderRule("system", _ot("im_start") + "system", "Qwen system turn"),
        RenderRule("user", _ot("im_start") + "user", "Qwen user turn"),
        RenderRule("assistant", _ot("im_start") + "assistant", "Qwen assistant turn"),
        RenderRule("tool", _ot("im_start") + "tool", "Qwen tool turn"),
    ],
    test_cases=_common_cases(),
    template=_QWEN_TEMPLATE,
)

DEEPSEEK_SPEC = ConformanceSpec(
    model_id="deepseek-v4",
    tool_call_wrapper="<tool_request>",
    tool_call_json_schema={"format": "json", "keys": ["type", "function", "name", "arguments"]},
    message_render_rules=[
        RenderRule("system", _ot("sys"), "DeepSeek system turn"),
        RenderRule("user", _ot("usr"), "DeepSeek user turn"),
        RenderRule("assistant", _ot("asst"), "DeepSeek assistant turn"),
        RenderRule("tool", _ot("tool_result"), "DeepSeek tool-result turn"),
    ],
    test_cases=_common_cases(),
    template=_DEEPSEEK_TEMPLATE,
)

SPECS: dict[str, ConformanceSpec] = {
    "glm-5.3": GLM_SPEC,
    "qwen3.8": QWEN_SPEC,
    "deepseek-v4": DEEPSEEK_SPEC,
}

SUPPORTED_MODELS = list(SPECS)


def normalize_model_id(model_id: str) -> str:
    """Map a concrete model id (e.g. glm-5.3-flash) to its family key.

    Matching is by prefix so size and variant suffixes (-flash, -flash-next,
    .5, -instruct) collapse to the supported family.
    """
    key = model_id.strip().lower()
    for family in SPECS:
        if key == family or key.startswith(family):
            return family
    raise ValueError(
        f"unsupported model '{model_id}'; supported families: {', '.join(SPECS)}"
    )


def get_spec(model_id: str) -> ConformanceSpec:
    """Return the ConformanceSpec for a model id, normalizing variant suffixes."""
    return SPECS[normalize_model_id(model_id)]


__all__ = [
    "ConformanceSpec",
    "RenderRule",
    "TestCase",
    "GLM_SPEC",
    "QWEN_SPEC",
    "DEEPSEEK_SPEC",
    "SPECS",
    "SUPPORTED_MODELS",
    "normalize_model_id",
    "get_spec",
]
