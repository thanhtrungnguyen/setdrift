"""Content-addressed cache tests (Plan 02-04 Task 2, D-32). Fully offline."""
import json

from sica_eval.benchmark.response_cache import cache_key, load_or_call

_TOOLS = [
    {"name": "spring_boot_endpoint", "description": "d", "input_schema": {"type": "object", "properties": {}, "required": []}}
]


def test_miss_writes_file_and_returns_dict(tmp_path, mock_anthropic_client):
    data = load_or_call("claude-sonnet-4-6", "add an endpoint", _TOOLS, tmp_path)
    assert data["content"][0]["name"] == "spring_boot_endpoint"
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1  # exactly one cache file, under the passed dir
    assert json.loads(files[0].read_text(encoding="utf-8")) == data
    assert len(mock_anthropic_client) == 1  # one API call on a miss


def test_second_call_is_a_cache_hit_no_recall(tmp_path, mock_anthropic_client):
    load_or_call("claude-sonnet-4-6", "add an endpoint", _TOOLS, tmp_path)
    load_or_call("claude-sonnet-4-6", "add an endpoint", _TOOLS, tmp_path)
    assert len(mock_anthropic_client) == 1  # second call served from disk, no API call


def test_different_args_produce_different_keys():
    base = cache_key("claude-sonnet-4-6", "p", _TOOLS)
    assert base != cache_key("claude-haiku-4-5", "p", _TOOLS)  # model
    assert base != cache_key("claude-sonnet-4-6", "p2", _TOOLS)  # prompt
    assert base != cache_key("claude-sonnet-4-6", "p", [])  # toolset


def test_tool_order_does_not_change_key():
    t2 = [
        {"name": "b_skill", "description": "d"},
        {"name": "a_skill", "description": "d"},
    ]
    assert cache_key("m", "p", t2) == cache_key("m", "p", list(reversed(t2)))


def test_arm_c_omits_both_tools_and_tool_choice(tmp_path, mock_anthropic_client):
    """Arm C (tools=[]) must send create-kwargs with NEITHER tools NOR tool_choice."""
    load_or_call("claude-sonnet-4-6", "what is 2+2?", [], tmp_path)
    sent = mock_anthropic_client[-1]
    assert "tools" not in sent
    assert "tool_choice" not in sent
    assert sent["temperature"] == 0  # still deterministic


def test_arm_b_includes_tools_and_tool_choice(tmp_path, mock_anthropic_client):
    load_or_call("claude-sonnet-4-6", "add an endpoint", _TOOLS, tmp_path)
    sent = mock_anthropic_client[-1]
    assert sent["tools"] == _TOOLS
    assert sent["tool_choice"] == {"type": "auto"}
