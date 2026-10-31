"""Tool-use turns are sent the way each API expects them."""

from veyntora_providers.adapters.anthropic_llm import AnthropicLLM
from veyntora_providers.adapters.openai_compat import _message
from veyntora_providers.interfaces import ChatMessage, ToolCall

CALLS = (
    ToolCall("tu_1", "get_ticket", '{"key": "SUP-1"}'),
    ToolCall("tu_2", "get_ticket", '{"key": "SUP-2"}'),
)
TURNS = [
    ChatMessage("system", "Be brief."),
    ChatMessage("user", "Status of SUP-1 and SUP-2?"),
    ChatMessage("assistant", "Looking them up.", tool_calls=CALLS),
    ChatMessage("tool", "SUP-1: open", tool_call_id="tu_1"),
    ChatMessage("tool", "SUP-2: closed", tool_call_id="tu_2"),
]


def test_anthropic_gets_tool_use_blocks_and_one_message_of_results() -> None:
    system, convo = AnthropicLLM._split(TURNS)
    assert system == "Be brief."
    assert [m["role"] for m in convo] == ["user", "assistant", "user"]
    assert convo[1]["content"] == [
        {"type": "text", "text": "Looking them up."},
        {"type": "tool_use", "id": "tu_1", "name": "get_ticket", "input": {"key": "SUP-1"}},
        {"type": "tool_use", "id": "tu_2", "name": "get_ticket", "input": {"key": "SUP-2"}},
    ]
    assert [b["tool_use_id"] for b in convo[2]["content"]] == ["tu_1", "tu_2"]


def test_openai_compatible_gets_tool_calls_on_the_assistant_turn() -> None:
    sent = _message(TURNS[2])
    assert sent["tool_calls"][0] == {
        "id": "tu_1",
        "type": "function",
        "function": {"name": "get_ticket", "arguments": '{"key": "SUP-1"}'},
    }
    assert _message(TURNS[3]) == {"role": "tool", "content": "SUP-1: open", "tool_call_id": "tu_1"}
