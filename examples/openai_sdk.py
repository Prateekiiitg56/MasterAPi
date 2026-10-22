"""Use the MasterAPI server from the official OpenAI SDK.

    masterapi serve
    masterapi token create my-app
    set MASTERAPI_TOKEN=<token>        (PowerShell: $env:MASTERAPI_TOKEN="<token>")
"""

import os

from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8787/v1", api_key=os.environ["MASTERAPI_TOKEN"])

# The model is your alias name (or "alias:model").
reply = client.chat.completions.create(model="gemini", messages=[{"role": "user", "content": "Hello!"}])
print(reply.choices[0].message.content)

# Anthropic through the same OpenAI format, streaming
stream = client.chat.completions.create(
    model="claude", messages=[{"role": "user", "content": "Write a haiku about keys."}], stream=True)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="")
print()

emb = client.embeddings.create(model="openai", input="hello")
print(len(emb.data[0].embedding), "dimensions")

img = client.images.generate(model="openai", prompt="a brass key on blue velvet")
print(img.data[0].url or "base64 image received")
