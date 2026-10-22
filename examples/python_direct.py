"""Use stored keys directly from Python, no server needed.

Setup once:
    masterapi add gemini -p gemini -m gemini-2.5-flash --embed-model gemini-embedding-001
    masterapi add openai -p openai -m gpt-4o-mini --image-model gpt-image-1
"""

from masterapi import MasterAPI, MasterAPIError, chat, embed, image

print(chat("gemini", "Name three uses for a paperclip.", system="Answer in one line."))

vectors = embed("gemini", ["cats purr", "dogs bark"])
print(f"{len(vectors)} vectors of {len(vectors[0])} dimensions")

picture = image("openai", "a lighthouse at dawn, watercolor", size="1024x1024")[0]
print(picture.get("url") or "base64 image received")

# Pick a different model for one call with "alias:model"
print(chat("gemini:gemini-2.5-pro", "Say hi."))

# Full control: OpenAI-format request and response, streaming
api = MasterAPI()
for chunk in api.chat_stream("gemini", {"messages": [{"role": "user", "content": "Count to five."}]}):
    print(chunk.decode(), end="")

try:
    chat("no-such-alias", "hi")
except MasterAPIError as e:
    print(f"\n{e.status}: {e}")
