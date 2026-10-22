"""Adapters turn an OpenAI-format operation into a provider request and the
provider's reply back into the OpenAI format. They do no I/O.

Interface:
    request(op, body, model) -> (path, json_payload)
    response(op, data) -> OpenAI-format dict
    stream_translator() -> object with feed(line) -> list[str], or None to pass bytes through
"""

from ..providers import CHAT, EMBEDDINGS, IMAGES
from .anthropic import AnthropicAdapter


class OpenAIAdapter:
    PATHS = {CHAT: "/chat/completions", EMBEDDINGS: "/embeddings", IMAGES: "/images/generations"}

    def request(self, op: str, body: dict, model: str) -> tuple[str, dict]:
        return self.PATHS[op], {**body, "model": model}

    def response(self, op: str, data: dict) -> dict:
        return data

    def stream_translator(self):
        return None


class HttpAdapter:
    """Raw APIs have no typed operations; use MasterAPI.request()."""

    def request(self, op, body, model):
        raise ValueError("this alias only supports raw requests (MasterAPI.request or /proxy/...)")


ADAPTERS = {"openai": OpenAIAdapter(), "anthropic": AnthropicAdapter(), "http": HttpAdapter()}
