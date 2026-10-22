"""Provider registry: where each API lives, how its key is sent, and what it can do.

An alias in the vault names a provider and may override any of these fields, so
any HTTP API with a key works, not only the built-in ones.
"""

from dataclasses import dataclass, field, replace

CHAT, EMBEDDINGS, IMAGES = "chat", "embeddings", "images"
OPERATIONS = (CHAT, EMBEDDINGS, IMAGES)
ADAPTERS = ("openai", "anthropic", "http")


@dataclass(frozen=True)
class Auth:
    """How a key is attached to a request.

    Spec strings: "bearer", "none", "header:NAME", "header:NAME=TEMPLATE", "query:NAME".
    TEMPLATE contains {key}, e.g. "header:Authorization=Token {key}".
    """
    kind: str
    name: str = ""
    template: str = "{key}"

    @classmethod
    def parse(cls, spec: str) -> "Auth":
        if spec == "bearer":
            return cls("header", "Authorization", "Bearer {key}")
        if spec == "none":
            return cls("none")
        kind, _, rest = spec.partition(":")
        name, _, template = rest.partition("=")
        if kind not in ("header", "query") or not name:
            raise ValueError(f"invalid auth '{spec}': use bearer, none, header:NAME[=TEMPLATE] or query:NAME")
        return cls(kind, name, template or "{key}")

    def value(self, key: str) -> str:
        return self.template.replace("{key}", key)


@dataclass(frozen=True)
class Provider:
    base_url: str
    adapter: str = "openai"
    auth: str = "bearer"
    capabilities: tuple[str, ...] = (CHAT,)
    headers: dict = field(default_factory=dict)

    @property
    def needs_key(self) -> bool:
        return self.auth != "none"


_ALL = (CHAT, EMBEDDINGS, IMAGES)

PROVIDERS: dict[str, Provider] = {
    # OpenAI-compatible model APIs
    "openai": Provider("https://api.openai.com/v1", capabilities=_ALL),
    "openrouter": Provider("https://openrouter.ai/api/v1"),
    "gemini": Provider("https://generativelanguage.googleapis.com/v1beta/openai", capabilities=_ALL),
    "groq": Provider("https://api.groq.com/openai/v1"),
    "mistral": Provider("https://api.mistral.ai/v1", capabilities=(CHAT, EMBEDDINGS)),
    "deepseek": Provider("https://api.deepseek.com/v1"),
    "together": Provider("https://api.together.xyz/v1", capabilities=_ALL),
    "xai": Provider("https://api.x.ai/v1", capabilities=(CHAT, IMAGES)),
    "fireworks": Provider("https://api.fireworks.ai/inference/v1", capabilities=(CHAT, EMBEDDINGS)),
    "cohere": Provider("https://api.cohere.ai/compatibility/v1", capabilities=(CHAT, EMBEDDINGS)),
    "perplexity": Provider("https://api.perplexity.ai"),
    "ollama": Provider("http://localhost:11434/v1", auth="none", capabilities=(CHAT, EMBEDDINGS)),
    # Native APIs translated to the OpenAI format
    "anthropic": Provider("https://api.anthropic.com/v1", adapter="anthropic", auth="header:x-api-key",
                          headers={"anthropic-version": "2023-06-01"}),
    # Non-LLM APIs: raw passthrough only (MasterAPI.request / /proxy/{alias}/...)
    "elevenlabs": Provider("https://api.elevenlabs.io", adapter="http", auth="header:xi-api-key", capabilities=()),
    "replicate": Provider("https://api.replicate.com/v1", adapter="http", capabilities=()),
    "stability": Provider("https://api.stability.ai", adapter="http", capabilities=()),
    "deepgram": Provider("https://api.deepgram.com", adapter="http",
                         auth="header:Authorization=Token {key}", capabilities=()),
}

CUSTOM = "custom"
OVERRIDABLE = ("base_url", "adapter", "auth", "capabilities", "headers")


def provider_for(alias: dict) -> Provider:
    """Built-in provider merged with the alias's own overrides."""
    name = alias["provider"]
    if name == CUSTOM:
        base = Provider(base_url="")
    elif name in PROVIDERS:
        base = PROVIDERS[name]
    else:
        raise ValueError(f"unknown provider '{name}': use '{CUSTOM}' with --base-url for any other API")

    overrides = {k: alias[k] for k in OVERRIDABLE if alias.get(k) is not None}
    if "capabilities" in overrides:
        overrides["capabilities"] = tuple(overrides["capabilities"])
    if "headers" in overrides:
        overrides["headers"] = {**base.headers, **overrides["headers"]}
    p = replace(base, **overrides)

    if not p.base_url:
        raise ValueError("custom provider needs --base-url")
    if p.adapter not in ADAPTERS:
        raise ValueError(f"unknown adapter '{p.adapter}': use one of {', '.join(ADAPTERS)}")
    bad = set(p.capabilities) - set(OPERATIONS)
    if bad:
        raise ValueError(f"unknown capability {sorted(bad)}: use {', '.join(OPERATIONS)}")
    Auth.parse(p.auth)
    return replace(p, base_url=p.base_url.rstrip("/"))
