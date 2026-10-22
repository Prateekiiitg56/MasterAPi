"""OpenAI chat format <-> native Anthropic Messages API, including tools,
images and streaming."""

import json
import time

from ..providers import CHAT

DEFAULT_MAX_TOKENS = 4096
FINISH = {"end_turn": "stop", "stop_sequence": "stop", "pause_turn": "stop",
          "max_tokens": "length", "tool_use": "tool_calls", "refusal": "content_filter"}


def _blocks(content) -> list[dict]:
    if not content:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    blocks = []
    for part in content:
        kind = part.get("type")
        if kind == "text":
            blocks.append({"type": "text", "text": part["text"]})
        elif kind == "image_url":
            url = part["image_url"]["url"] if isinstance(part["image_url"], dict) else part["image_url"]
            if url.startswith("data:"):
                header, _, data = url.partition(",")
                media_type = header[5:].split(";")[0]
                blocks.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}})
            else:
                blocks.append({"type": "image", "source": {"type": "url", "url": url}})
        else:
            raise ValueError(f"content part type '{kind}' is not supported for anthropic")
    return blocks


def _tool_choice(choice):
    if choice in ("auto", "none"):
        return {"type": choice}
    if choice == "required":
        return {"type": "any"}
    if isinstance(choice, dict):
        return {"type": "tool", "name": choice["function"]["name"]}
    return None


def _usage(input_tokens: int, output_tokens: int) -> dict:
    return {"prompt_tokens": input_tokens, "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens}


def to_anthropic(body: dict, model: str) -> dict:
    system, messages = [], []
    for m in body.get("messages", []):
        role = m.get("role")
        if role in ("system", "developer"):
            system.extend(_blocks(m.get("content")))
            continue
        if role == "tool":
            role = "user"
            blocks = [{"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": _blocks(m.get("content"))}]
        elif role == "assistant":
            blocks = _blocks(m.get("content"))
            for call in m.get("tool_calls") or []:
                fn = call["function"]
                blocks.append({"type": "tool_use", "id": call["id"], "name": fn["name"],
                               "input": json.loads(fn.get("arguments") or "{}")})
        elif role == "user":
            blocks = _blocks(m.get("content"))
        else:
            raise ValueError(f"unknown message role '{role}'")
        # Anthropic needs alternating roles; OpenAI allows repeats (e.g. several tool results).
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"].extend(blocks)
        else:
            messages.append({"role": role, "content": blocks})

    out = {"model": model, "messages": messages,
           "max_tokens": body.get("max_completion_tokens") or body.get("max_tokens") or DEFAULT_MAX_TOKENS}
    if system:
        out["system"] = system
    for k in ("temperature", "top_p", "stream"):
        if k in body:
            out[k] = body[k]
    if stop := body.get("stop"):
        out["stop_sequences"] = [stop] if isinstance(stop, str) else stop
    if tools := body.get("tools"):
        out["tools"] = [{"name": t["function"]["name"],
                         "description": t["function"].get("description", ""),
                         "input_schema": t["function"].get("parameters") or {"type": "object", "properties": {}}}
                        for t in tools]
    if choice := _tool_choice(body.get("tool_choice")):
        out["tool_choice"] = choice
    if user := body.get("user"):
        out["metadata"] = {"user_id": user}
    return out


def from_anthropic(data: dict) -> dict:
    text = "".join(b["text"] for b in data["content"] if b["type"] == "text")
    calls = [{"id": b["id"], "type": "function",
              "function": {"name": b["name"], "arguments": json.dumps(b["input"])}}
             for b in data["content"] if b["type"] == "tool_use"]
    message = {"role": "assistant", "content": text or None}
    if calls:
        message["tool_calls"] = calls
    u = data.get("usage", {})
    return {"id": data["id"], "object": "chat.completion", "created": int(time.time()), "model": data["model"],
            "choices": [{"index": 0, "message": message, "finish_reason": FINISH.get(data.get("stop_reason"), "stop")}],
            "usage": _usage(u.get("input_tokens", 0), u.get("output_tokens", 0))}


class AnthropicStream:
    """Turns Anthropic SSE lines into OpenAI chat.completion.chunk SSE events."""

    def __init__(self):
        self.id = self.model = ""
        self.created = int(time.time())
        self.input_tokens = 0
        self.tool_index: dict[int, int] = {}  # anthropic block index -> openai tool_calls index

    def _chunk(self, delta: dict, finish: str | None = None, usage: dict | None = None) -> str:
        chunk = {"id": self.id, "object": "chat.completion.chunk", "created": self.created, "model": self.model,
                 "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
        if usage:
            chunk["usage"] = usage
        return f"data: {json.dumps(chunk)}\n\n"

    def feed(self, line: str) -> list[str]:
        if not line.startswith("data:"):
            return []
        ev = json.loads(line[5:])
        kind = ev.get("type")
        if kind == "message_start":
            m = ev["message"]
            self.id, self.model = m["id"], m["model"]
            self.input_tokens = m.get("usage", {}).get("input_tokens", 0)
            return [self._chunk({"role": "assistant", "content": ""})]
        if kind == "content_block_start" and ev["content_block"]["type"] == "tool_use":
            block = ev["content_block"]
            i = self.tool_index[ev["index"]] = len(self.tool_index)
            return [self._chunk({"tool_calls": [{"index": i, "id": block["id"], "type": "function",
                                                 "function": {"name": block["name"], "arguments": ""}}]})]
        if kind == "content_block_delta":
            d = ev["delta"]
            if d["type"] == "text_delta":
                return [self._chunk({"content": d["text"]})]
            if d["type"] == "input_json_delta":
                return [self._chunk({"tool_calls": [{"index": self.tool_index[ev["index"]],
                                                     "function": {"arguments": d["partial_json"]}}]})]
        if kind == "message_delta":
            u = ev.get("usage", {})
            usage = _usage(u.get("input_tokens") or self.input_tokens, u.get("output_tokens", 0))
            return [self._chunk({}, FINISH.get(ev["delta"].get("stop_reason"), "stop"), usage)]
        if kind == "message_stop":
            return ["data: [DONE]\n\n"]
        if kind == "error":
            return [f"data: {json.dumps({'error': ev['error']})}\n\n"]
        return []


class AnthropicAdapter:
    def request(self, op: str, body: dict, model: str) -> tuple[str, dict]:
        if op != CHAT:
            raise ValueError(f"anthropic does not support {op}")
        return "/messages", to_anthropic(body, model)

    def response(self, op: str, data: dict) -> dict:
        return from_anthropic(data)

    def stream_translator(self):
        return AnthropicStream()
