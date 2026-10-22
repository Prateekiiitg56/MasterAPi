import json

from masterapi.adapters.anthropic import AnthropicStream, from_anthropic, to_anthropic


def test_request_translation():
    body = {
        "messages": [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": [
                {"type": "text", "text": "what is this?"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ]},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "t1", "type": "function", "function": {"name": "look", "arguments": '{"q": 1}'}}]},
            {"role": "tool", "tool_call_id": "t1", "content": "a cat"},
            {"role": "tool", "tool_call_id": "t2", "content": "a hat"},
        ],
        "tools": [{"type": "function", "function": {"name": "look", "parameters": {"type": "object"}}}],
        "tool_choice": "required", "stop": "END", "temperature": 0.2, "n": 3,
    }
    out = to_anthropic(body, "claude-x")
    assert out["system"] == [{"type": "text", "text": "be brief"}]
    assert out["max_tokens"] == 4096
    assert out["messages"][0]["content"][1] == {
        "type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}
    assert out["messages"][1]["content"] == [{"type": "tool_use", "id": "t1", "name": "look", "input": {"q": 1}}]
    # consecutive tool results merge into one user turn
    assert [b["tool_use_id"] for b in out["messages"][2]["content"]] == ["t1", "t2"]
    assert out["tools"][0]["input_schema"] == {"type": "object"}
    assert out["tool_choice"] == {"type": "any"}
    assert out["stop_sequences"] == ["END"]
    assert "n" not in out


def test_response_translation():
    data = {"id": "msg_1", "model": "claude-x", "stop_reason": "tool_use",
            "content": [{"type": "text", "text": "Let me look."},
                        {"type": "tool_use", "id": "t1", "name": "look", "input": {"q": 1}}],
            "usage": {"input_tokens": 10, "output_tokens": 5}}
    out = from_anthropic(data)
    choice = out["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["content"] == "Let me look."
    assert json.loads(choice["message"]["tool_calls"][0]["function"]["arguments"]) == {"q": 1}
    assert out["usage"] == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


def test_stream_translation():
    events = [
        {"type": "message_start", "message": {"id": "m1", "model": "claude-x", "usage": {"input_tokens": 9}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hi"}},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "t1", "name": "f"}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{\"a\""}},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 4}},
        {"type": "message_stop"},
    ]
    s = AnthropicStream()
    out = []
    for ev in events:
        out += s.feed(f"event: {ev['type']}")
        out += s.feed(f"data: {json.dumps(ev)}")
    assert out[-1] == "data: [DONE]\n\n"
    chunks = [json.loads(o[6:]) for o in out[:-1]]
    deltas = [c["choices"][0]["delta"] for c in chunks]
    assert deltas[0] == {"role": "assistant", "content": ""}
    assert deltas[1] == {"content": "Hi"}
    assert deltas[2]["tool_calls"][0]["function"]["name"] == "f"
    assert deltas[3]["tool_calls"][0] == {"index": 0, "function": {"arguments": "{\"a\""}}
    assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"
    assert chunks[-1]["usage"]["total_tokens"] == 13
